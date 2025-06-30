


from __future__ import annotations
"""
config.py – Environment variable loader for Token‑Referral Bot
-------------------------------------------------------------
• تمام متغیرهای لازم را از محیط می‌خواند و اعتبارسنجی می‌کند.
• مقادیر را به نام‌های پایتونی اکسپورت می‌کند تا در کل پروژه ایمپورت شوند.

نکته: اگر متغیری «اختیاری» است، مقدار پیش‌فرض دارد و خطا نمی‌دهد.
"""

import os
from typing import List

# ────────────────────────────── الزامی‌ها ───────────────────────────────
REQUIRED_VARS = [
    "TELEGRAM_BOT_TOKEN",
    "WEBHOOK_URL",
    "MONGODB_URI",
    "TRADE_WALLET_ADDRESS",      # ← NEW
    "POOL_WALLET_ADDRESS",
    "PAYMENT_WALLET_ADDRESS",
    "TRADE_CHANNEL_ID",
    "SUPPORT_USER_USERNAME",
    "ADMIN_USER_IDS",  # کاما جدا شده (1,2,3)
]

missing = [var for var in REQUIRED_VARS if not os.getenv(var)]
if missing:
    raise ValueError(f"Missing required environment variables: {', '.join(missing)}")

# ────────────────────────────── مقادیر ────────────────────────────────
TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN")
WEBHOOK_URL: str = os.getenv("WEBHOOK_URL")
MONGODB_URI: str = os.getenv("MONGODB_URI")
POOL_WALLET_ADDRESS: str = os.getenv("POOL_WALLET_ADDRESS")
PAYMENT_WALLET_ADDRESS: str = os.getenv("PAYMENT_WALLET_ADDRESS")
TRADE_WALLET_ADDRESS: str = os.getenv("TRADE_WALLET_ADDRESS")      # Escrow for P2P trades  ← NEW
SUPPORT_USER_USERNAME: str = os.getenv("SUPPORT_USER_USERNAME")

# اعدادی که به int باید تبدیل شوند
TRADE_CHANNEL_ID: int = int(os.getenv("TRADE_CHANNEL_ID"))

# لیست ادمین‌ها (عدد صحیح)
ADMIN_USER_IDS: List[int] = [int(uid.strip()) for uid in os.getenv("ADMIN_USER_IDS").split(",")]

# ────────────────────────────── اختیاری‌ها ─────────────────────────────
STATIC_TOKEN_PRICE: float = float(os.getenv("STATIC_TOKEN_PRICE", "1.0"))
PRICE_CACHE_TTL: int = int(os.getenv("PRICE_CACHE_TTL", "60"))  # ثانیه
PORT: int = int(os.getenv("PORT", "8000"))

# LLM / ترجمه (در صورت استفاده)
OPENROUTER_API_KEY: str | None = os.getenv("OPENROUTER_API_KEY")

# ────────────────────────────── __all__ ────────────────────────────────
__all__ = [
    "TELEGRAM_BOT_TOKEN",
    "WEBHOOK_URL",
    "MONGODB_URI",
    "POOL_WALLET_ADDRESS",
    "PAYMENT_WALLET_ADDRESS",
    "TRADE_WALLET_ADDRESS",          # ← NEW
    "SUPPORT_USER_USERNAME",
    "TRADE_CHANNEL_ID",
    "ADMIN_USER_IDS",
    "STATIC_TOKEN_PRICE",
    "PRICE_CACHE_TTL",
    "PORT",
    "OPENROUTER_API_KEY",
]
