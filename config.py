


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
    # — Core
    "TELEGRAM_BOT_TOKEN",
    "WEBHOOK_URL",
    "MONGODB_URI",
    
    # — Wallets / Payments
    "TREASURY_WALLET",
    "TREASURY_PRIVATE_KEY",
    "SPLIT_WALLET_A",
    "SPLIT_WALLET_B",
    "SPLIT_WALLET_C",    
    
    "SPLIT_WALLET_A_PRIV",     
    
    "TRADE_WALLET_ADDRESS",      
    "POOL_WALLET_ADDRESS",
    "PAYMENT_WALLET_ADDRESS",
    "TRADE_CHANNEL_ID",
    "SUPPORT_USER_USERNAME",
    "ADMIN_USER_IDS",  # کاما جدا شده (1,2,3)
    
    # — Blockchain / Tron (now required)
    "TRON_PROVIDER_URL",  # new
    "TRON_PRO_API_KEY",   # new
]

missing = [var for var in REQUIRED_VARS if not os.getenv(var)]
if missing:
    raise ValueError(f"Missing required environment variables: {', '.join(missing)}")

# ────────────────────────────── مقادیر ────────────────────────────────

# Telegram / Webhook
TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN")
WEBHOOK_URL: str = os.getenv("WEBHOOK_URL")

# Database
MONGODB_URI: str = os.getenv("MONGODB_URI")

# Wallets
TREASURY_WALLET: str = os.getenv("TREASURY_WALLET").lower()
TREASURY_PRIVATE_KEY: str = os.getenv("TREASURY_PRIVATE_KEY")
SPLIT_WALLET_A: str = os.getenv("SPLIT_WALLET_A").lower()
SPLIT_WALLET_B: str = os.getenv("SPLIT_WALLET_B").lower()
SPLIT_WALLET_C: str = os.getenv("SPLIT_WALLET_C").lower()

SPLIT_WALLET_A_PRIV: str = os.getenv("SPLIT_WALLET_A_PRIV")

# Trading & Pool
POOL_WALLET_ADDRESS: str = os.getenv("POOL_WALLET_ADDRESS")
PAYMENT_WALLET_ADDRESS: str = os.getenv("PAYMENT_WALLET_ADDRESS")
TRADE_WALLET_ADDRESS: str = os.getenv("TRADE_WALLET_ADDRESS")      # Escrow for P2P trades  ← NEW
SUPPORT_USER_USERNAME: str = os.getenv("SUPPORT_USER_USERNAME")

# Support / Admin
# اعدادی که به int باید تبدیل شوند
TRADE_CHANNEL_ID: int = int(os.getenv("TRADE_CHANNEL_ID"))
ADMIN_USER_IDS: List[int] = [int(uid.strip()) for uid in os.getenv("ADMIN_USER_IDS").split(",")]


# ────────────────────────────── اختیاری‌ها ─────────────────────────────

# Blockchain / Tron
TRON_NETWORK: str = os.getenv("TRON_NETWORK", "mainnet")                # mainnet | nile | URL

TRON_PROVIDER_URL: str | None = os.getenv("TRON_PROVIDER_URL", "https://api.trongrid.io")          # optional custom provider URI
TRON_PRO_API_KEY: str | None = os.getenv("TRON_PRO_API_KEY")            # optional API key for Tron Pro services

TRONSCAN_API_KEY: str | None = os.getenv("TRONSCAN_API_KEY")

USDT_CONTRACT: str = os.getenv(
    "USDT_CONTRACT",
    "TXLAQ63Xg1NAzckPwKHvzw7CSEmLMEqcdj",
)

STATIC_TOKEN_PRICE: float = float(os.getenv("STATIC_TOKEN_PRICE", "1.0"))
PRICE_CACHE_TTL: int = int(os.getenv("PRICE_CACHE_TTL", "60"))  # ثانیه
PORT: int = int(os.getenv("PORT", "8000"))

# LLM / ترجمه (در صورت استفاده)
OPENROUTER_API_KEY: str | None = os.getenv("OPENROUTER_API_KEY")

# ────────────────────────────── __all__ ────────────────────────────────
__all__ = [
    # Core
    "TELEGRAM_BOT_TOKEN",
    "WEBHOOK_URL",
    "MONGODB_URI",
    
    # Wallets / Payments
    "TREASURY_WALLET",
    "TREASURY_PRIVATE_KEY",
    "SPLIT_WALLET_A",
    "SPLIT_WALLET_B",
    "SPLIT_WALLET_C",
    "SPLIT_WALLET_A_PRIV",
    
    "POOL_WALLET_ADDRESS",
    "PAYMENT_WALLET_ADDRESS",
    "TRADE_WALLET_ADDRESS",
    
    # Trading / Support
    "TRADE_CHANNEL_ID",
    "SUPPORT_USER_USERNAME",
    "ADMIN_USER_IDS",
    
    # Blockchain
    "TRON_NETWORK",
    "TRON_PROVIDER_URL",
    "TRON_PRO_API_KEY",
    "TRONSCAN_API_KEY",
    "USDT_CONTRACT",
    
    # Pricing / Misc
    "STATIC_TOKEN_PRICE",
    "PRICE_CACHE_TTL",
    "PORT",
    # LLM
    "OPENROUTER_API_KEY",
]
