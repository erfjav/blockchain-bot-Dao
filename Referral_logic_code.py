from __future__ import annotations
"""
referral_logic_tron.py   (v4 – 2025‑07‑07)
=====================================================================
✅ **Aligned with the latest business rules**

Key updates compared to v3 (hardening layer):
1. **All wallets migrated to TronLink / Trust Wallet only** – removed any left‑over
   multi‑sig or Ethereum references.
2. **10‑day automatic split** of the $50 join‑fee accumulator wallet
   (70 / 20 / 10) now honours the exact percentages after fees.
3. **Second‑admin pool logic rewritten**
   • 19 % → each of the five second‑admins (Trust Wallet)
   • 5 % buffer kept in the pool, used first for network fees; if the buffer is
     still insufficient, each admin share is reduced proportionally (never
     negative).
4. **First‑admin pool payout** – equal split every 10 days, with dynamic fee
   deduction from the pool residue.
5. **Dynamic fee estimation** using `CryptoHandler.estimate_fee()`; falls back to
   a safe constant if the provider does not support it.
6. **Atomic slot assignment using BFS** to honour placement rules:
   • Users **without inviter** are placed at the *lowest‑rightmost* vacant slot
     (breadth‑first search across the whole tree).
   • Users **with inviter** are placed in the emptiest branch under their
     inviter (also BFS starting from the inviter’s slot).
7. **Eligibility refresh tightened** – evaluated on every child deletion as
   well (public helper `mark_child_removed`).
8. **Decimal‑safe accounting** – every USD value travels as `Decimal` → micro‑
   USDT (int) only at the hand‑off to `CryptoHandler.transfer()`.
9. **Retry & pending queues** unchanged (still 3 attempts).

This single file is self‑contained except for:
    • `config.py`      – runtime constants (wallet addresses, admin IDs, …)
    • `core.crypto_handler` – blockchain I/O (unchanged interface)
    • `myproject_database.Database` – thin async wrapper around `motor` (Mongo)
"""

import asyncio
import logging
import uuid
from collections import deque
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_DOWN
from typing import Optional, List, Dict, Any

from pymongo import ReturnDocument, errors as mongo_errors

from myproject_database import Database
from config import (
    
    # Blockchain endpoints
    TRON_PROVIDERS,

    # Core corporate wallets (all TronLink)
    

    WALLET_JOIN_POOL,   # 🏛️ WALLET_JOIN_POOL
                        # Central entry wallet.
                        # All $50 join-fee payments from users go here first.
                        # Funds are then redistributed every 10 days into three operational wallets.     
    
    WALLET_SPLIT_70,    # 📊 WALLET_SPLIT_70
                        # Upstream rewards pool.
                        # Receives 70% of the join-pool.
                        # Used to pay eligible upstream users (referral ancestors).

    WALLET_SPLIT_20,    # 🏢 WALLET_SPLIT_20
                        # Company main wallet.
                        # Receives 20% of the join-pool.
                        # Used for core company operations and costs.

    WALLET_SPLIT_10,            # 🧾 WALLET_SPLIT_10
                                # Company secondary wallet.
                                # Receives 10% of the join-pool.
                                # Covers additional costs or reserves.

    # Admin pools (TronLink)
    WALLET_FIRST_ADMIN_POOL,    # 🪙 WALLET_FIRST_ADMIN_POOL
                                # Pool for first-level admin commissions.
                                # Accumulates funds allocated to MAIN_LEADER_IDS.
                                # Every 10 days, split equally among FIRST_ADMIN_PERSONAL_WALLETS.
    
    WALLET_SECOND_ADMIN_POOL,   # 🪪 WALLET_SECOND_ADMIN_POOL
                                # Pool for second-level admin commissions.
                                # Receives upstream commission shares for SECOND_ADMIN_USER_IDS.
                                # Every 10 days, 95% is split among 5 personal wallets;
                                # 5% is kept as buffer for covering transaction fees.

    # Personal wallets (Trust Wallet)
    FIRST_ADMIN_PERSONAL_WALLETS,   # 👤 FIRST_ADMIN_PERSONAL_WALLETS
                                    # List of personal wallets for top-tier admins (Trust Wallet).
                                    # Each receives equal share from WALLET_FIRST_ADMIN_POOL.      
    
    SECOND_ADMIN_PERSONAL_WALLETS,  # 👥 SECOND_ADMIN_PERSONAL_WALLETS
                                    # Exactly 5 personal wallets for second-tier admins (Trust Wallet).
                                    # Each receives equal share (after buffer deduction) from WALLET_SECOND_ADMIN_POOL.

    # Staff / role IDs
    MAIN_LEADER_IDS,        # “first‑admins” – always eligible
    SECOND_ADMIN_USER_IDS,  # “second‑admins” – must still bring 2
)
from core.crypto_handler import CryptoHandler

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Business constants
# ----------------------------------------------------------------------------
JOIN_FEE_USD        = Decimal("50")
INVITER_DIRECT_USD  = Decimal("5")              # Paid immediately to inviter

# From the remaining $45
COMPANY_MAIN_RATE   = Decimal("0.20")            # 9 USDT
COMPANY_ALT_RATE    = Decimal("0.10")            # 4.5 USDT
UPSTREAM_RATE       = Decimal("0.70")            # 31.5 USDT

MICRO = Decimal("1000000")  # 1e6 (USDT has 6 decimals)

