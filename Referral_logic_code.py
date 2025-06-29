

from __future__ import annotations
"""
Referral_logic_code.py   (v3 – with depletion handling)
=======================================================
• توزیع توکن نزولی تا سقف ۹٬۸۰۰٬۰۰۰ واحد
• در صورت اتمام موجودی، خطای TokensDepletedError بالا می‌رود تا لایهٔ بالاتر (signup) بتواند:
    – پیام «ظرفیت توکن‌ها تکمیل شده» به کاربر بدهد
    – یا ثبت نام را قفل کند
• لاگ سروری در سطح WARNING ثبت می‌شود.

برای سادگی، Exception جدید تعریف شد و در پایان فایل export می‌شود.
"""

import logging
import os
import uuid
from datetime import datetime
from typing import Optional, List, Dict, Any, Deque

from pymongo import ReturnDocument

from myproject_database import Database

from config import POOL_WALLET_ADDRESS

logger = logging.getLogger(__name__)


class TokensDepletedError(RuntimeError):
    """Raised when user-token supply (9.8M) is exhausted."""


class ReferralManager:
    # ---------- constants ----------
    JOIN_FEE_USD: float = 50.0
    COMMISSION_RATE: float = 0.10

    TOKEN_SUPPLY_TOTAL = 20_000_000
    TOKEN_SUPPLY_FOR_USERS = 9_800_000
    TOKEN_START_PER_USER = 200.0
    TOKEN_DECREMENT_PER_USER = 0.02

    def __init__(self, db: Database, *, pool_wallet: Optional[str] = None):
        self.db = db
        self.users = db.collection_users
        self.payments = db.db["payments"]
        self.counters = db.db["counters"]
        self.pool_wallet = POOL_WALLET_ADDRESS


    # ------------------------------------------------------------------
    async def ensure_user(
        self,
        chat_id: int,
        first_name: str,
        inviter_code: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        اطمینان از وجود پروفایل کامل کاربر:
        • اگر کاربر قبلاً ثبت شده اما فیلدهای کلیدی ناقص‌اند، آن‌ها را تکمیل می‌کند.
        • در غیر این‌صورت، کاربر جدید می‌سازد و توکن/کمیسیون تخصیص می‌دهد.
        برمی‌گرداند: دیکشنری کامل پروفایل (بدون _id)
        """
        # ── ➊ جستجوی سند موجود
        doc: Dict[str, Any] | None = await self.users.find_one(
            {"user_id": chat_id},
            {"_id": 0},
        )

        # ───────────── حالت الف: سند موجود ولی ناقص ─────────────
        if doc:
            updates: Dict[str, Any] = {}

            # member_no و referral_code را در صورت نبود ایجاد می‌کنیم
            if "member_no" not in doc:
                updates["member_no"] = await self._next_member_no()
            if "referral_code" not in doc:
                updates["referral_code"] = await self._generate_unique_code()

            # first_name را هم اگر خالی بود به‌روزرسانی می‌کنیم
            if not doc.get("first_name") and first_name:
                updates["first_name"] = first_name

            if updates:
                await self.users.update_one({"user_id": chat_id}, {"$set": updates})
                doc |= updates  # ادغام دیکشنری‌ها در پایتون 3.9+

            return doc

        # ───────────── حالت ب: کاربر جدید ─────────────
        referral_code: str = await self._generate_unique_code()
        member_no: int = await self._next_member_no()

        inviter_id, ancestors = await self._resolve_inviter_chain(inviter_code)

        # ممکن است TokensDepletedError بیندازد
        tokens_allocated: int = await self._allocate_tokens()

        doc = {
            "user_id": chat_id,
            "member_no": member_no,
            "first_name": first_name,
            "created_at": datetime.utcnow(),
            "referral_code": referral_code,
            "inviter_id": inviter_id,
            "tokens": tokens_allocated,
            "commission_usd": 0.0,
            "joined": False,            # بعد از پرداخت True می‌شود
        }

        await self.users.insert_one(doc)

        # کمیسیون به زنجیرهٔ والدین
        await self._distribute_commission(new_user_id=chat_id, ancestors=ancestors)

        return {k: v for k, v in doc.items() if k != "_id"}
        
    
    # async def ensure_user(
    #     self, chat_id: int, first_name: str, inviter_code: Optional[str] = None
    # ) -> Dict[str, Any]:
    #     """Register user, allocate tokens, distribute commissions."""
    #     # Return if exists
    #     doc = await self.users.find_one({"user_id": chat_id}, {"_id": 0})
    #     if doc:
    #         return doc

    #     referral_code = await self._generate_unique_code()
    #     member_no = await self._next_member_no()

    #     inviter_id, ancestors = await self._resolve_inviter_chain(inviter_code)

    #     # Allocate tokens – may raise TokensDepletedError
    #     tokens_allocated = await self._allocate_tokens()

    #     await self.users.insert_one(
    #         {
    #             "user_id": chat_id,
    #             "member_no": member_no,
    #             "first_name": first_name,
    #             "created_at": datetime.utcnow(),
    #             "referral_code": referral_code,
    #             "inviter_id": inviter_id,
    #             "tokens": tokens_allocated,
    #             "commission_usd": 0.0,
    #         }
    #     )

    #     await self._distribute_commission(new_user_id=chat_id, ancestors=ancestors)

    #     return await self.users.find_one({"user_id": chat_id}, {"_id": 0})

    # ------------------------------------------------------------------
    async def _resolve_inviter_chain(self, inviter_code: Optional[str]):
        inviter_id: Optional[int] = None
        ancestors: List[int] = []
        if inviter_code:
            doc = await self.users.find_one({"referral_code": inviter_code})
            if doc:
                inviter_id = doc["user_id"]
                temp = inviter_id
                while temp:
                    ancestor = await self.users.find_one({"user_id": temp}, {"inviter_id": 1})
                    if not ancestor:
                        break
                    ancestors.append(temp)
                    temp = ancestor.get("inviter_id")
        return inviter_id, ancestors

    # ---------------- token allocation ----------------
    async def _allocate_tokens(self) -> float:
        doc = await self.counters.find_one_and_update(
            {"_id": "token_distribution"},
            {"$setOnInsert": {"index": 0, "distributed": 0.0}},
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        idx, distributed = int(doc["index"]), float(doc["distributed"])
        remaining = self.TOKEN_SUPPLY_FOR_USERS - distributed
        if remaining <= 0:
            logger.warning("Token supply for users exhausted (%.0f distributed)", distributed)
            raise TokensDepletedError("Token supply exhausted; registration closed.")

        tokens_for_user = max(self.TOKEN_START_PER_USER - idx * self.TOKEN_DECREMENT_PER_USER, 0)
        if tokens_for_user > remaining:
            tokens_for_user = remaining  # give only leftover

        await self.counters.update_one(
            {"_id": "token_distribution"},
            {"$inc": {"index": 1, "distributed": tokens_for_user}},
        )
        logger.info("Allocated %.4f tokens (index %s)", tokens_for_user, idx + 1)
        return tokens_for_user

    # ---------------- helper methods (unchanged) ----------------
    async def _generate_unique_code(self) -> str:
        while True:
            code = uuid.uuid4().hex[:8].upper()
            if not await self.users.find_one({"referral_code": code}, {"_id": 1}):
                return code
    #----------------------------------------------------------------------------------------------
    async def _next_member_no(self) -> int:
        doc = await self.counters.find_one_and_update(
            {"_id": "member_no"},
            {"$inc": {"seq": 1}},
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        return int(doc["seq"])

    #----------------------------------------------------------------------------------------------
    async def _distribute_commission(self, *, new_user_id: int, ancestors: List[int]):
        # ۱) محاسبه میزان کل پورسانت (۱۰٪ از حق عضویت ۵۰ دلار)
        commission_pool = self.JOIN_FEE_USD * self.COMMISSION_RATE

        # ۲) اگر کسی کاربر جدید را دعوت کرده (لیست ancestors غیرخالی است)…
        if ancestors:
            # سهم هر نفر = پورسانت کلی تقسیم بر تعداد دعوت‌کننده‌ها
            share = commission_pool / len(ancestors)
            #  ثبت افزایش پورسانت دلاری آنها در کالکشن users
            for uid in ancestors:
                await self.users.update_one(
                    {"user_id": uid},
                    {"$inc": {"commission_usd": share}}
                )
        else:
            # اگر دعوت‌کننده‌‌ای نیست، لاگ می‌زند و پورسانت پرداخت نمی‌شود
            logger.info("User has no inviter; پورسانت تقسیم نشد.")

        # ۳) ثبت پرداخت ۹۰٪ باقیمانده (حق عضویت – پورسانت) به کیف پول استخر
        await self.payments.insert_one({
            "from_user": new_user_id,
            "amount_usd": self.JOIN_FEE_USD - commission_pool,
            "to": self.pool_wallet,
            "type": "join_fee_pool",
            "timestamp": datetime.utcnow(),
        })

    # ------------------------------------------------------------------
    async def ensure_profile(
        self, chat_id: int, first_name: str, inviter_code: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        لایهٔ سازگاری با ProfileHandler – صرفاً ensure_user را فراخوانی می‌کند.
        """
        return await self.ensure_user(chat_id, first_name, inviter_code)




    # # ------------------------------------------------------------------
    # async def get_profile(self, user_id: int) -> Dict[str, Any]:
    #     """
    #     برمی‌گرداند:
    #      - referral_code
    #      - member_no
    #      - tokens
    #      - commission_usd
    #      - total downline count
    #     """
    #     # سند کاربر
    #     user = await self.users.find_one(
    #         {"user_id": user_id},
    #         {"_id": 0, "referral_code": 1, "member_no": 1, "tokens": 1, "commission_usd": 1}
    #     )
    #     if not user:
    #         return {}

    #     # تعداد زیرمجموعه‌ها (بدون صفحه‌بندی)
    #     total = await self.users.count_documents({"inviter_id": user_id})
    #     # مقادیر برگشتی
    #     return {
    #         **user,
    #         "total": total
    #     }

    # # ------------------------------------------------------------------
    # async def get_downline_paginated(
    #     self,
    #     user_id: int,
    #     page: int = 1,
    #     page_size: int = 30
    # ) -> Dict[str, Any]:
    #     """
    #     لیست زیرمجموعه‌ها با صفحه‌بندی:
    #      - members: لیست دیکشنری {'first_name', 'referral_code'}
    #      - total: تعداد کل زیرمجموعه‌ها
    #     """
    #     skip = (page - 1) * page_size
    #     cursor = self.users.find(
    #         {"inviter_id": user_id},
    #         {"_id": 0, "first_name": 1, "referral_code": 1}
    #     ).skip(skip).limit(page_size)
    #     members = await cursor.to_list(length=page_size)
    #     total = await self.users.count_documents({"inviter_id": user_id})
    #     return {"members": members, "total": total}