

from __future__ import annotations
"""
price_provider.py – Manual price provider for proprietary token
---------------------------------------------------------------
این نسخهٔ جدید مخصوص توکنی است که در هیچ صرافی فهرست نشده و قیمت آن را مدیر تعیین می‌کند.

قابلیت‌ها
~~~~~~~~~~
• ذخیرهٔ قیمت در کالکشن `settings` در MongoDB (کلید: `token_price_usd`).
• کش در حافظه (اختیاری) برای جلوگیری از کوئری زیاد. TTL پیش‌فرض 60 ثانیه.
• متدهای ساده برای دریافت و به‌روزرسانی قیمت.
• بدون وابستگی به API خارجی.

برای تغییر قیمت می‌توانید یک دستور ادمین (مثلاً `/set_price 1.75`) بنویسید که به متد `set_price` فراخوان بزند.
"""

import os
import time
import logging
from typing import Optional

from myproject_database import Database  # Async wrapper

logger = logging.getLogger(__name__)


class PriceProvider:
    """Manual price provider backed by MongoDB settings collection."""

    DEFAULT_PRICE: float = float(os.getenv("STATIC_TOKEN_PRICE", "1.0"))
    CACHE_TTL: int = int(os.getenv("PRICE_CACHE_TTL", "60"))  # seconds

    def __init__(self, db: Database):
        self.db = db
        self.settings = db.db["settings"]
        self._cache_price: Optional[float] = None
        self._cache_ts: float = 0.0

    # ───────────────────────────────────────── public API ──────────────────

    async def get_price(self) -> float:
        """Return current price in USD (float). Uses in‑memory cache."""
        now = time.time()
        if self._cache_price is not None and now - self._cache_ts < self.CACHE_TTL:
            return self._cache_price

        doc = await self.settings.find_one({"_id": "token_price_usd"})
        price = float(doc["value"]) if doc and "value" in doc else self.DEFAULT_PRICE
        self._cache_price = price
        self._cache_ts = now
        return price

    async def set_price(self, new_price: float):
        """Update price (to be called by admin command)."""
        if new_price <= 0:
            raise ValueError("Price must be positive")
        await self.settings.update_one(
            {"_id": "token_price_usd"},
            {"$set": {"value": new_price}},
            upsert=True,
        )
        # invalidate cache
        self._cache_price = new_price
        self._cache_ts = time.time()
        logger.info("Token price updated to $%s", new_price)