# Dynamic fee fallback (≈ 0.6 USDT on Tron per tx as of 07‑2025)
FEE_FALLBACK_USD    = Decimal("0.6")

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ----------------------------------------------------------------------------

def _round_down(val: Decimal, precision: str = "0.000001") -> Decimal:
    return val.quantize(Decimal(precision), rounding=ROUND_DOWN)


def _dec_to_micro(val: Decimal) -> int:
    """Convert a Decimal[USDT] → integer micro‑USDT (6 decimals)."""
    return int((val * MICRO).to_integral_value(rounding=ROUND_DOWN))

# ─────────────────────────────────────────────────────────────────────────────
# Referral Manager – async / database‑backed
# ----------------------------------------------------------------------------

class ReferralManager:
    """All monetary operations are funnelled through here."""

    # ────────────────────────────────────────────────────────────
    # Construction / bootstrap
    # -----------------------------------------------------------
    def __init__(self, *, db: Database, crypto:CryptoHandler ):
        
        self.db = db
        self.logger = logging.getLogger(__name__)
        self.crypto_handler = crypto

        self.col_users     = db.collection_users
        self.col_slots     = db.collection_slots
        self.col_counters  = db.collection_counters
        self.col_payments  = db.collection_payments
        self.col_schedules = db.collection_schedules

    # ────────────────────────────────────────────────────────────
    # 🔔 Public API (always ticks scheduler)
    # -----------------------------------------------------------
    async def ensure_user(self, *, user_id: int, first_name: str, inviter_id: Optional[int] = None):
        await self._tick_schedules()
        return await self._ensure_user_impl(user_id=user_id, first_name=first_name, inviter_id=inviter_id)

    async def mark_child_removed(self, *, parent_id: int, child_id: int):
        """Call when a child is removed (e.g. refund / ban) to keep eligibility sane."""
        await self.col_users.update_one({"user_id": parent_id}, {"$pull": {"direct_children": child_id}})
        await self._refresh_eligibility(parent_id)

    async def process_scheduled_payouts(self):
        """Can be triggered by an external cron – not required but keeps logs tidy."""
        await self._tick_schedules(force=True)

    # ────────────────────────────────────────────────────────────
    # Scheduler tick (idempotent)
    # -----------------------------------------------------------
    async def _tick_schedules(self, *, force: bool = False):
        now = datetime.utcnow()

        # 10‑day schedule (corporate & admin pools)
        doc10 = await self.col_schedules.find_one({"_id": "10d"})
        if force or not doc10 or (now - doc10["ts"]) >= timedelta(days=10):
            await self._payout_every_10_days()
            await self.col_schedules.update_one({"_id": "10d"}, {"$set": {"ts": now}}, upsert=True)

        # 30‑day schedule (normal members)
        doc30 = await self.col_schedules.find_one({"_id": "30d"})
        if force or not doc30 or (now - doc30["ts"]) >= timedelta(days=30):
            await self._payout_every_30_days()
            await self.col_schedules.update_one({"_id": "30d"}, {"$set": {"ts": now}}, upsert=True)

    # ────────────────────────────────────────────────────────────
    # User onboarding
    # -----------------------------------------------------------
    
    async def _ensure_user_impl(self, *, user_id: int, first_name: str, inviter_id: Optional[int]):
        user = await self.col_users.find_one({"user_id": user_id})

        if user:
            # ۱) اگر اسم کاربر نداشت، پرش کن
            if first_name and not user.get("first_name"):
                await self.col_users.update_one(
                    {"user_id": user_id},
                    {"$set": {"first_name": first_name}}
                )

            # ۲) اگر referral_code نداشت، تولید و ذخیره کن
            if "referral_code" not in user:
                new_code = await self._gen_referral_code()
                user["referral_code"] = new_code
                await self.col_users.update_one(
                    {"user_id": user_id},
                    {"$set": {"referral_code": new_code}}
                )

            # ۳) اگر member_no نداشت، مثل قبل
            if "member_no" not in user:
                new_no = await self._next_member_no()
                user["member_no"] = new_no
                await self.col_users.update_one(
                    {"user_id": user_id},
                    {"$setOnInsert": {"member_no": new_no}},
                    upsert=True
                )

            return user

        #   اگر user وجود نداشت، سند جدید را بساز
        referral_code = await self._gen_referral_code()
        member_no     = await self._next_member_no()
        slot_id       = await self._assign_slot(inviter_id, member_no)
        ancestors     = await self._resolve_chain(inviter_id) if inviter_id else []

        new_doc = {
            "user_id":        user_id,
            "first_name":     first_name,
            "referral_code":  referral_code,
            "member_no":      member_no,
            "slot_id":        slot_id,
            "inviter_id":     inviter_id,
            "ancestors":      ancestors,
            "direct_children": [],
            "direct_dates":   [],
            "eligible":       False,
            "joined":         False,             # ← اضافه شد
            "tokens":         0,                 # ← اضافه شد
            "balance_usd":    0.0,
            "commission_usd": 0.0,      # ← اضافه شد
            "created_at":     datetime.utcnow(),
        }
        await self.col_users.insert_one(new_doc)

        # … ادامه‌ی کدِ آپدیت inviter و پخش کمیسیون و توکن
        return new_doc

    # ────────────────────────────────────────────────────────────
    # Slot placement (BFS – atomic insert into `slots`)
    # -----------------------------------------------------------
    async def _assign_slot(self, inviter_id: Optional[int], member_no: int) -> str:
        """Fulfils placement rules with a breadth‑first search + atomic lock."""

        # Determine the search root (inviter’s slot or global ROOT)
        if inviter_id:
            base_slot = (await self.col_users.find_one({"user_id": inviter_id}, {"slot_id": 1})) or {}
            root_slot = base_slot.get("slot_id", "ROOT")
        else:
            root_slot = "ROOT"

        queue: deque[str] = deque([root_slot])
        visited: set[str] = set()

        while queue:
            parent = queue.popleft()
            if parent in visited:
                continue
            visited.add(parent)

            # Count existing children (fast – uses index on slot_id)
            child_count = await self.col_users.count_documents({"slot_id": {"$regex": f"^{parent}-c"}})
            if child_count < 2:
                # Attempt to lock this position atomically
                for attempt in range(5):
                    candidate = f"{parent}-c{uuid.uuid4().hex[:4]}" if parent != "ROOT" else f"N{member_no}-root"
                    try:
                        await self.col_slots.insert_one({"slot_id": candidate})
                        return candidate
                    except mongo_errors.DuplicateKeyError:
                        continue  # extremely low‑probability clash – retry
            # Push children into BFS queue (rightmost preference ⇒ appendleft)
            async for s in self.col_slots.find({"slot_id": {"$regex": f"^{parent}-c"}}, {"slot_id": 1}).sort("slot_id", -1):
                queue.appendleft(s["slot_id"])

        # Should never reach here
        raise RuntimeError("No vacant slot found – tree seems full or DB corrupted.")

    # ────────────────────────────────────────────────────────────
    # Eligibility calculation
    # -----------------------------------------------------------
    async def _refresh_eligibility(self, uid: int):
        doc = await self.col_users.find_one({"user_id": uid}, {"direct_children": 1})
        eligible_now = len(doc.get("direct_children", [])) >= 2 and uid not in MAIN_LEADER_IDS
        await self.col_users.update_one({"user_id": uid}, {"$set": {"eligible": eligible_now}})

    async def _is_eligible(self, uid: int) -> bool:
        d = await self.col_users.find_one({"user_id": uid}, {"eligible": 1})
        return bool(d and d.get("eligible"))

    # ────────────────────────────────────────────────────────────
    # Commission distribution (on each $50 join)
    # -----------------------------------------------------------
    async def _distribute_commission(self, user_doc: Dict[str, Any]):
        inviter_id = user_doc.get("inviter_id")

        # 1️⃣ Direct inviter bonus – paid immediately
        if inviter_id:
            await self._credit_user(inviter_id, INVITER_DIRECT_USD, "direct‑5usd")

        # Remaining $45 dollars to split
        remaining = JOIN_FEE_USD - INVITER_DIRECT_USD
        company_main = _round_down(COMPANY_MAIN_RATE * remaining)  # 9 USDT
        company_alt  = _round_down(COMPANY_ALT_RATE * remaining)   # 4.5 USDT
        upstream_pool = _round_down(remaining - company_main - company_alt)  # 31.5 USDT

        await self._transfer_wallet(WALLET_SPLIT_20, company_main, "company‑20")
        await self._transfer_wallet(WALLET_SPLIT_10, company_alt,  "company‑10")

        # 2️⃣ 70 % upstream split among eligible ancestors (excluding ineligible)
        ancestors = [a for a in user_doc["ancestors"] if await self._is_eligible(a)]
        if ancestors:
            share = _round_down(upstream_pool / len(ancestors))
            for anc in ancestors:
                await self._credit_user(anc, share, "upstream‑share")
        else:
            share = Decimal("0")

        # Any rounding residue is kept in the join pool wallet
        residue = remaining - company_main - company_alt - (share * len(ancestors))
        if residue > 0:
            await self._transfer_wallet(WALLET_JOIN_POOL, residue, "round‑residue")

    # Credit helper – routes to the correct corporate/admin pool or user balance
    async def _credit_user(self, uid: int, amount: Decimal, note: str):
        if uid in MAIN_LEADER_IDS:
            await self._transfer_wallet(WALLET_FIRST_ADMIN_POOL, amount, f"1stadmin‑{note}", from_uid=uid)
        elif uid in SECOND_ADMIN_USER_IDS:
            await self._transfer_wallet(WALLET_SECOND_ADMIN_POOL, amount, f"2ndadmin‑{note}", from_uid=uid)
        else:
            await self.col_users.update_one({"user_id": uid}, {"$inc": {"balance_usd": amount}})
            await self.col_payments.insert_one({
                "user_id":   uid,
                "amount_usd": str(amount),
                "status":    "accrued",
                "note":      note,
                "timestamp": datetime.utcnow(),
            })

    # ────────────────────────────────────────────────────────────
    # Safe blockchain transfer (3 retries)
    # -----------------------------------------------------------
    async def _transfer_wallet(self, wallet: str, amount: Decimal, note: str, *, from_uid: Optional[int] = None):
        micros = _dec_to_micro(amount)
        fee_estimate = await self._estimate_fee(wallet, micros)
        logger.debug("Transfer %s → %s (%.6f USDT) fee≈%.4f", note, wallet, amount, fee_estimate)

        for attempt in range(3):
            try:
                tx_hash = await self.crypto_handler.transfer("tron", wallet, micros, token_symbol="USDT", decimals=6)
                await self.col_payments.insert_one({
                    "user_id":   from_uid,
                    "wallet":    wallet,
                    "amount_usd": str(amount),
                    "tx_hash":   tx_hash,
                    "status":    "success",
                    "note":      note,
                    "timestamp": datetime.utcnow(),
                })
                return
            except Exception as exc:
                logger.warning("Transfer attempt %d failed (%s): %s", attempt + 1, note, exc)
                await asyncio.sleep(1.5)

        # after 3 failed attempts – mark as pending
        await self.col_payments.insert_one({
            "user_id":   from_uid,
            "wallet":    wallet,
            "amount_usd": str(amount),
            "tx_hash":   None,
            "status":    "pending_retry",
            "note":      note,
            "timestamp": datetime.utcnow(),
        })

    async def _estimate_fee(self, wallet: str, micros: int) -> Decimal:
        try:
            return Decimal(str(await self.crypto_handler.estimate_fee("tron", wallet, micros, token_symbol="USDT", decimals=6)))
        except Exception:
            return FEE_FALLBACK_USD

    # ────────────────────────────────────────────────────────────
    # 10‑day corporate / admin payouts
    # -----------------------------------------------------------
    async def _payout_every_10_days(self):
        await self._split_join_pool()
        await self._split_second_admin_pool()
        await self._split_first_admin_pool()
        
    ###------------------------------------------------------------------------------------

    async def _split_join_pool(self):
        bal = Decimal(str(await self.crypto_handler.get_wallet_balance("tron", WALLET_JOIN_POOL, "USDT", 6)))
        if bal == 0:
            return
        seventy = _round_down(bal * Decimal("0.70"))
        twenty  = _round_down(bal * Decimal("0.20"))
        ten     = bal - seventy - twenty
        await self._transfer_wallet(WALLET_SPLIT_70, seventy, "join‑70")
        await self._transfer_wallet(WALLET_SPLIT_20, twenty,  "join‑20")
        await self._transfer_wallet(WALLET_SPLIT_10, ten,    "join‑10")
        
    ###------------------------------------------------------------------------------------
    
    async def _split_second_admin_pool(self, period_start=None, period_end=None):
        """
        پرداخت اتوماتیک به مدیران رده دوم و ثبت گزارش هر تراکنش
        """

        try:
            bal = Decimal(str(await self.crypto_handler.get_wallet_balance(
                "tron", WALLET_SECOND_ADMIN_POOL, "USDT", 6
            )))
            if bal == 0:
                return

            # محاسبه سهم هر نفر با احتساب buffer
            buffer_target = _round_down(bal * Decimal("0.05"))
            distributable = bal - buffer_target
            share = _round_down(distributable / Decimal(len(SECOND_ADMIN_PERSONAL_WALLETS)))

            total_estimated_fees = Decimal("0")
            for w in SECOND_ADMIN_PERSONAL_WALLETS:
                total_estimated_fees += await self._estimate_fee(w, _dec_to_micro(share))
            if total_estimated_fees > buffer_target:
                deficit = total_estimated_fees - buffer_target
                reduction_each = _round_down(deficit / Decimal(len(SECOND_ADMIN_PERSONAL_WALLETS)))
                share -= reduction_each
                if share <= 0:
                    self.logger.warning("Second-admin share turned non-positive after fee adjustment – postponing payout.")
                    return

            # zip با SECOND_ADMIN_USER_IDS
            for idx, (w, user_id) in enumerate(zip(SECOND_ADMIN_PERSONAL_WALLETS, SECOND_ADMIN_USER_IDS), 1):
                try:
                    tx_hash = await self._transfer_wallet(w, share, f"2ndadmin‑{idx}")
                    payout_period = (
                        f"{period_start} ~ {period_end}"
                        if period_start and period_end
                        else datetime.utcnow().strftime("%Y-%m-%d")
                    )
                    await self.db.store_leader_payment(
                        user_id=user_id,
                        amount=float(share),
                        token="USDT",
                        wallet=w,
                        tx_hash=tx_hash,
                        pool_type="SECOND_ADMIN_POOL",
                        payout_period=payout_period,
                    )
                except Exception as e:
                    self.logger.error(
                        f"Error in second admin payout for user {user_id} (wallet {w}): {e}"
                    )
                    continue
        except Exception as e:
            self.logger.error(f"Error in _split_second_admin_pool: {e}")
            
    ###------------------------------------------------------------------------------------
    async def _split_first_admin_pool(self, period_start=None, period_end=None):
        """
        پرداخت اتوماتیک به مدیران رده اول و ثبت گزارش هر تراکنش
        """
        from datetime import datetime

        try:
            bal = Decimal(str(await self.crypto_handler.get_wallet_balance(
                "tron", WALLET_FIRST_ADMIN_POOL, "USDT", 6
            )))
            if bal == 0:
                return

            share = _round_down(bal / Decimal(len(FIRST_ADMIN_PERSONAL_WALLETS)))

            # ترتیب zip باید با MAIN_LEADER_IDS یکی باشد
            for idx, (w, user_id) in enumerate(zip(FIRST_ADMIN_PERSONAL_WALLETS, MAIN_LEADER_IDS), 1):
                try:
                    tx_hash = await self._transfer_wallet(w, share, f"1stadmin‑{idx}")
                    payout_period = (
                        f"{period_start} ~ {period_end}"
                        if period_start and period_end
                        else datetime.utcnow().strftime("%Y-%m-%d")
                    )
                    await self.db.store_leader_payment(
                        user_id=user_id,
                        amount=float(share),
                        token="USDT",
                        wallet=w,
                        tx_hash=tx_hash,
                        pool_type="FIRST_ADMIN_POOL",
                        payout_period=payout_period,
                    )
                except Exception as e:
                    self.logger.error(
                        f"Error in first admin payout for user {user_id} (wallet {w}): {e}"
                    )
                    continue
        except Exception as e:
            self.logger.error(f"Error in _split_first_admin_pool: {e}")

    # ────────────────────────────────────────────────────────────
    # 30‑day member payouts
    # -----------------------------------------------------------
    async def days_until_next_monthly_payout(self, user_id: int, interval_days: int = 30) -> int:
        """
        محاسبه می‌کند چند روز تا زمان پاداش ماهانه (یا برداشت مجاز) باقی مانده:
        - ملاک اول: تاریخ دومین زیرمجموعه‌ی کاربر
        - ملاک دوم: تاریخ آخرین برداشت (در صورت وجود)
        اگر هیچ‌کدام نبود یا بیش از interval_days گذشته، عدد 0 برمی‌گرداند.
        """
        from datetime import datetime, timedelta

        # ۱) تاریخ دومین زیرمجموعه
        second_date = await self._second_child_date(user_id)

        # ۲) تاریخ آخرین درخواست برداشت
        last_req = await self.db.get_last_withdraw_request(user_id)
        last_withdraw_date = last_req.get("created_at") if last_req else None

        # انتخاب قدیمی‌ترین تاریخِ مؤثر
        effective_date = None
        if second_date and last_withdraw_date:
            effective_date = max(second_date, last_withdraw_date)
        else:
            effective_date = second_date or last_withdraw_date

        if not effective_date:
            # اگر هیچ‌کدام وجود ندارد، کاربر هنوز واجد دریافت اولین برداشت نیست → فاصله‌ی کامل
            return interval_days

        delta = datetime.utcnow() - effective_date
        if delta < timedelta(days=interval_days):
            return interval_days - delta.days
        return 0
    
    async def _payout_every_30_days(self):
        now = datetime.utcnow()
        async for user in self.col_users.find({"balance_usd": {"$gt": 0}}):
            uid = user["user_id"]
            if uid in MAIN_LEADER_IDS + SECOND_ADMIN_USER_IDS:
                continue  # admins handled separately

            # ← استفاده از helper
            days_left = await self.days_until_next_monthly_payout(uid, 30)
            if days_left:
                continue  # هنوز ماه کامل نشده

            amt = Decimal(user["balance_usd"])
            wallet = user.get("tron_wallet")
            if not wallet:
                continue

            await self._transfer_wallet(wallet, amt, "monthly-member", from_uid=uid)
            await self.col_users.update_one({"user_id": uid}, {"$set": {"balance_usd": Decimal("0")}})
            await self._refresh_eligibility(uid)    
    
    async def _second_child_date(self, uid: int) -> Optional[datetime]:
        doc = await self.col_users.find_one({"user_id": uid}, {"direct_dates": 1})
        dates = doc.get("direct_dates", []) if doc else []
        return dates[1] if len(dates) >= 2 else None

    # ────────────────────────────────────────────────────────────
    # Token airdrop (unchanged)
    # -----------------------------------------------------------
    async def _allocate_tokens(self, new_user: Dict[str, Any]):
        ctr = await self.col_counters.find_one_and_update(
            {"_id": "token"}, {"$inc": {"idx": 1}}, upsert=True, return_document=ReturnDocument.AFTER
        )
        idx = ctr.get("idx", 1)
        dist = ctr.get("dist", 0)
        MAX_DISTRIBUTION_SUPPLY = 9_800_000
        INITIAL_AIRDROP_TOKENS  = 200
        DECAY_PER_USER          = Decimal("0.02")

        if dist >= MAX_DISTRIBUTION_SUPPLY:
            return
        tok = max(INITIAL_AIRDROP_TOKENS - (idx - 1) * DECAY_PER_USER, Decimal("1"))
        if dist + tok > MAX_DISTRIBUTION_SUPPLY:
            tok = MAX_DISTRIBUTION_SUPPLY - dist
        await self.col_counters.update_one({"_id": "token"}, {"$inc": {"dist": float(tok)}})
        await self.col_users.update_one({"user_id": new_user["user_id"]}, {"$inc": {"tokens": float(tok)}})

    # ────────────────────────────────────────────────────────────
    # Misc helpers
    # -----------------------------------------------------------
    async def _gen_referral_code(self) -> str:
        while True:
            code = uuid.uuid4().hex[:8].upper()
            if not await self.col_users.find_one({"referral_code": code}, {"_id": 1}):
                return code

    async def _next_member_no(self) -> int:
        doc = await self.col_counters.find_one_and_update(
            {"_id": "member"}, {"$inc": {"seq": 1}}, upsert=True, return_document=ReturnDocument.AFTER
        )
        return doc.get("seq", 1)

    async def _resolve_chain(self, inviter_id: int) -> List[int]:
        chain: List[int] = []
        current = inviter_id
        while current:
            chain.append(current)
            row = await self.col_users.find_one({"user_id": current}, {"inviter_id": 1})
            current = row.get("inviter_id") if row else None
        return chain



