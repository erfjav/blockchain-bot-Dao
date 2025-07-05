

from __future__ import annotations
"""
price_provider.py  –  Auto-pricing for proprietary token
----------------------------------------------------------------
• Price = USD balance of backing wallet ÷ circulating tokens
  (falls back to TOTAL_SUPPLY until first sale).
• Works fully async, no external price APIs required if wallet
  balance is already in USD-pegged stable-coin (e.g. USDT, USDC).
• Caches result briefly to avoid excessive RPC calls.
"""

import os
import time
import logging
from decimal import Decimal
from typing import Optional

from myproject_database import Database          # async wrapper
from .crypto_handler import CryptoHandler         # you already use this

logger = logging.getLogger(__name__)


class DynamicPriceProvider:
    """Compute token price from on-chain backing funds."""

    # total tokens you intend to distribute
    TOTAL_SUPPLY: Decimal = Decimal(os.getenv("TOTAL_TOKEN_SUPPLY", "9800000"))

    # wallet that holds users’ payments (USDT / stable-coin)
    WALLET_CHAIN: str = os.getenv("BACKING_CHAIN", "tron")
    WALLET_ADDRESS: str = os.getenv("BACKING_ADDRESS", "")  # must be set

    CACHE_TTL: int = int(os.getenv("PRICE_CACHE_TTL", "30"))   # seconds

    def __init__(self, db: Database, crypto: CryptoHandler):
        self.db = db
        self.crypto = crypto
        self._cache_price: Optional[Decimal] = None
        self._cache_ts: float = 0.0

    # ────────────────────────────── public API ────────────────────────────
    async def get_price(self) -> Decimal:
        """
        Return current token price in USD.
        Calculation:
            wallet_balance_usd ÷ max(circulating_supply, TOTAL_SUPPLY)
        """
        now = time.time()
        if self._cache_price is not None and now - self._cache_ts < self.CACHE_TTL:
            return self._cache_price

        balance_usd = await self._wallet_balance_usd()
        circulating = await self._circulating_supply()

        denominator = circulating or self.TOTAL_SUPPLY
        price = balance_usd / Decimal(denominator)

        # cache & return
        self._cache_price = price
        self._cache_ts = now
        return price

    # ──────────────────────────── internal helpers ───────────────────────
    async def _wallet_balance_usd(self) -> Decimal:
        """
        Query on-chain wallet and convert to USD.
        Assumes wallet holds USD-pegged asset, else expand
        `CryptoHandler.get_usd_rate` as shown.
        """
        native = await self.crypto.get_wallet_balance(self.WALLET_CHAIN,
                                                      self.WALLET_ADDRESS)
        # if already a stable-coin, 1:1 to USD
        if self.WALLET_CHAIN.lower() in ("tron", "bsc") and self.crypto.asset_is_stable():
            return Decimal(native)

        rate = await self.crypto.get_usd_rate(self.WALLET_CHAIN)
        return Decimal(native) * Decimal(rate)

    async def _circulating_supply(self) -> int:
        """
        Sum `token_balance` field for all users.
        Expects a `users` collection with per-user balances.
        """
        pipeline = [{"$group": {"_id": None, "total": {"$sum": "$token_balance"}}}]
        agg = await self.db.db["users"].aggregate(pipeline).to_list(1)
        return int(agg[0]["total"]) if agg else 0

    # ─────────────────────────────── debug aid ───────────────────────────
    async def snapshot(self) -> dict:
        """Return a dict with balance, supply, and price – handy for logs."""
        balance = await self._wallet_balance_usd()
        circ = await self._circulating_supply()
        price = await self.get_price()
        return {
            "wallet_balance_usd": float(balance),
            "circulating_supply": circ,
            "price_usd": float(price),
        }



# from __future__ import annotations
# """
# price_provider.py – Manual price provider for proprietary token
# ---------------------------------------------------------------
# این نسخهٔ جدید مخصوص توکنی است که در هیچ صرافی فهرست نشده و قیمت آن را مدیر تعیین می‌کند.

# قابلیت‌ها
# ~~~~~~~~~~
# • ذخیرهٔ قیمت در کالکشن `settings` در MongoDB (کلید: `token_price_usd`).
# • کش در حافظه (اختیاری) برای جلوگیری از کوئری زیاد. TTL پیش‌فرض 60 ثانیه.
# • متدهای ساده برای دریافت و به‌روزرسانی قیمت.
# • بدون وابستگی به API خارجی.

# برای تغییر قیمت می‌توانید یک دستور ادمین (مثلاً `/set_price 1.75`) بنویسید که به متد `set_price` فراخوان بزند.
# """

# import os
# import time
# import logging
# from typing import Optional

# from myproject_database import Database  # Async wrapper

# logger = logging.getLogger(__name__)


# class PriceProvider:
#     """Manual price provider backed by MongoDB settings collection."""

#     DEFAULT_PRICE: float = float(os.getenv("STATIC_TOKEN_PRICE", "1.0"))
#     CACHE_TTL: int = int(os.getenv("PRICE_CACHE_TTL", "60"))  # seconds

#     def __init__(self, db: Database):
#         self.db = db
#         self.settings = db.db["settings"]
#         self._cache_price: Optional[float] = None
#         self._cache_ts: float = 0.0

#     # ───────────────────────────────────────── public API ──────────────────

#     async def get_price(self) -> float:
#         """Return current price in USD (float). Uses in‑memory cache."""
#         now = time.time()
#         if self._cache_price is not None and now - self._cache_ts < self.CACHE_TTL:
#             return self._cache_price

#         doc = await self.settings.find_one({"_id": "token_price_usd"})
#         price = float(doc["value"]) if doc and "value" in doc else self.DEFAULT_PRICE
#         self._cache_price = price
#         self._cache_ts = now
#         return price

#     async def set_price(self, new_price: float):
#         """Update price (to be called by admin command)."""
#         if new_price <= 0:
#             raise ValueError("Price must be positive")
#         await self.settings.update_one(
#             {"_id": "token_price_usd"},
#             {"$set": {"value": new_price}},
#             upsert=True,
#         )
#         # invalidate cache
#         self._cache_price = new_price
#         self._cache_ts = time.time()
#         logger.info("Token price updated to $%s", new_price)
