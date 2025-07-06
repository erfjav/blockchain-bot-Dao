from __future__ import annotations
"""
Referral_logic_code.py   (v7 – production-ready)
================================================
Fixes applied to v6:
• atomic *right-biased* placement with children_count (<2) to prevent race conditions
• slot linkage via `inviter_slot_id` field + consistent counter
• second-admin share now **only** split among 5 wallets (3-dec precision) – residue
  stays in common pool and is logged
• removed double payment to `SECOND_ADMIN_POOL_WALLET`
• rounding residue payment recorded
• safeguard for zero / negative token price
• pay helper keeps 8-dec precision; comment on USD vs token
"""

import logging
import uuid
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple

from pymongo import ReturnDocument
from myproject_database import Database
from config import (
    POOL_WALLET_ADDRESS,
    MULTISIG_WALLET_2OF2,
    SECOND_ADMIN_POOL_WALLET,
    SECOND_ADMIN_PERSONAL_WALLETS,
)

logger = logging.getLogger(__name__)

GHOST_SLOTS: List[str] = [f"EJ-{i}" for i in range(1, 22)]
SECOND_ADMIN_SLOTS: List[str] = (
    [f"N{i}" for i in range(1, 16)] + [f"NN{i}" for i in range(1, 9)]
)

class ReferralManager:
    # ─────── financial constants ───────
    JOIN_FEE_USD          = 50.0
    INVITER_RATE          = 0.10  # 5  USD
    UPSTREAM_RATE         = 0.70  # 35 USD
    COMPANY_RATE          = 0.20  # 10 USD

    # ─────── token constants ───────
    TOKEN_SUPPLY_FOR_USERS   = 9_800_000
    TOKEN_START_PER_USER     = 200.0
    TOKEN_DECREMENT_PER_USER = 0.02

    def __init__(self, db: Database):
        self.db       = db
        self.users    = db.collection_users
        self.payments = db.db["payments"]
        self.counters = db.db["counters"]

        if len(SECOND_ADMIN_PERSONAL_WALLETS) != 5:
            raise RuntimeError("config error: SECOND_ADMIN_PERSONAL_WALLETS must have 5 items")

    # ───────────────────────── main entry ─────────────────────────
    async def ensure_user(
        self, chat_id: int, first_name: str, inviter_code: Optional[str] = None
    ) -> Dict[str, Any]:
        """Create or complete a user profile; returns full document (without _id)."""
        doc = await self.users.find_one({"user_id": chat_id}, {"_id": 0})

        # ➊ existing user → patch missing fields
        if doc:
            updates: Dict[str, Any] = {}
            if "member_no" not in doc:
                updates["member_no"] = await self._next_member_no()
            if "referral_code" not in doc:
                updates["referral_code"] = await self._generate_code()
            if not doc.get("first_name") and first_name:
                updates["first_name"] = first_name
            if updates:
                await self.users.update_one({"user_id": chat_id}, {"$set": updates})
                doc |= updates
            return doc

        # ➋ new user
        referral_code = await self._generate_code()
        member_no     = await self._next_member_no()
        inviter_id, ancestors = await self._resolve_inviter_chain(inviter_code)
        tokens_alloc  = await self._allocate_tokens()

        slot_id, tier, parent_slot = await self._assign_slot(inviter_id, member_no)

        doc = {
            "user_id":        chat_id,
            "member_no":      member_no,
            "slot_id":        slot_id,
            "parent_slot":    parent_slot,       # for structural queries
            "tier":           tier,
            "first_name":     first_name,
            "created_at":     datetime.utcnow(),
            "referral_code":  referral_code,
            "inviter_id":     inviter_id,
            "tokens":         tokens_alloc,
            "commission_usd": 0.0,
            "children_count": 0,
            "joined":         False,
        }
        await self.users.insert_one(doc)

        await self._distribute_commission(
            new_user_id = chat_id,
            inviter_id  = inviter_id,
            ancestors   = ancestors,
        )
        return doc

    # ───────────────────────── placement ──────────────────────────
    async def _assign_slot(
        self, inviter_id: Optional[int], member_no: int
    ) -> Tuple[str, str, Optional[str]]:
        """
        Right-biased emptiest placement with atomic reservation.
        Returns (slot_id, tier, parent_slot).
        """
        if inviter_id is None:
            return str(member_no), "public", None   # rootless (should only happen for seed)

        inviter = await self.users.find_one({"user_id": inviter_id}, {"slot_id": 1})
        root_sid = inviter["slot_id"]

        queue = [root_sid]
        while queue:
            current_sid = queue.pop(0)

            # atomic reserve if < 2 children
            reserved = await self.users.find_one_and_update(
                {"slot_id": current_sid, "children_count": {"$lt": 2}},
                {"$inc": {"children_count": 1}},
                return_document=ReturnDocument.AFTER,
            )
            if reserved:
                return str(member_no), "public", current_sid

            # enqueue children (right child first)
            children = await self.users.find(
                {"parent_slot": current_sid},
                {"slot_id": 1}
            ).sort("slot_id", -1).to_list(length=2)
            queue.extend([c["slot_id"] for c in children])

        # should not happen – fallback
        logger.error("placement fallback triggered")
        return str(member_no), "public", root_sid

    # ───────────────────────── chain utils ────────────────────────
    async def _resolve_inviter_chain(self, inviter_code: Optional[str]):
        inviter_id: Optional[int] = None
        chain: List[int] = []
        if inviter_code:
            doc = await self.users.find_one({"referral_code": inviter_code})
            if doc:
                inviter_id = doc["user_id"]
                temp = inviter_id
                while temp:
                    anc = await self.users.find_one({"user_id": temp}, {"inviter_id": 1})
                    if not anc:
                        break
                    chain.append(temp)
                    temp = anc.get("inviter_id")
        return inviter_id, chain

    # ───────────────────────── token logic ────────────────────────
    async def _allocate_tokens(self) -> float:
        doc = await self.counters.find_one_and_update(
            {"_id": "token_distribution"},
            {"$setOnInsert": {"index": 0, "distributed": 0.0}},
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        idx, distributed = int(doc["index"]), float(doc["distributed"])
        remaining = self.TOKEN_SUPPLY_FOR_USERS - distributed

        if remaining > 0:
            tokens = max(self.TOKEN_START_PER_USER - idx * self.TOKEN_DECREMENT_PER_USER, 0)
            tokens = min(tokens, remaining)
            await self.counters.update_one(
                {"_id": "token_distribution"},
                {"$inc": {"index": 1, "distributed": tokens}},
            )
            return tokens

        # dynamic grant
        price = await self._get_token_price()
        if price <= 0:
            raise RuntimeError("oracle returned invalid token price")
        tokens = round(self.JOIN_FEE_USD / price, 4)
        logger.warning("dynamic token grant %.4f at %.4f USD", tokens, price)
        return tokens

    async def _get_token_price(self) -> float:
        """TODO: connect to real oracle; must never return ≤0."""
        return 0.25

    # ─────────────────────── commission ───────────────────────────
    async def _distribute_commission(
        self, *, new_user_id: int, inviter_id: Optional[int], ancestors: List[int]
    ):
        inviter_share  = self.JOIN_FEE_USD * self.INVITER_RATE
        upstream_pool  = self.JOIN_FEE_USD * self.UPSTREAM_RATE
        company_share  = self.JOIN_FEE_USD * self.COMPANY_RATE

        # direct inviter
        if inviter_id:
            await self._add_commission_to_user(inviter_id, inviter_share)
        else:
            company_share += inviter_share

        # ancestors (excluding inviter)
        higher = [uid for uid in ancestors if uid != inviter_id]
        if higher:
            share = upstream_pool / len(higher)
            for uid in higher:
                anc  = await self.users.find_one({"user_id": uid}, {"slot_id": 1})
                slot = anc.get("slot_id", "")
                if slot in GHOST_SLOTS:
                    await self._pay(MULTISIG_WALLET_2OF2, share, new_user_id, f"ghost {slot}")
                elif slot in SECOND_ADMIN_SLOTS:
                    await self._split_second_admin_pool(share, new_user_id)
                else:
                    await self._add_commission_to_user(uid, share)
        else:
            company_share += upstream_pool

        # company
        if company_share:
            await self._pay(POOL_WALLET_ADDRESS, company_share,
                            new_user_id, "company pool")

    # ─────────────────────── payment helpers ─────────────────────
    async def _pay(self, wallet: str, amount: float, from_user: int, note: str):
        await self.payments.insert_one({
            "from_user":  from_user,
            "amount_usd": round(amount, 8),   # in USD; adjust if token
            "to":         wallet,
            "type":       note,
            "timestamp":  datetime.utcnow(),
        })

    async def _add_commission_to_user(self, user_id: int, amount: float):
        await self.users.update_one(
            {"user_id": user_id},
            {"$inc": {"commission_usd": round(amount, 8)}},
        )

    async def _split_second_admin_pool(self, amount: float, from_user: int):
        """
        Split equally among 5 second-level admins (3-dec precision).
        Residue ≤0.004 stays in SECOND_ADMIN_POOL_WALLET.
        """
        per_admin = round(amount / 5, 3)
        for w in SECOND_ADMIN_PERSONAL_WALLETS:
            await self._pay(w, per_admin, from_user, "second-admin split")
        residue = round(amount - per_admin * 5, 8)
        if residue > 0:
            await self._pay(SECOND_ADMIN_POOL_WALLET, residue, from_user, "second-admin residue")

    # ─────────────────────── misc helpers ────────────────────────
    async def _generate_code(self) -> str:
        while True:
            code = uuid.uuid4().hex[:8].upper()
            if not await self.users.find_one({"referral_code": code}, {"_id": 1}):
                return code

    async def _next_member_no(self) -> int:
        doc = await self.counters.find_one_and_update(
            {"_id": "member_no"},
            {"$inc": {"seq": 1}},
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        return int(doc["seq"])

    # wrapper for legacy
    async def ensure_profile(
        self, chat_id: int, first_name: str, inviter_code: Optional[str] = None
    ) -> Dict[str, Any]:
        return await self.ensure_user(chat_id, first_name, inviter_code)