####################################################################################################### 
    # async def _split_second_admin_pool(self):
    #     bal = Decimal(str(await self.crypto_handler.get_wallet_balance("tron", WALLET_SECOND_ADMIN_POOL, "USDT", 6)))
    #     if bal == 0:
    #         return

    #     # 95 % (19×5) to admins, 5 % stays as fee buffer
    #     buffer_target = _round_down(bal * Decimal("0.05"))
    #     distributable = bal - buffer_target
    #     share = _round_down(distributable / Decimal(len(SECOND_ADMIN_PERSONAL_WALLETS)))

    #     # Real‑time fee estimate to ensure we don’t overdraw
    #     total_estimated_fees = Decimal("0")
    #     for w in SECOND_ADMIN_PERSONAL_WALLETS:
    #         total_estimated_fees += await self._estimate_fee(w, _dec_to_micro(share))

    #     if total_estimated_fees > buffer_target:
    #         deficit = total_estimated_fees - buffer_target
    #         """Reduce each share equally so that buffer covers fees."""
    #         reduction_each = _round_down(deficit / Decimal(len(SECOND_ADMIN_PERSONAL_WALLETS)))
    #         share -= reduction_each
    #         if share <= 0:
    #             logger.warning("Second‑admin share turned non‑positive after fee adjustment – postponing payout.")
    #             return

    #     # Execute transfers
    #     for idx, w in enumerate(SECOND_ADMIN_PERSONAL_WALLETS, 1):
    #         await self._transfer_wallet(w, share, f"2ndadmin‑{idx}")
    #     # any residue (including buffer) stays in pool for next round

    # async def _split_first_admin_pool(self):
    #     bal = Decimal(str(await self.crypto_handler.get_wallet_balance("tron", WALLET_FIRST_ADMIN_POOL, "USDT", 6)))
    #     if bal == 0:
    #         return
    #     share = _round_down(bal / Decimal(len(FIRST_ADMIN_PERSONAL_WALLETS)))
    #     for idx, w in enumerate(FIRST_ADMIN_PERSONAL_WALLETS, 1):
    #         await self._transfer_wallet(w, share, f"1stadmin‑{idx}")
    #     # residue automatically stays to cover future fees
