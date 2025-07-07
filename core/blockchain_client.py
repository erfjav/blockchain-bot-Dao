


# blockchain_client.py
"""
Utility class for interacting with the Tron network:

1) verify_txid(...)  ──  Validate an incoming USDT-TRC20 payment via TronScan.
2) transfer_trc20(...) ──  Send USDT-TRC20 (or any TRC-20 token) to a target address.

Environment variables
---------------------
TRONSCAN_API_KEY        Optional – higher rate-limit on TronScan
TRON_NETWORK            "mainnet"  (default)  | "nile" (testnet) | custom full-node URL
USDT_CONTRACT           Contract address if you prefer overriding the default
"""
from __future__ import annotations

import os
import asyncio
import random
from typing import Optional, Tuple

import httpx
from tronpy import AsyncTron
from tronpy.providers import AsyncHTTPProvider   # ← NEW
from tronpy.exceptions import TransactionError

import config

# ────────────────────────────────────────────────────────────
# Constants
# ────────────────────────────────────────────────────────────
TRONSCAN_BASE = "https://apilist.tronscan.org/api"

DEFAULT_USDT_CONTRACT = config.USDT_CONTRACT  # USDT-TRC20 (mainnet)

TRON_PRO_API_KEY = config.TRON_PRO_API_KEY
TRON_PROVIDER_URL = config.TRON_PROVIDER_URL

DECIMALS = 6  # USDT has 6 decimals


# ────────────────────────────────────────────────────────────
# Helper – simple exponential backoff with jitter
# ────────────────────────────────────────────────────────────
async def _sleep_backoff(attempt: int) -> None:
    base = min(2 ** attempt, 32)             # 1 → 2s, 2 → 4s, … capped at 32s
    await asyncio.sleep(base + random.random())


# ────────────────────────────────────────────────────────────
# Main client
# ────────────────────────────────────────────────────────────
class BlockchainClient:
    def __init__(self, network: str | None = None) -> None:
        
        self.network: str = network or config.TRON_NETWORK
        self.api_key: Optional[str] = config.TRONSCAN_API_KEY

        # AsyncTron اتصال را فقط در صورت نیاز می‌سازیم
        self._tron: AsyncTron | None = None

    # ────────────────────────────────────────────────
    # Internal helpers
    # ────────────────────────────────────────────────
    async def _http_get(self, url: str, max_retries: int = 3) -> Optional[dict]:
        """
        GET with simple retry / back-off.
        """
        headers = {"TRON-PRO-API-KEY": self.api_key} if self.api_key else {}
        attempt = 0
        while attempt < max_retries:
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    r = await client.get(url, headers=headers)
                if r.status_code == 200:
                    return r.json()

                # 429 یا 5xx  → دوباره تلاش
                if r.status_code in (429, 503, 500):
                    attempt += 1
                    await _sleep_backoff(attempt)
                    continue
                return None
            except httpx.RequestError:
                attempt += 1
                await _sleep_backoff(attempt)
        return None

    #───────────────────────────────────────────────────────────
    async def _get_tron(self) -> AsyncTron:
        """
        Singleton AsyncTron with custom HTTP provider + API-Key.
        برای هر فراخوانی بعدی همان شیء کش‌شده برگردانده می‌شود.
        """
        if self._tron is None:
            provider = AsyncHTTPProvider(
                endpoint_uri=TRON_PROVIDER_URL,  # مثلاً https://api.trongrid.io
                api_key=TRON_PRO_API_KEY,        # هدر TRON-PRO-API-KEY
            )

            self._tron = AsyncTron(
                provider=provider,
                network=self.network,            # "mainnet" یا "nile"
            )

        return self._tron

    # ────────────────────────────────────────────────
    # Public ① – Verify incoming payment
    # ────────────────────────────────────────────────
    async def verify_txid(
        self,
        txid: str,
        to_address: str,
        expected_usdt_amount: float,
        *,
        min_confirmations: int = 1,
        token_contract: str | None = None,
    ) -> bool:
        """
        Returns True if a TRC-20 transfer matching the criteria is found.

        Criteria:
        • contractType == 31 (TRC-20 Transfer)
        • toAddress matches
        • amount ≥ expected_usdt_amount
        • confirmations ≥ min_confirmations
        • tokenAddress matches (defaults to USDT contract)
        """
        token_contract = token_contract or DEFAULT_USDT_CONTRACT

        data = await self._http_get(f"{TRONSCAN_BASE}/transaction-info?hash={txid}")
        if not data or data.get("contractType") != 31:
            return False

        confirmations = int(data.get("confirmations", 0))
        if confirmations < min_confirmations:
            return False

        # TronScan sometimes places transfers under different keys
        transfers: list[dict] = (
            data.get("tokenTransferInfo", [])
            or data.get("tokenInfo", [])
            or data.get("transferInfo", [])
        )

        for tr in transfers:
            if (
                tr.get("toAddress") == to_address
                and tr.get("tokenAddress", token_contract) == token_contract
                and float(tr.get("amount", 0)) >= expected_usdt_amount
            ):
                return True
        return False

    # ────────────────────────────────────────────────
    # Public ② – Send USDT-TRC20
    # ────────────────────────────────────────────────
    async def transfer_trc20(
        self,
        from_private_key: str,
        to_address: str,
        amount: float,
        *,
        token_contract: str | None = None,
        decimals: int = DECIMALS,
        memo: str | None = "membership split",
    ) -> str:
        """
        Signs & broadcasts a TRC-20 transfer. Returns the resulting txid.

        Raises TransactionError on failure.
        """
        token_contract = token_contract or DEFAULT_USDT_CONTRACT
        tron = await self._get_tron()

        # owner address derived from the private key
        wallet = tron.generate_wallet(private_key=from_private_key)
        contract = await tron.get_contract(token_contract)

        txn = (
            contract.functions.transfer(
                to_address,
                int(round(amount * (10**decimals))),
            )
            .with_owner(wallet.default_address)
            .memo(memo or "")
            .build()
            .sign(from_private_key)
        )

        result = await txn.broadcast()
        if result.get("result"):
            return result["txid"]
        raise TransactionError(result)

    # ────────────────────────────────────────────────
    # Clean-up
    # ────────────────────────────────────────────────
    async def close(self) -> None:
        if self._tron is not None:
            await self._tron.close()
            self._tron = None

    # Context-manager sugar (optional use:  async with BlockchainClient() as bc: …)
    async def __aenter__(self) -> "BlockchainClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        await self.close()
        return False  # propagate exception if any


