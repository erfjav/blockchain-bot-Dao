


from __future__ import annotations
"""
price_provider.py  –  Auto-pricing for proprietary token
----------------------------------------------------------------
• Price = USD balance of backing wallet ÷ circulating tokens
  (falls back to TOTAL_SUPPLY until first sale).
• Works fully async, no external price APIs or conversion required since
  wallet balance is held in USD-pegged stable-coin (e.g. USDT-TRC20).
• Caches result briefly to avoid excessive RPC calls.
• Resilient to RPC errors: falls back to cached price if available.
"""

import time
import logging
from decimal import Decimal
from typing import Optional
from myproject_database import Database          # async wrapper
from .crypto_handler import CryptoHandler         # you already use this
from config import WALLET_SPLIT_70

logger = logging.getLogger(__name__)

class DynamicPriceProvider:
    """Compute token price from on-chain backing funds."""

    # total tokens you intend to distribute (fixed constant)
    TOTAL_SUPPLY: Decimal = Decimal("9800000")

    # wallet that holds users’ payments (USDT / stable-coin)
    WALLET_CHAIN: str = "tron"
    WALLET_ADDRESS: str = WALLET_SPLIT_70

    # cache TTL for price (seconds)
    CACHE_TTL: int = 30

    def __init__(self, db: Database, crypto: CryptoHandler):
        self.db = db
        self.crypto = crypto
        self._cache_price: Optional[Decimal] = None
        self._cache_ts: float = 0.0
        
    #-----------------------------------------------------------------------------------------
    async def get_price(self) -> Decimal:
        """
        Return current token price in USD.
        Calculation:
            wallet_balance_usd ÷ max(circulating_supply, TOTAL_SUPPLY)
        """
        now = time.time()
        # return cached price if within TTL
        if self._cache_price is not None and now - self._cache_ts < self.CACHE_TTL:
            return self._cache_price

        balance_usd = await self._wallet_balance_usd()
        circulating = await self._circulating_supply()
        
        # avoid zero division by falling back to TOTAL_SUPPLY
        denominator = circulating if circulating > 0 else self.TOTAL_SUPPLY
        price = balance_usd / denominator

        # cache & return
        self._cache_price = price
        self._cache_ts = now
        return price
    
    #-----------------------------------------------------------------------------------------
    async def _wallet_balance_usd(self) -> Decimal:
        """
        Query on-chain wallet and return USD balance directly.
        Falls back to cached price if RPC fails and cache exists.
        """
        try:
            stable_balance = await self.crypto.get_wallet_balance(
                self.WALLET_CHAIN, self.WALLET_ADDRESS
            )
        except Exception as e:
            logger.error("Failed to fetch wallet balance for %s: %s", self.WALLET_ADDRESS, e)
            if self._cache_price is not None:
                return self._cache_price
            raise

        return Decimal(str(stable_balance))
    
    #-----------------------------------------------------------------------------------------
    async def _circulating_supply(self) -> Decimal:
        """
        Sum `tokens` field for all users, preserving decimals.
        Expects a `collection_users` attribute on db for Mongo collection.
        """
        pipeline = [{"$group": {"_id": None, "total": {"$sum": "$tokens"}}}]
        try:
            collection = getattr(self.db, "collection_users", None)
            if collection is None:
                collection = self.db.db["users"]
            agg = await collection.aggregate(pipeline).to_list(1)
        except Exception as e:
            logger.error("Failed to aggregate circulating supply: %s", e)
            return Decimal("0")
        total = agg[0]["total"] if agg else 0
        return Decimal(str(total))
    
    #-----------------------------------------------------------------------------------------
    async def snapshot(self) -> dict:
        """Return a dict with balance, supply, and price – handy for logs."""
        balance = await self._wallet_balance_usd()
        circ = await self._circulating_supply()
        price = await self.get_price()
        return {
            "wallet_balance_usd": float(balance),
            "circulating_supply": float(circ),
            "price_usd": float(price),
        }