#####################################################################################################
    # async def _payout_every_30_days(self):
        
    #     now = datetime.utcnow()
    #     async for user in self.col_users.find({"balance_usd": {"$gt": 0}}):
    #         uid = user["user_id"]
    #         if uid in MAIN_LEADER_IDS + SECOND_ADMIN_USER_IDS:
    #             continue  # admins handled separately
            
    #         second_date = await self._second_child_date(uid)
    #         if not second_date or (now - second_date) < timedelta(days=30):
    #             continue  # not yet eligible for payout
            
    #         amt = Decimal(user["balance_usd"])
    #         wallet = user.get("tron_wallet")
            
    #         if not wallet:
    #             continue  # user has no withdrawal wallet on file
            
    #         await self._transfer_wallet(wallet, amt, "monthly‑member", from_uid=uid)
    #         await self.col_users.update_one({"user_id": uid}, {"$set": {"balance_usd": Decimal("0")}})
    #         await self._refresh_eligibility(uid)  # may become ineligible if children were removed


#######################################################################################################

# from __future__ import annotations
# """
# Referral_logic_code.py   (v7 – production-ready)
# ================================================
# Fixes applied to v6:
# • atomic *right-biased* placement with children_count (<2) to prevent race conditions
# • slot linkage via `inviter_slot_id` field + consistent counter
# • second-admin share now **only** split among 5 wallets (3-dec precision) – residue
#   stays in common pool and is logged
# • removed double payment to `SECOND_ADMIN_POOL_WALLET`
# • rounding residue payment recorded
# • safeguard for zero / negative token price
# • pay helper keeps 8-dec precision; comment on USD vs token
# """

