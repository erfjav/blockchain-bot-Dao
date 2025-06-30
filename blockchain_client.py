

# blockchain_client.py
"""
سرویس ساده برای بررسی تراکنش‌های USDT-TRC20 در TronScan / TronGrid.
در تولید حتماً لاجیک Rate-Limit و خطاها را کامل کنید.
"""
import os
import httpx
from typing import Optional

TRONSCAN_BASE = "https://apilist.tronscan.org/api"

class BlockchainClient:
    def __init__(self):
        self.api_key = os.getenv("TRONSCAN_API_KEY")

    async def _get(self, url: str) -> Optional[dict]:
        headers = {"TRON-PRO-API-KEY": self.api_key} if self.api_key else {}
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(url, headers=headers)
            if r.status_code != 200:
                return None
            return r.json()

    async def verify_txid(
        self,
        txid: str,
        to_address: str,
        expected_amount: float,
        min_confirmations: int = 1,
    ) -> bool:
        """
        True → تراکنش USDT-TRC20 با شرایط زیر پیدا شد:
        • گیرنده == to_address
        • amount ≥ expected_amount
        • confirmations ≥ min_confirmations
        """
        data = await self._get(f"{TRONSCAN_BASE}/transaction-info?hash={txid}")
        if not data or data.get("contractType") != 31:  # 31 == TRC20 Transfer
            return False

        # در برخی رکوردها amount در tokenInfo یا data.transferInfo می‌آید
        transfers = data.get("tokenInfo", []) or data.get("transferInfo", [])
        for tr in transfers:
            if (
                tr.get("toAddress") == to_address
                and float(tr.get("amount", 0)) >= expected_amount
                and int(data.get("confirmations", 0)) >= min_confirmations
            ):
                return True
        return False
