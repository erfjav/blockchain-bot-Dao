# crypto_handler.py
# ─────────────────────────────────────────────────────────────────────────
from __future__ import annotations

import httpx
from decimal import Decimal
from typing import Optional

import config
from .blockchain_client import BlockchainClient, DEFAULT_USDT_CONTRACT, DECIMALS

# Define the ERC20 ABI manually since it's not available in this tronpy version
ERC20_ABI = [
    {
        "constant": True,
        "inputs": [{"name": "_owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "balance", "type": "uint256"}],
        "type": "function"
    },
    {
        "constant": False,
        "inputs": [
            {"name": "_to", "type": "address"},
            {"name": "_value", "type": "uint256"}
        ],
        "name": "transfer",
        "outputs": [{"name": "", "type": "bool"}],
        "type": "function"
    },
    {
        "constant": True,
        "inputs": [],
        "name": "decimals",
        "outputs": [{"name": "", "type": "uint8"}],
        "type": "function"
    },
    {
        "constant": True,
        "inputs": [],
        "name": "symbol",
        "outputs": [{"name": "", "type": "string"}],
        "type": "function"
    },
    {
        "constant": True,
        "inputs": [],
        "name": "name",
        "outputs": [{"name": "", "type": "string"}],
        "type": "function"
    }
]

COINGECKO_SIMPLE_PRICE = "https://api.coingecko.com/api/v3/simple/price"


class CryptoHandler:
    """
    Wrapper around BlockchainClient that exposes high-level helpers
    needed by DynamicPriceProvider.
    """

    def __init__(self, network: str | None = None) -> None:
        self.chain = "tron"          # فعلاً فقط ترون را پشتیبانی می‌کنیم
        self.blockchain = BlockchainClient(network=network or config.TRON_NETWORK)

    # ────────────────────────────────────────────────
    # Main public helpers
    # ────────────────────────────────────────────────
    
    async def get_wallet_balance(
        self,
        chain: str,
        address: str,
        token_contract: str | None = None,
        decimals: int = 6,
    ) -> Decimal:
        """
        برمی‌گرداند موجودی توکن در ولت به‌صورت Decimal
        (برای USDT-TRC20 با ۶ رقم اعشار به‌صورت پیش‌فرض).
        """
        if chain.lower() != "tron":
            raise NotImplementedError("Only Tron network is implemented.")

        # استفاده از قرارداد توکن پیش‌فرض در صورت عدم ارسال
        token_contract = token_contract or DEFAULT_USDT_CONTRACT

        try:
            # تبدیل آدرس Tron به هگز
            if address.startswith("T"):
                hex_address = address.replace("T", "41", 1)
            else:
                hex_address = address
            # اطمینان از طول ۴۲ کاراکتری (۲ حرف ۰x + 40 کاراکتر)
            hex_address = hex_address.rjust(42, "0")

            # آماده‌سازی داده برای فراخوانی تابع balanceOf(address)
            function_selector = "balanceOf(address)"
            parameter = hex_address[2:].ljust(64, "0")  # حذف پیشوند 0x و padding تا 64 کاراکتر

            # ارسال درخواست به TronGrid
            url = f"{config.TRON_PROVIDER_URL}/wallet/triggerconstantcontract"
            payload = {
                "owner_address": hex_address,         # بهتر owner را همان آدرس hex کاربر بگذارید
                "contract_address": token_contract,
                "function_selector": function_selector,
                "parameter": parameter,
                "visible": True
            }
            headers = {}
            if getattr(config, "TRON_PRO_API_KEY", None):
                headers["TRON-PRO-API-KEY"] = config.TRON_PRO_API_KEY

            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(url, json=payload, headers=headers)
                data = resp.json()

            # در صورت پاسخ موفق و وجود constant_result
            results = data.get("constant_result") or []
            if data.get("result", {}).get("result") and results:
                raw_hex = results[0]
                raw_balance = int(raw_hex, 16)
                # تقسیم با توجه به دقت (decimals)
                return Decimal(raw_balance) / (Decimal(10) ** decimals)
            else:
                return Decimal("0")

        except Exception as e:
            # در صورت هر خطا، صفر برگردان
            print(f"Error getting balance: {e}")
            return Decimal("0")    
    
    # async def get_wallet_balance(
    #     self,
    #     chain: str,
    #     address: str,
    #     token_contract: str | None = None,
    #     decimals: int = 6,
    # ) -> Decimal:
    #     """
    #     برمی‌گرداند موجودی توکن در ولت به‌صورت Decimal
    #     (برای USDT-TRC20 با ۶ رقم اعشار).
    #     """
    #     if chain.lower() != "tron":
    #         raise NotImplementedError("Only Tron network is implemented.")

    #     token_contract = token_contract or DEFAULT_USDT_CONTRACT
        
    #     # ✅ Simple solution: Use HTTP API directly
    #     try:
    #         # Convert Tron address to hex format for API call
    #         hex_address = address.replace("T", "41") if address.startswith("T") else address
    #         if len(hex_address) < 42:
    #             hex_address = hex_address.ljust(42, "0")
            
    #         # Prepare the function call data for balanceOf
    #         function_selector = "balanceOf(address)"
    #         parameter = hex_address[2:].ljust(64, "0")  # Remove "41" prefix and pad to 64 chars
            
    #         # Call TronGrid API
    #         url = f"{config.TRON_PROVIDER_URL}/wallet/triggerconstantcontract"
    #         payload = {
    #             "owner_address": "410000000000000000000000000000000000000000",
    #             "contract_address": token_contract,
    #             "function_selector": function_selector,
    #             "parameter": parameter,
    #             "visible": True
    #         }
            
    #         headers = {}
    #         if config.TRON_PRO_API_KEY:
    #             headers["TRON-PRO-API-KEY"] = config.TRON_PRO_API_KEY
            
    #         async with httpx.AsyncClient(timeout=10) as client:
    #             response = await client.post(url, json=payload, headers=headers)
    #             data = response.json()
                
    #             if data.get("result", {}).get("result") and data.get("constant_result"):
    #                 hex_result = data["constant_result"][0]
    #                 raw_balance = int(hex_result, 16)
    #                 return Decimal(raw_balance) / Decimal(10 ** DECIMALS)
    #             else:
    #                 return Decimal("0")
                    
    #     except Exception as e:
    #         # Fallback to zero if everything fails
    #         print(f"Error getting balance: {e}")
    #         return Decimal("0")

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
##################################################################################################

    async def transfer(self, chain, to, amount, token_symbol="USDT", decimals=6):
        if chain.lower() != "tron":
            raise NotImplementedError("Only Tron is supported.")

        if token_symbol != "USDT":
            raise NotImplementedError("Only USDT token is currently supported.")

        # مقدار amount فرض کن integer میکروUSDT است (مثلاً 1000000 یعنی 1 USDT)
        float_amount = amount / (10 ** decimals)
        private_key = config.TREASURY_PRIVATE_KEY

        return await self.blockchain.transfer_trc20(
            from_private_key=private_key,
            to_address=to,
            amount=float_amount,
            token_contract=DEFAULT_USDT_CONTRACT,
            decimals=decimals,
        )


    async def estimate_fee(self, chain, to, amount, token_symbol="USDT", decimals=6):
        if chain.lower() != "tron":
            raise NotImplementedError("Only Tron is supported.")
        # TODO: در آینده اینجا call به API Tron برای محاسبه fee واقعی
        return Decimal("0.6")  # فی فعلاً ثابت


    # ────────────────────────────────────────────────
    # Clean-up helpers (اختیاری)
    # ────────────────────────────────────────────────
    async def close(self) -> None:
        await self.blockchain.close()

    async def __aenter__(self) -> "CryptoHandler":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        await self.close()
        return False