# import logging
# import uuid
# from datetime import datetime
# from typing import Optional, List, Dict, Any, Tuple

# from pymongo import ReturnDocument
# from myproject_database import Database
# from core.safe_client import SafeClient
# from core.price_provider import DynamicPriceProvider 

# from config import (
#     POOL_WALLET_ADDRESS,
#     MULTISIG_GHOST_WALLET_2OF2,
#     SECOND_ADMIN_POOL_WALLET,
#     SECOND_ADMIN_PERSONAL_WALLETS,
# )

# logger = logging.getLogger(__name__)

# GHOST_SLOTS: List[str] = [f"EJ-{i}" for i in range(1, 22)]
# SECOND_ADMIN_SLOTS: List[str] = (
#     [f"N{i}" for i in range(1, 16)] + [f"NN{i}" for i in range(1, 9)]
# )

# class ReferralManager:
#     # ─────── financial constants ───────
#     JOIN_FEE_USD          = 50.0
#     INVITER_RATE          = 0.10  # 5  USD
#     UPSTREAM_RATE         = 0.70  # 35 USD
#     COMPANY_RATE          = 0.20  # 10 USD

#     # ─────── token constants ───────
#     TOKEN_SUPPLY_FOR_USERS   = 9_800_000
#     TOKEN_START_PER_USER     = 200.0
#     TOKEN_DECREMENT_PER_USER = 0.02

