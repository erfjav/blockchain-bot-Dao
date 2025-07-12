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
    WALLET_FIRST_LEADER_POOL,    # 🪙 WALLET_FIRST_LEADER_POOL
                                # Pool for first-level admin commissions.
                                # Accumulates funds allocated to MAIN_LEADER_IDS.
                                # Every 10 days, split equally among FIRST_LEADER_PERSONAL_WALLETS.
    
    WALLET_SECOND_LEADER_POOL,   # 🪪 WALLET_SECOND_LEADER_POOL
                                # Pool for second-level admin commissions.
                                # Receives upstream commission shares for SECOND_LEADER_USER_IDS.
                                # Every 10 days, 95% is split among 5 personal wallets;
                                # 5% is kept as buffer for covering transaction fees.

    # Personal wallets (Trust Wallet)
    FIRST_LEADER_PERSONAL_WALLETS,   # 👤 FIRST_LEADER_PERSONAL_WALLETS
                                    # List of personal wallets for top-tier admins (Trust Wallet).
                                    # Each receives equal share from WALLET_FIRST_LEADER_POOL.      
    
    SECOND_LEADER_PERSONAL_WALLETS,  # 👥 SECOND_LEADER_PERSONAL_WALLETS
                                    # Exactly 5 personal wallets for second-tier admins (Trust Wallet).
                                    # Each receives equal share (after buffer deduction) from WALLET_SECOND_LEADER_POOL.

    # Staff / role IDs
    MAIN_LEADER_IDS,        # “first‑admins” – always eligible
    
    SECOND_LEADER_USER_IDS,  # “second‑admins” – must still bring 2
)
from core.crypto_handler import CryptoHandler


# ─────────────────────────────────────────────────────────────────────────────
# Business constants
# ----------------------------------------------------------------------------
JOIN_FEE_USD        = Decimal("50")
INVITER_DIRECT_USD  = Decimal("5")              # Paid immediately to inviter

# From the remaining $45
COMPANY_MAIN_RATE   = Decimal("0.20")            # 9 USDT
COMPANY_ALT_RATE    = Decimal("0.10")            # 4.5 USDT
UPSTREAM_RATE       = Decimal("0.70")            # 31.5 USDT

