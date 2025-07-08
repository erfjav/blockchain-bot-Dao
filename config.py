


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

    "WALLET_JOIN_POOL_PRIVATE_KEY",  
    
    "WALLET_SPLIT_20_PRIVATE_KEY", 
        
    "WALLET_SPLIT_10_PRIVATE_KEY",
    
    "TRADE_WALLET_ADDRESS", 
    "TRADE_WALLET_PRIVATE_KEY",  
    
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

# ────────────────────────────── Blockchain / Tron (EndPoints) ───────────────────────────────
TRON_PROVIDERS: list[str] = [
    url.strip() for url in os.getenv("TRON_PROVIDERS", "https://api.trongrid.io").split(",") if url.strip()
]

# ────────────────────────────── Core corporate wallets (TronLink) ───────────────────────────────
# تمام پرداخت‌های عضویت $50 به این والت وارد می‌شود
WALLET_JOIN_POOL: str = os.getenv("WALLET_JOIN_POOL")      # Pool for joining fees
WALLET_JOIN_POOL_PRIVATE_KEY: str = os.getenv("WALLET_JOIN_POOL_PRIVATE_KEY")

WALLET_SPLIT_70: str  = os.getenv("WALLET_SPLIT_70")       # 70% تقسیم
WALLET_SPLIT_70_PRIVATE_KEY: str = os.getenv("WALLET_SPLIT_70_PRIVATE_KEY")

WALLET_SPLIT_20: str  = os.getenv("WALLET_SPLIT_20")       # 20% تقسیم
WALLET_SPLIT_20_PRIVATE_KEY: str = os.getenv("WALLET_SPLIT_20_PRIVATE_KEY")

WALLET_SPLIT_10: str  = os.getenv("WALLET_SPLIT_10")       # 10% تقسیم
WALLET_SPLIT_10_PRIVATE_KEY: str = os.getenv("WALLET_SPLIT_10_PRIVATE_KEY")

# ────────────────────────────── Admin Pools (TronLink) ───────────────────────────────
WALLET_FIRST_ADMIN_POOL: str  = os.getenv("WALLET_FIRST_ADMIN_POOL")
WALLET_FIRST_ADMIN_POOL_PRIVATE_KEY:   str = os.getenv("WALLET_FIRST_ADMIN_POOL_PRIVATE_KEY")

WALLET_SECOND_ADMIN_POOL: str = os.getenv("WALLET_SECOND_ADMIN_POOL")
WALLET_SECOND_ADMIN_POOL_PRIVATE_KEY:  str = os.getenv("WALLET_SECOND_ADMIN_POOL_PRIVATE_KEY")

# ────────────────────────────── Personal Wallets (TrustWallet) ───────────────────────────────
FIRST_ADMIN_PERSONAL_WALLETS: list[str]  = [
    w.strip() for w in os.getenv("FIRST_ADMIN_PERSONAL_WALLETS", "").split(",") if w.strip()
]
SECOND_ADMIN_PERSONAL_WALLETS: list[str] = [
    w.strip() for w in os.getenv("SECOND_ADMIN_PERSONAL_WALLETS", "").split(",") if w.strip()
]  # باید دقیقاً 5 مورد باشد

# ────────────────────────────── Staff / Role IDs ───────────────────────────────
MAIN_LEADER_IDS: list[int] = [
    int(uid.strip()) for uid in os.getenv("MAIN_LEADER_IDS", "").split(",") if uid.strip()
]  # ادمین‌های اصلی
SECOND_ADMIN_USER_IDS: list[int] = [
    int(uid.strip()) for uid in os.getenv("SECOND_ADMIN_USER_IDS", "").split(",") if uid.strip()
]  # ادمین‌های دوم که باید دو نفر جذب کنند

##############################################################################################################
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

#----------------------------------------------------------------------------
# Trading & Pool
TRADE_WALLET_ADDRESS: str = os.getenv("TRADE_WALLET_ADDRESS")      # Escrow for P2P trades  ← NEW
TRADE_WALLET_PRIVATE_KEY: str = os.getenv("TRADE_WALLET_PRIVATE_KEY")

SUPPORT_USER_USERNAME: str = os.getenv("SUPPORT_USER_USERNAME")

#------------------------------------------------------------------------
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
    #---------------------------------------
    "TRON_PROVIDERS",
    "WALLET_JOIN_POOL",
    "WALLET_JOIN_POOL_PRIVATE_KEY",
    #--------------------------------------- 
    "WALLET_SPLIT_70",
    "WALLET_SPLIT_70_PRIVATE_KEY",
    
    "WALLET_SPLIT_20",
    "WALLET_SPLIT_20_PRIVATE_KEY",
    
    "WALLET_SPLIT_10",
    "WALLET_SPLIT_10_PRIVATE_KEY"
    
    #---------------------------------------
    "WALLET_FIRST_ADMIN_POOL",
    "WALLET_SECOND_ADMIN_POOL",
    
    "WALLET_FIRST_ADMIN_POOL_PRIVATE_KEY",
    "WALLET_SECOND_ADMIN_POOL_PRIVATE_KEY",
    
    "FIRST_ADMIN_PERSONAL_WALLETS",
    
    "SECOND_ADMIN_PERSONAL_WALLETS",
    #----------------------------------------
    
    "MAIN_LEADER_IDS",
    "SECOND_ADMIN_USER_IDS",    
    #----------------------------------------
    # Wallets / Payments
    "TRADE_WALLET_ADDRESS",
    "TRADE_WALLET_PRIVATE_KEY",  
    #----------------------------------------
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
    
    #----------------------------------------
    # Pricing / Misc
    "STATIC_TOKEN_PRICE",
    "PRICE_CACHE_TTL",
    "PORT",
    # LLM
    "OPENROUTER_API_KEY",
]