#     def __init__(self, db: Database, safe_client: SafeClient, price_provider:DynamicPriceProvider):
        
#         self.db       = db
#         self.logger = logging.getLogger(__name__)
#         self.users    = db.collection_users
#         self.payments = db.db["payments"]
#         self.counters = db.db["counters"]
#         self.safe_client = safe_client
#         self.price_provider= price_provider

#         if len(SECOND_ADMIN_PERSONAL_WALLETS) != 5:
#             raise RuntimeError("config error: SECOND_ADMIN_PERSONAL_WALLETS must have 5 items")

#     # ───────────────────────── main entry ─────────────────────────
    # async def ensure_user(
    #     self, chat_id: int, first_name: str, inviter_code: Optional[str] = None
    # ) -> Dict[str, Any]:
    #     """Create or complete a user profile; returns full document (without _id)."""
    #     doc = await self.users.find_one({"user_id": chat_id}, {"_id": 0})

    #     # ➊ existing user → patch missing fields
    #     if doc:
    #         updates: Dict[str, Any] = {}
    #         if "member_no" not in doc:
    #             updates["member_no"] = await self._next_member_no()
    #         if "referral_code" not in doc:
    #             updates["referral_code"] = await self._generate_code()
    #         if not doc.get("first_name") and first_name:
    #             updates["first_name"] = first_name
    #         if updates:
    #             await self.users.update_one({"user_id": chat_id}, {"$set": updates})
    #             doc |= updates
    #         return doc

    #     # ➋ new user
    #     referral_code = await self._generate_code()
    #     member_no     = await self._next_member_no()
    #     inviter_id, ancestors = await self._resolve_inviter_chain(inviter_code)
    #     tokens_alloc  = await self._allocate_tokens()

    #     slot_id, tier, parent_slot = await self._assign_slot(inviter_id, member_no)

    #     doc = {
    #         "user_id":        chat_id,
    #         "member_no":      member_no,
    #         "slot_id":        slot_id,
    #         "parent_slot":    parent_slot,       # for structural queries
    #         "tier":           tier,
    #         "first_name":     first_name,
    #         "created_at":     datetime.utcnow(),
    #         "referral_code":  referral_code,
    #         "inviter_id":     inviter_id,
    #         "tokens":         tokens_alloc,
    #         "commission_usd": 0.0,
    #         "children_count": 0,
    #         "joined":         False,
    #     }
    #     await self.users.insert_one(doc)

    #     await self._distribute_commission(
    #         new_user_id = chat_id,
    #         inviter_id  = inviter_id,
    #         ancestors   = ancestors,
    #     )
    #     return doc