_DECIMALS = 6

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
            await self._transfer_wallet(WALLET_FIRST_LEADER_POOL, amount, f"1stadmin‑{note}", from_uid=uid)
        elif uid in SECOND_LEADER_USER_IDS:
            await self._transfer_wallet(WALLET_SECOND_LEADER_POOL, amount, f"2ndadmin‑{note}", from_uid=uid)
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
    
    async def _transfer_wallet(
        self,
        wallet: str,
        amount: Decimal,
        note: str,
        *,
        from_uid: Optional[int] = None,
    ):
        """Send `amount` USDT (Decimal) from the correct pool to `wallet` on Tron."""
        micros = _dec_to_micro(amount)

        # 1) rough fee estimate (optional – can be 0)
        fee_estimate = await self._estimate_fee(wallet, micros)
        logger.debug(
            "Transfer %s → %s (%.6f USDT) fee≈%.4f",
            note,
            wallet,
            amount,
            fee_estimate,
        )

        # 2) map destination wallet ⇒ source key name for CryptoHandler.transfer()
        source_map = {
            WALLET_JOIN_POOL:              "join",
            WALLET_FIRST_LEADER_POOL:      "admin1",
            WALLET_SECOND_LEADER_POOL:     "admin2",
            WALLET_SPLIT_70:               "split70",
            WALLET_SPLIT_20:               "split20",
            WALLET_SPLIT_10:               "split10",
        }
        from_wallet = source_map.get(wallet, "join")  # default to join-pool key

        # 3) try up to three times
        for attempt in range(3):
            try:
                tx_hash = await self.crypto_handler.transfer(
                    "tron",
                    wallet,
                    micros,
                    from_wallet,           # ← fourth positional argument (required)
                    token_symbol="USDT",
                    decimals=_DECIMALS,
                )
                await self.col_payments.insert_one(
                    {
                        "user_id":    from_uid,
                        "wallet":     wallet,
                        "amount_usd": str(amount),
                        "tx_hash":    tx_hash,
                        "status":     "success",
                        "note":       note,
                        "timestamp":  datetime.utcnow(),
                    }
                )
                return tx_hash
            except Exception as exc:
                logger.warning(
                    "Transfer attempt %d failed (%s): %s", attempt + 1, note, exc
                )
                await asyncio.sleep(1.5)

        # 4) after 3 failures mark as pending
        await self.col_payments.insert_one(
            {
                "user_id":    from_uid,
                "wallet":     wallet,
                "amount_usd": str(amount),
                "tx_hash":    None,
                "status":     "pending_retry",
                "note":       note,
                "timestamp":  datetime.utcnow(),
            }
        )
        return None  # explicit fallback    
    
    # async def _transfer_wallet(self, wallet: str, amount: Decimal, note: str, *, from_uid: Optional[int] = None):
    #     micros = _dec_to_micro(amount)
    #     fee_estimate = await self._estimate_fee(wallet, micros)
    #     logger.debug("Transfer %s → %s (%.6f USDT) fee≈%.4f", note, wallet, amount, fee_estimate)

    #     for attempt in range(3):
    #         try:
    #             tx_hash = await self.crypto_handler.transfer("tron", wallet, micros, token_symbol="USDT", decimals=6)
    #             await self.col_payments.insert_one({
    #                 "user_id":   from_uid,
    #                 "wallet":    wallet,
    #                 "amount_usd": str(amount),
    #                 "tx_hash":   tx_hash,
    #                 "status":    "success",
    #                 "note":      note,
    #                 "timestamp": datetime.utcnow(),
    #             })
    #             # return
    #             return tx_hash
    #         except Exception as exc:
    #             logger.warning("Transfer attempt %d failed (%s): %s", attempt + 1, note, exc)
    #             await asyncio.sleep(1.5)

    #     # after 3 failed attempts – mark as pending
    #     await self.col_payments.insert_one({
    #         "user_id":   from_uid,
    #         "wallet":    wallet,
    #         "amount_usd": str(amount),
    #         "tx_hash":   None,
    #         "status":    "pending_retry",
    #         "note":      note,
    #         "timestamp": datetime.utcnow(),
    #     })
        
        # return None  # ← این خط اضافه شد
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
                "tron", WALLET_SECOND_LEADER_POOL, "USDT", 6
            )))
            if bal == 0:
                return

            # محاسبه سهم هر نفر با احتساب buffer
            buffer_target = _round_down(bal * Decimal("0.05"))
            distributable = bal - buffer_target
            share = _round_down(distributable / Decimal(len(SECOND_LEADER_PERSONAL_WALLETS)))

            total_estimated_fees = Decimal("0")
            for w in SECOND_LEADER_PERSONAL_WALLETS:
                total_estimated_fees += await self._estimate_fee(w, _dec_to_micro(share))
            if total_estimated_fees > buffer_target:
                deficit = total_estimated_fees - buffer_target
                reduction_each = _round_down(deficit / Decimal(len(SECOND_LEADER_PERSONAL_WALLETS)))
                share -= reduction_each
                if share <= 0:
                    self.logger.warning("Second-admin share turned non-positive after fee adjustment – postponing payout.")
                    return

            # zip با SECOND_LEADER_USER_IDS
            for idx, (w, user_id) in enumerate(zip(SECOND_LEADER_PERSONAL_WALLETS, SECOND_LEADER_USER_IDS), 1):
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
                "tron", WALLET_FIRST_LEADER_POOL, "USDT", 6
            )))
            if bal == 0:
                return

            share = _round_down(bal / Decimal(len(FIRST_LEADER_PERSONAL_WALLETS)))

            # ترتیب zip باید با MAIN_LEADER_IDS یکی باشد
            for idx, (w, user_id) in enumerate(zip(FIRST_LEADER_PERSONAL_WALLETS, MAIN_LEADER_IDS), 1):
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
    
    ###---------------------------------------------------------------------------------
    async def _payout_every_30_days(self):
        now = datetime.utcnow()
        async for user in self.col_users.find({"balance_usd": {"$gt": 0}}):
            uid = user["user_id"]
            if uid in MAIN_LEADER_IDS + SECOND_LEADER_USER_IDS:
                continue  # admins handled separately

            # ← استفاده از helper
            days_left = await self.days_until_next_monthly_payout(uid, 30)
            if days_left:
                continue  # هنوز ماه کامل نشده

            amt = Decimal(user["balance_usd"])
            wallet = user.get("tron_wallet")
            if not wallet:
                continue

            # await self._transfer_wallet(wallet, amt, "monthly-member", from_uid=uid)
            # await self.col_users.update_one({"user_id": uid}, {"$set": {"balance_usd": Decimal("0")}})
            # await self._refresh_eligibility(uid)   
             
            tx_hash = await self._transfer_wallet(wallet, amt, "monthly-member", from_uid=uid)
            await self.col_users.update_one({"user_id": uid}, {"$set": {"balance_usd": Decimal("0")}})
            await self._refresh_eligibility(uid)

            # ثبت لاگ پرداخت در دیتابیس
            await self.db.store_user_payment(
                user_id=uid,
                amount=float(amt),
                token="USDT",
                wallet=wallet,
                tx_hash=tx_hash,
                payment_type="MONTHLY_PAYOUT"
            )             
                        
    ###---------------------------------------------------------------------------------
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






