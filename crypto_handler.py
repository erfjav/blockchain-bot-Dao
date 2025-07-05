
from __future__ import annotations

import httpx
from decimal import Decimal
from typing import Optional

import config
from blockchain_client import BlockchainClient, DEFAULT_USDT_CONTRACT, DECIMALS
from tronpy.abi import ERC20_ABI

COINGECKO_SIMPLE_PRICE = "https://api.coingecko.com/api/v3/simple/price"


class CryptoHandler:
    """
    Wrapper around BlockchainClient that exposes high-level helpers
    needed by DynamicPriceProvider.
    """
    def __init__(self, network: str | None = None) -> None:
        self.chain = "tron"          # فعلاً فقط ترون را پشتیبانی می‌کنیم
        # instantiate client with network from config (uses TRON_PROVIDER_URL & TRON_PRO_API_KEY internally)
        self.blockchain = BlockchainClient(network=network or config.TRON_NETWORK)

    async def get_wallet_balance(
        self,
        chain: str,
        address: str,
        token_contract: str | None = None,
    ) -> Decimal:
        """
        برمی‌گرداند موجودی توکن در ولت به‌صورت Decimal
        (برای USDT-TRC20 با ۶ رقم اعشار).
        """
        if chain.lower() != "tron":
            raise NotImplementedError("Only Tron network is implemented.")

        token_contract = token_contract or DEFAULT_USDT_CONTRACT
        # get AsyncTron client configured via BlockchainClient
        tron = await self.blockchain._get_tron()
        # include ERC20_ABI so func calls like balanceOf work
        contract = await tron.get_contract(token_contract, abi=ERC20_ABI)
        raw_balance = await contract.functions.balanceOf(address)
        return Decimal(raw_balance) / Decimal(10 ** DECIMALS)

    def asset_is_stable(self, chain: str = "tron") -> bool:
        """
        اگر پشتوانه استیبل‌کوین دلاری باشد True برمی‌گرداند.
        در این سناریو: USDT روی Tron.
        """
        return chain.lower() == "tron"

    async def get_usd_rate(self, symbol: str) -> Decimal:
        """
        نرخ برابری دارایی به دلار از CoinGecko.
        اگر پشتوانه استیبل‌کوین باشد نیازی نیست فراخوانی شود.
        """
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(
                COINGECKO_SIMPLE_PRICE,
                params={"ids": symbol, "vs_currencies": "usd"},
            )
        data = r.json()
        return Decimal(str(data.get(symbol, {}).get("usd", "0")))

    async def close(self) -> None:
        await self.blockchain.close()

    async def __aenter__(self) -> "CryptoHandler":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        await self.close()
        return False



# # crypto_handler.py
# # ─────────────────────────────────────────────────────────────────────────
# from __future__ import annotations

# import httpx
# from decimal import Decimal
# from typing import Optional

# import config
# from blockchain_client import BlockchainClient, DEFAULT_USDT_CONTRACT, DECIMALS


# COINGECKO_SIMPLE_PRICE = "https://api.coingecko.com/api/v3/simple/price"


# class CryptoHandler:
#     """
#     Wrapper around BlockchainClient that exposes high-level helpers
#     needed by DynamicPriceProvider.
#     """

#     def __init__(self, network: str | None = None) -> None:
#         self.chain = "tron"          # فعلاً فقط ترون را پشتیبانی می‌کنیم
#         self.blockchain = BlockchainClient(network=network or config.TRON_NETWORK)

#     # ────────────────────────────────────────────────
#     # Main public helpers
#     # ────────────────────────────────────────────────
#     async def get_wallet_balance(
#         self,
#         chain: str,
#         address: str,
#         token_contract: str | None = None,
#     ) -> Decimal:
#         """
#         برمی‌گرداند موجودی توکن در ولت به‌صورت Decimal
#         (برای USDT-TRC20 با ۶ رقم اعشار).
#         """
#         if chain.lower() != "tron":
#             raise NotImplementedError("Only Tron network is implemented.")

#         token_contract = token_contract or DEFAULT_USDT_CONTRACT
#         tron = await self.blockchain._get_tron()
#         contract = await tron.get_contract(token_contract)
#         raw_balance = await contract.functions.balanceOf(address)
#         return Decimal(raw_balance) / Decimal(10 ** DECIMALS)

#     def asset_is_stable(self, chain: str = "tron") -> bool:
#         """
#         اگر پشتوانه استیبل‌کوین دلاری باشد True برمی‌گرداند.
#         در این سناریو: USDT روی Tron.
#         """
#         return chain.lower() == "tron"

#     async def get_usd_rate(self, symbol: str) -> Decimal:
#         """
#         نرخ برابری دارایی به دلار از CoinGecko.
#         اگر پشتوانه استیبل‌کوین باشد نیازی نیست فراخوانی شود.
#         """
#         async with httpx.AsyncClient(timeout=10) as client:
#             r = await client.get(
#                 COINGECKO_SIMPLE_PRICE,
#                 params={"ids": symbol, "vs_currencies": "usd"},
#             )
#         data = r.json()
#         return Decimal(str(data.get(symbol, {}).get("usd", "0")))

#     # ────────────────────────────────────────────────
#     # Clean-up helpers (اختیاری)
#     # ────────────────────────────────────────────────
#     async def close(self) -> None:
#         await self.blockchain.close()

#     async def __aenter__(self) -> "CryptoHandler":
#         return self

#     async def __aexit__(self, exc_type, exc, tb) -> bool:
#         await self.close()
#         return False