#     # ───────────────────────── placement ──────────────────────────
#     async def _assign_slot(
#         self, inviter_id: Optional[int], member_no: int
#     ) -> Tuple[str, str, Optional[str]]:
#         """
#         Right-biased emptiest placement with atomic reservation.
#         Returns (slot_id, tier, parent_slot).
#         """
#         if inviter_id is None:
#             return str(member_no), "public", None   # rootless (should only happen for seed)

#         inviter = await self.users.find_one({"user_id": inviter_id}, {"slot_id": 1})
#         root_sid = inviter["slot_id"]

#         queue = [root_sid]
#         while queue:
#             current_sid = queue.pop(0)

#             # atomic reserve if < 2 children
#             reserved = await self.users.find_one_and_update(
#                 {"slot_id": current_sid, "children_count": {"$lt": 2}},
#                 {"$inc": {"children_count": 1}},
#                 return_document=ReturnDocument.AFTER,
#             )
#             if reserved:
#                 return str(member_no), "public", current_sid

#             # enqueue children (right child first)
#             children = await self.users.find(
#                 {"parent_slot": current_sid},
#                 {"slot_id": 1}
#             ).sort("slot_id", -1).to_list(length=2)
#             queue.extend([c["slot_id"] for c in children])

#         # should not happen – fallback
#         logger.error("placement fallback triggered")
#         return str(member_no), "public", root_sid

#     # ───────────────────────── chain utils ────────────────────────
#     async def _resolve_inviter_chain(self, inviter_code: Optional[str]):
#         inviter_id: Optional[int] = None
#         chain: List[int] = []
#         if inviter_code:
#             doc = await self.users.find_one({"referral_code": inviter_code})
#             if doc:
#                 inviter_id = doc["user_id"]
#                 temp = inviter_id
#                 while temp:
#                     anc = await self.users.find_one({"user_id": temp}, {"inviter_id": 1})
#                     if not anc:
#                         break
#                     chain.append(temp)
#                     temp = anc.get("inviter_id")
#         return inviter_id, chain

#     # ───────────────────────── token logic ────────────────────────
#     async def _allocate_tokens(self) -> float:
#         doc = await self.counters.find_one_and_update(
#             {"_id": "token_distribution"},
#             {"$setOnInsert": {"index": 0, "distributed": 0.0}},
#             upsert=True,
#             return_document=ReturnDocument.AFTER,
#         )
#         idx, distributed = int(doc["index"]), float(doc["distributed"])
#         remaining = self.TOKEN_SUPPLY_FOR_USERS - distributed

#         if remaining > 0:
#             tokens = max(self.TOKEN_START_PER_USER - idx * self.TOKEN_DECREMENT_PER_USER, 0)
#             tokens = min(tokens, remaining)
#             await self.counters.update_one(
#                 {"_id": "token_distribution"},
#                 {"$inc": {"index": 1, "distributed": tokens}},
#             )
#             return tokens

#         # dynamic grant
#         price = await self._get_token_price()
#         if price <= 0:
#             raise RuntimeError("oracle returned invalid token price")
#         tokens = round(self.JOIN_FEE_USD / price, 4)
#         logger.warning("dynamic token grant %.4f at %.4f USD", tokens, price)
#         return tokens

#     async def _get_token_price(self) -> float:
#         """TODO: connect to real oracle; must never return ≤0."""
#         return 0.25

#     # ─────────────────────── commission ───────────────────────────
#     async def _distribute_commission(
#         self, *, new_user_id: int, inviter_id: Optional[int], ancestors: List[int]
#     ):
#         inviter_share  = self.JOIN_FEE_USD * self.INVITER_RATE
#         upstream_pool  = self.JOIN_FEE_USD * self.UPSTREAM_RATE
#         company_share  = self.JOIN_FEE_USD * self.COMPANY_RATE

#         # direct inviter
#         if inviter_id:
#             await self._add_commission_to_user(inviter_id, inviter_share)
#         else:
#             company_share += inviter_share

#         # ancestors (excluding inviter)
#         higher = [uid for uid in ancestors if uid != inviter_id]
#         if higher:
#             share = upstream_pool / len(higher)
#             for uid in higher:
#                 anc  = await self.users.find_one({"user_id": uid}, {"slot_id": 1})
#                 slot = anc.get("slot_id", "")
#                 if slot in GHOST_SLOTS:
#                     await self._pay(MULTISIG_GHOST_WALLET_2OF2, share, new_user_id, f"ghost {slot}")
#                 elif slot in SECOND_ADMIN_SLOTS:
#                     await self._split_second_admin_pool(share, new_user_id)
#                 else:
#                     await self._add_commission_to_user(uid, share)
#         else:
#             company_share += upstream_pool

#         # company
#         if company_share:
#             await self._pay(POOL_WALLET_ADDRESS, company_share,
#                             new_user_id, "company pool")

#     # ─────────────────────── payment helpers ─────────────────────
#     async def _pay(self, wallet: str, amount: float, from_user: int, note: str):
#         """
#         Records a payment or, if the destination is a 2-of-2 multisig
#         (primary or any of SECOND_ADMIN_PERSONAL_WALLETS), submits it via SafeClient.
#         """
#         w = wallet.lower()

#         # 1️⃣ Primary multisig?
#         if w == MULTISIG_GHOST_WALLET_2OF2.lower():
#             alias = 'primary'
#         else:
#             # 2️⃣ Secondary admin multisigs?
#             admin_wallets = [addr.lower() for addr in SECOND_ADMIN_PERSONAL_WALLETS]
#             if w in admin_wallets:
#                 idx = admin_wallets.index(w) + 1
#                 alias = f'admin_pool_{idx}'
#             else:
#                 alias = None

#         # 3️⃣ اگر alias تشخیص داده شد، ارسال از طریق SafeClient
#         if alias:
#             # تبدیل USD به ETH
#             eth_price_usd = await self.price_provider.get_price()
#             eth_amount    = amount / eth_price_usd
#             try:
#                 result = self.safe_client.propose(
#                     to=wallet,
#                     value_eth=eth_amount,
#                     data="0x",
#                     alias=alias
#                 )
#                 self.logger.info(
#                     "SafeClient.propose called (alias=%s to=%s value_eth=%.6f) → %s",
#                     alias, wallet, eth_amount, result
#                 )
#                 return result
#             except Exception as e:
#                 self.logger.error(
#                     "Safe propose failed (alias=%s): %s", alias, e, exc_info=True
#                 )
#                 raise

#         # 4️⃣ وگرنه رکورد عادی در دیتابیس
#         record = {
#             "from_user":  from_user,
#             "amount_usd": round(amount, 8),
#             "to":         wallet,
#             "type":       note,
#             "timestamp":  datetime.utcnow(),
#         }
#         await self.payments.insert_one(record)
#         self.logger.info("Inserted payment record: %s", record)
#         return record
    
#     async def _add_commission_to_user(self, user_id: int, amount: float):
#         await self.users.update_one(
#             {"user_id": user_id},
#             {"$inc": {"commission_usd": round(amount, 8)}},
#         )

#     async def _split_second_admin_pool(self, amount: float, from_user: int):
#         """
#         Split equally among 5 second-level admins (3-dec precision).
#         Residue ≤0.004 stays in SECOND_ADMIN_POOL_WALLET.
#         """
#         per_admin = round(amount / 5, 3)
#         for w in SECOND_ADMIN_PERSONAL_WALLETS:
#             await self._pay(w, per_admin, from_user, "second-admin split")
#         residue = round(amount - per_admin * 5, 8)
#         if residue > 0:
#             await self._pay(SECOND_ADMIN_POOL_WALLET, residue, from_user, "second-admin residue")

#     # ─────────────────────── misc helpers ────────────────────────
#     async def _generate_code(self) -> str:
#         while True:
#             code = uuid.uuid4().hex[:8].upper()
#             if not await self.users.find_one({"referral_code": code}, {"_id": 1}):
#                 return code
            
#     #-----------------------------------------------------------------------------------------
#     async def _next_member_no(self) -> int:
#         doc = await self.counters.find_one_and_update(
#             {"_id": "member_no"},
#             {"$inc": {"seq": 1}},
#             upsert=True,
#             return_document=ReturnDocument.AFTER,
#         )
#         return int(doc["seq"])
    
#     #-----------------------------------------------------------------------------------------
#     # wrapper for legacy
#     async def ensure_profile(
#         self, chat_id: int, first_name: str, inviter_code: Optional[str] = None
#     ) -> Dict[str, Any]:
#         return await self.ensure_user(chat_id, first_name, inviter_code)





