

# myproject_database.py

import logging
import os
from datetime import datetime
from typing import Optional, Dict, Any, List

from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import PyMongoError, DuplicateKeyError
from pymongo import ReturnDocument, ASCENDING


class Database:
    def __init__(self):
        self.logger = logging.getLogger(self.__class__.__name__)

        try:
            mongo_uri = os.environ.get('MONGODB_URI')
            db_name = os.environ.get('MONGO_DB_NAME')

            if not mongo_uri:
                raise ValueError("MONGODB_URI environment variable not set")
            if not db_name:
                raise ValueError("MONGO_DB_NAME environment variable is not set.")

            self.client = AsyncIOMotorClient(mongo_uri)
            self.db = self.client[db_name]

            self.collection_users             =     self.db["users"]
            self.collection_languages         =     self.db["user_languages"]
            self.collection_translation_cache =     self.db["translation_cache"]
            self.collection_payments          =     self.db["payments"]
            
            self.collection_withdrawals       =     self.db["withdrawals"]   # NEW
            
            self.collection_orders            =     self.db["orders"]        # NEW  (سفارش‌های خرید/فروش)
            self.collection_counters          =     self.db["counters"]      # NEW
            self.collection_wallet_events     =     self.db["wallet_events"]
            # در __init__ بعد از تعریف بقیه‌ی collection_*
            self.collection_slots     = self.db["slots"]
            self.collection_schedules = self.db["schedules"]


            self.logger.info("✅ Database connected successfully.")

        except Exception as e:
            self.logger.error(f"❌ Database connection failed: {e}")
            raise
    #-------------------------------------------------------------------------------------   
    async def check_connection(self):
        """Ping MongoDB to ensure it’s up."""
        try:
            await self.client.admin.command("ping")
            self.logger.info("✅ MongoDB ping successful.")
        except Exception as e:
            self.logger.error(f"❌ MongoDB ping failed: {e}")
            raise

    #-------------------------------------------------------------------------------------   
    async def initialize_all_connections(self):
        """Initialize and verify all database connections"""
        try:
            # Check main database connection
            await self.check_connection()
            
            # ➋ Initialize counter member_no (only on first run)
            await self.collection_counters.update_one(
                {"_id": "member_no"},
                {"$setOnInsert": {"seq": 1000}},
                upsert=True
            )            

            # ➂ unique index on wallet_address (sparse: only docs that have it)
            await self.collection_users.create_index(
                [("wallet_address", ASCENDING)],
                unique=True,
                sparse=True,
                name="unique_wallet_address"
            )         
            
            await self.collection_payments.create_index(
                [("txid", ASCENDING)],
                unique=True,
                name="unique_txid"
            )            
           
            await self.collection_withdrawals.create_index(
                [("withdraw_id", ASCENDING)],
                unique=True,
                name="unique_withdraw_id"
            )           
                    
            await self.collection_slots.create_index(
                [("slot_id", ASCENDING)],
                unique=True,
                name="unique_slot_id"
            )

            # Removed index creation on _id for schedules since _id is unique by default
            
            self.logger.info("All database connections initialized and verified")
        except Exception as e:
            self.logger.error(f"Error initializing database connections: {e}")
            raise

    # ------------------- User Language Management -----------------------
    async def update_user_language(self, chat_id: int, language_code: str):
        """Set or update user's preferred language"""
        try:
            await self.collection_languages.update_one(
                {"user_id": chat_id},
                {"$set": {
                    "language": language_code,
                    "last_updated": datetime.utcnow()
                }},
                upsert=True
            )
        except Exception as e:
            self.logger.error(f"❌ update_user_language({chat_id}) failed: {e}")
            raise
        
    #-------------------------------------------------------------------------------------   
    async def get_user_language(self, chat_id: int) -> str:
        """Get stored language for user (fallback: 'en')"""
        try:
            user = await self.collection_languages.find_one(
                {"user_id": chat_id}, {"_id": 0, "language": 1}
            )
            return user["language"] if user and "language" in user else "en"
        except Exception as e:
            self.logger.error(f"❌ get_user_language({chat_id}) failed: {e}")
            return "en"
        
    #-------------------------------------------------------------------------------------   
    async def is_language_set(self, chat_id: int) -> bool:
        """Check if language was set for this user"""
        doc = await self.collection_languages.find_one(
            {"user_id": chat_id}, {"_id": 0, "language": 1}
        )
        return bool(doc and doc.get("language"))

    # ------------------- User Profile -----------------------
    async def insert_user(self, chat_id: int, first_name: str):
        """Insert or update user info"""
        try:
            await self.collection_users.update_one(
                {"user_id": chat_id},
                {"$set": {
                    "first_name": first_name,
                    "last_updated": datetime.utcnow()
                }},
                upsert=True
            )
        except Exception as e:
            self.logger.error(f"❌ insert_user({chat_id}) failed: {e}")
            raise
        
    #-------------------------------------------------------------------------------------   
    async def insert_user_if_not_exists(self, chat_id, first_name):
        await self.collection_users.update_one(
            {"user_id": chat_id},
            {"$setOnInsert": {
                "user_id": chat_id,
                "first_name": first_name,
                "language": "en",            # هرچی پیش‌فرض داشتی
                "promoted_language": False,  # ← فلگ جدید
                "created_at": datetime.utcnow()
            }},
            upsert=True
        )
        
    #-------------------------------------------------------------------------------------   
    async def is_language_prompt_done(self, chat_id) -> bool:
        doc = await self.collection_users.find_one(
            {"user_id": chat_id}, {"_id":0,"promoted_language":1}
        )
        return bool(doc and doc.get("promoted_language"))

    async def mark_language_prompt_done(self, chat_id):
        await self.collection_users.update_one(
            {"user_id": chat_id},
            {"$set": {"promoted_language": True}}
        )

    # ------------------- Translation Cache -----------------------
    async def get_cached_translation(self, text: str, target_lang: str) -> Optional[str]:
        try:
            key = f"{text}_{target_lang}"
            doc = await self.collection_translation_cache.find_one({"cache_key": key})
            if doc:
                return doc.get("translation")
            return None
        except PyMongoError as e:
            self.logger.error(f"❌ Error getting cached translation: {e}")
            return None
        
    #-------------------------------------------------------------------------------------   
    async def update_translation_cache(self, text: str, target_lang: str, translation: str):
        try:
            key = f"{text}_{target_lang}"
            await self.collection_translation_cache.update_one(
                {"cache_key": key},
                {
                    "$set": {
                        "original_text": text,
                        "target_lang": target_lang,
                        "translation": translation,
                        "timestamp": datetime.utcnow()
                    }
                },
                upsert=True
            )
        except PyMongoError as e:
            self.logger.error(f"❌ Error updating translation cache: {e}")
            
    #-------------------------------------------------------------------------------------   
    async def get_original_text_by_translation(self, translated_text: str, target_lang: str) -> Optional[str]:
        """
        برعکس get_cached_translation عمل می‌کند.
        می‌گردد در کالکشن اگر سندی پیدا شد که فیلد `translation == translated_text`
        و `target_lang == target_lang`، آنگاه `original_text` را برمی‌گرداند.
        """
        if not translated_text or not target_lang:
            return None

        if self.collection_translation_cache is not None:
            doc = await self.collection_translation_cache.find_one({
                "translation": translated_text,
                "target_lang": target_lang
            })
            if doc and "original_text" in doc:
                self.logger.info(f"Reverse lookup found original_text for '{translated_text}' in lang '{target_lang}'")
                return doc["original_text"]

        return None

# -------------------------------------------------------------
    async def get_user_balance(self, user_id: int) -> int:
        """
        برگرداندن موجودی توکن کاربر.

        Args:
            user_id (int): آیدی عددی تلگرام کاربر.

        Returns:
            int: تعداد توکن‌های کاربر (۰ اگر کاربر یا فیلد وجود نداشته باشد).
        """
        # فرض می‌کنیم collection_users قبلاً در __init__ مقداردهی شده است
        doc = await self.collection_users.find_one(
            {"user_id": user_id},
            {"_id": 0, "tokens": 1}
        )
        return int(doc.get("tokens", 0)) if doc else 0
# -------------------------------------------------------------

    async def adjust_balance(self, user_id: int, delta: int):
        """
        افزایش یا کاهش موجودی کاربر.

        delta می‌تواند منفی باشد.
        """
        await self.collection_users.update_one(
            {"user_id": user_id},
            {"$inc": {"tokens": delta}},
            upsert=True
        )

    async def set_balance(self, user_id: int, new_balance: int):
        """تنظیم مستقیم موجودی به مقدار مشخص."""
        await self.collection_users.update_one(
            {"user_id": user_id},
            {"$set": {"tokens": max(0, new_balance)}},
            upsert=True
        )
############---------------------------------------------------------------------------------------     
    async def store_payment_txid(self, user_id: int, txid: str) -> None:
        """
        ذخیره‌ی Hash تراکنش (TxID) برای پرداخت join fee.

        این تابع:
         1) یک سند جدید در کالکشن "payments" درج می‌کند
            با فیلدهای:
              - user_id: شناسه‌ی تلگرام کاربر
              - txid:     رشته‌ی هش تراکنش
              - timestamp: تاریخ و ساعت درج (UTC)
              - status:   "pending"  (برای پیگیری وضعیت تأیید)
         2) اجازه می‌دهد بعداً در webhook یا مانیتور کریپتو،
            همین سند را با وضعیت "confirmed" یا "failed" به‌روز کنید.
        """
        await self.collection_payments.insert_one({
            "user_id":    user_id,
            "txid":       txid,
            "timestamp":  datetime.utcnow(),
            "status":     "pending"
        })    
            
    #-----------------------------------------------------------------------------
    async def update_payment_status(self, txid: str, status: str) -> None:
        """
        به‌روزرسانی وضعیت سند پرداخت:
        - txid: Hash تراکنش
        - status: 'confirmed' یا 'failed'
        """
        await self.collection_payments.update_one(
            {"txid": txid},
            {"$set": {
                "status": status,
                "updated_at": datetime.utcnow()
            }}
        )
    #-----------------------------------------------------------------------------
    async def is_txid_used(self, txid: str) -> bool:
        """Return True if this TxID already exists in payments."""
        return await self.collection_payments.count_documents({"txid": txid}) > 0

############################################################################################################
    # ------------------------------------------------------------------
    async def _generate_member_no(self) -> int:
        """
        یک شمارهٔ عضویت یکتا و افزایشی برمی‌گرداند.
        از کالکشنی به نام 'counters' استفاده می‌کند.
        """
        counter = await self.collection_counters.find_one_and_update(
            {"_id": "member_no"},             # این سند فقط یک رکورد است
            {"$inc": {"seq": 1}},             # مقدار seq را +۱ می‌کند
            upsert=True,                      # اگر وجود نداشت می‌سازد
            return_document=ReturnDocument.AFTER,
        )
        return counter["seq"]
       
    # ------------------- Profile & Referral helpers -----------------------

    async def get_profile(self, user_id: int) -> Optional[Dict[str, Any]]:
        doc = await self.collection_users.find_one(
            {"user_id": user_id},
            {
                "_id": 0,
                "member_no":      1,
                "referral_code":  1,
                "tokens":         1,
                # دو فیلد مجزا
                "balance_usd":    1,      # ← NEW
                "commission_usd": 1,
                "joined":         1,
            },
        )
        if doc is None:
            return None

        # اگر member_no هنوز ست نشده باشد
        if "member_no" not in doc:
            doc["member_no"] = await self._generate_member_no()
            await self.collection_users.update_one(
                {"user_id": user_id},
                {"$set": {"member_no": doc["member_no"]}}
            )

        # تعداد زیرمجموعه‌ها
        doc["downline_count"] = await self.collection_users.count_documents(
            {"inviter_id": user_id}
        )

        # پیش‌فرض‌ها
        doc.setdefault("tokens", 0)
        doc.setdefault("balance_usd", 0.0)
        doc.setdefault("commission_usd", 0.0)
        doc.setdefault("joined", False)

        # تبدیل Decimal → float
        doc["balance_usd"]    = float(doc["balance_usd"])
        doc["commission_usd"] = float(doc["commission_usd"])
        return doc
    ###########-------------------------------------------------------------------------------------------
    async def get_downline(
        self,
        user_id: int,
        page: int = 1,
        page_size: int = 30,
    ) -> List[Dict[str, Any]]:
        """
        فهرست زیرمجموعه‌های مستقیم کاربر، به‌صورت صفحه‌بندی.
        """
        try:
            skip = max(0, (page - 1) * page_size)
            cursor = (
                self.collection_users.find(
                    {"inviter_id": user_id},
                    {"_id": 0, "first_name": 1, "referral_code": 1},
                )
                .skip(skip)
                .limit(page_size)
            )
            return await cursor.to_list(length=page_size)
        except Exception as e:
            self.logger.error(f"❌ get_downline({user_id}) failed: {e}")
            raise
    
    # ─── تابع کمکی عمومی برای کانترهای افزایشی ────────────────────────────
    async def _get_next_sequence(self, name: str) -> int:
        """
        خواندن و ++ کردن کانتر عمومی (اتمیک).
        مثال name: "order_id" یا "member_no".
        """
        counter = await self.collection_counters.find_one_and_update(
            {"_id": name},
            {"$inc": {"seq": 1}},
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        return counter["seq"]
    
    #----------------------------------------------------------------------------------------
    # موجودی دلاری (پس از فروش توکن)
    async def get_fiat_balance(self, user_id: int) -> float:
        doc = await self.collection_users.find_one({"user_id": user_id}, {"usd_balance": 1})
        return float(doc.get("usd_balance", 0)) if doc else 0.0
    
    #-------------------------------------------------------------------------------------   
    async def credit_fiat_balance(self, user_id: int, amount: float):
        await self.collection_users.update_one(
            {"user_id": user_id},
            {"$inc": {"usd_balance": amount}},
            upsert=True,
        )
        
    #-------------------------------------------------------------------------------------   
    async def set_fiat_balance(self, user_id: int, amount: float):
        await self.collection_users.update_one(
            {"user_id": user_id}, {"$set": {"usd_balance": amount}}, upsert=True
        )
################################### withdraw #####################################################################################

    # ─────────────────────── Referral helpers ────────────────────────
    async def get_downline_count(self, user_id: int) -> int:
        """تعداد مستقیم‌ترین زیرمجموعه‌های کاربر."""
        return await self.collection_users.count_documents({"parent_id": user_id})

    async def clear_downline(self, user_id: int) -> None:
        """
        والدِ تمام زیرمجموعه‌های مستقیم را خالی می‌کند.
        همچنین می‌توانید به دلخواه، رکوردی در لاگ نگه دارید.
        """
        await self.collection_users.update_many(
            {"parent_id": user_id},
            {"$set": {"parent_id": None}}
        )

    async def mark_membership_withdrawn(self, user_id: int) -> None:
        """
        فلَگ‌های عضویت را ریست می‌کند تا کاربر برای استفادهٔ مجدد مجبور
        به پرداخت یا دعوت مجدد شود.
        """
        await self.collection_users.update_one(
            {"user_id": user_id},
            {"$set": {"joined": False, "membership_withdrawn": True,
                      "withdrawn_at": datetime.utcnow()}}
        )

    # ─────────────────── Withdrawal life-cycle helpers ───────────────
    async def update_withdraw_status(
        self, withdraw_id: int, status: str, txid: Optional[str] = None
    ) -> None:
        """
        به‌روز‌رسانی وضعیت برداشت (pending → sent/failed).
        `txid` برای زمانی است که تسویهٔ آنی روی بلاک‌چین انجام شده باشد.
        """
        update_doc: Dict[str, Any] = {
            "status": status,
            "updated_at": datetime.utcnow(),
        }
        if txid:
            update_doc["txid"] = txid

        await self.collection_withdrawals.update_one(
            {"withdraw_id": withdraw_id},
            {"$set": update_doc}
        )

    # (اختیاری) اگر می‌خواهید برداشت‌های باز را استریم کنید
    async def get_pending_withdrawals(self) -> List[Dict[str, Any]]:
        """برمی‌گرداند تمام درخواست‌های برداشت با status='pending'."""
        cursor = self.collection_withdrawals.find({"status": "pending"})
        return await cursor.to_list(length=None)
    
    async def mark_withdraw_failed(self, chat_id: int, reason: str) -> None:
        """
        آخرین درخواست برداشتِ کاربر را به حالت «failed» می‌برد و دلیل خطا را ذخیره می‌کند.
        """
        await self.collection_withdrawals.update_one(
            {"chat_id": chat_id, "status": "pending"},       # آخرین رکورد در انتظار
            {"$set": {
                "status": "failed",
                "fail_reason": reason,
                "updated_at": datetime.utcnow(),
            }}
        )    
    
    async def mark_withdraw_paid(
        self, user_id: int, tx_id: str
    ) -> Optional[Dict[str, Any]]:
        """
        Marks the most recent withdrawal request for the given user as paid.
        Sets status to 'paid', stores the blockchain transaction ID and timestamp.

        Returns the updated withdrawal document, or None if no pending request found.
        """
        updated = await self.collection_withdrawals.find_one_and_update(
            {"user_id": user_id, "status": "pending"},
            {
                "$set": {
                    "status": "paid",
                    "tx_id": tx_id,
                    "paid_at": datetime.utcnow(),
                }
            },
            sort=[("created_at", -1)],
            return_document=ReturnDocument.AFTER,
        )
        return updated
    
    
    # ------------------------------------------------------------------
    async def create_withdraw_request(
        self,
        user_id: int,
        address: str,
        amount: float = 50.0,           # پیش‌فرض برای حق عضویت
    ) -> int:
        """
        درج ایمن یک درخواست برداشت جدید.

        ● اگر همان کاربر هنوز درخواست «pending» داشته باشد → خطا.
        ● شناسهٔ یکتا (auto-increment) با کلید `withdraw_id`.
        ● در صورت بروز حذف هم‌زمان (race condition) روی همان id،
        DuplicateKeyError گرفته و مجدداً تلاش می‌شود.

        Returns
        -------
        wid : int
            شمارهٔ یکتای درخواست برداشت.
        """
        # ➊ آیا قبلاً درخواست باز دارد؟
        existing = await self.collection_withdrawals.find_one(
            {"user_id": user_id, "status": "pending"}
        )
        if existing:
            raise ValueError("pending_withdraw_exists")

        # ➋ حلقهٔ امن برای ایجاد ID یکتا
        for _ in range(3):                         # حداکثر ۳ بار تلاش
            wid = await self._get_next_sequence("withdraw_id")
            try:
                await self.collection_withdrawals.insert_one(
                    {
                        "withdraw_id":  wid,
                        "user_id":      user_id,
                        "amount":       amount,
                        "address":      address,
                        "status":       "pending",
                        "requested_at": datetime.utcnow(),
                    }
                )
                return wid                         # موفقیت ☑
            except DuplicateKeyError:
                # در شرایط رقابتی نادر رخ می‌دهد؛ تکرار حلقه
                continue

        # اگر به اینجا برسیم یعنی بعد از ۳ تلاش هنوز موفق نشدیم
        raise RuntimeError("withdraw_id_generation_failed")


    async def get_last_withdraw_request(
        self, user_id: int
    ) -> Optional[Dict[str, Any]]:
        """
        Returns the most recent withdraw request for the given user,
        or None if no request exists. Assumes each request document
        has a 'created_at' field of type datetime.
        """
        return await self.collection_withdrawals.find_one(
            {"user_id": user_id},
            sort=[("created_at", -1)]
        )


########################################################################################################################

    # ── ایجاد سفارش فروش ───────────────────────────────────────────────
    async def create_sell_order(self, order: dict) -> int:
        seq = await self._get_next_sequence("order_id")      # ← همین شمارنده را
        order.update({
            "order_id":   seq,
            "side":       "sell",        # تمایز جهت سفارش (اختیاری)
            "status":     "open",
            "remaining":  order["amount"],
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
        })
        await self.collection_orders.insert_one(order)
        return seq

    # ── ایجاد سفارش خرید ───────────────────────────────────────────────
    async def create_buy_order(self, order: dict) -> int:
        seq = await self._get_next_sequence("order_id")      # ← همان شمارنده
        order.update({
            "order_id":   seq,
            "side":       "buy",
            "status":     "open",
            "remaining":  order["amount"],
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
        })
        await self.collection_orders.insert_one(order)
        return seq
 

    # ─── انتقال توکن بین دو کاربر (اتمیک) ───────────────────────────────
    async def transfer_tokens(self, seller_id: int, buyer_id: int, amount: int):
        """
        کسر از seller و افزودن به buyer به‌صورت تراکنش اتمیک.
        موجودی کاربران در فیلد «tokens» نگه‌داری می‌شود.
        """
        async with await self.client.start_session() as session:
            async with session.start_transaction():
                # ➊ کسر از فروشنده (اگر کافی نباشد exc بالا می‌آید)
                res = await self.collection_users.update_one(
                    {"user_id": seller_id, "tokens": {"$gte": amount}},
                    {"$inc": {"tokens": -amount}},
                    session=session,
                )
                if res.modified_count != 1:
                    raise ValueError("Seller balance insufficient")

                # ➋ افزودن به خریدار (اگر کاربر وجود نداشت ساخته می‌شود)
                await self.collection_users.update_one(
                    {"user_id": buyer_id},
                    {"$inc": {"tokens": amount}},
                    upsert=True,
                    session=session,
                )

    #-------------------------------------------------------------------------------------   
    async def set_wallet_address(self, user_id: int, address: str) -> None:
        """ذخیره یا به‌روزرسانی آدرس کیف پول کاربر."""
        await self.collection_users.update_one(
            {"user_id": user_id},
            {"$set": {"wallet_address": address}},
            upsert=True
        )
        
    #-------------------------------------------------------------------------------------   
    async def get_wallet_address(self, user_id: int) -> str | None:
        """بازیابی آدرس کیف پول کاربر یا None اگر ذخیره نشده باشد."""
        doc = await self.collection_users.find_one(
            {"user_id": user_id},
            {"wallet_address": 1}
        )
        return doc.get("wallet_address") if doc else None
    
    #-------------------------------------------------------------------------------------   
    async def get_user_by_wallet(self, address: str) -> Optional[int]:
        """
        If this address is already taken, return the owner’s chat_id.
        """
        doc = await self.collection_users.find_one(
            {"wallet_address": address},
            {"_id": 0, "user_id": 1}
        )
        return doc["user_id"] if doc else None

    # ── مدیریت موجودی و تاریخچه ─────────────────────────────────
    async def get_user_balance(self, user_id: int) -> float:
        """موجودی فعلی توکن کاربر (یا ۰.۰ اگر فیلد وجود نداشته باشد)."""
        doc = await self.collection_users.find_one(
            {"user_id": user_id},
            {"_id": 0, "tokens": 1}
        )
        return float(doc.get("tokens", 0.0)) if doc else 0.0
    
    #-------------------------------------------------------------------------------------   
    async def adjust_balance(self, user_id: int, delta: float):
        """اضافه یا کم کردن اتمیک مقدار delta در موجودی."""
        await self.collection_users.update_one(
            {"user_id": user_id},
            {"$inc": {"tokens": delta}},
            upsert=True
        )
        
    #-------------------------------------------------------------------------------------   
    async def record_wallet_event(
        self, user_id: int, amount: float, event_type: str, description: str = ""
    ) -> None:
        """
        ثبت هر تغییر در موجودی:
        event_type مثل "referral_reward" یا "manual_adjustment"
        """
        await self.collection_wallet_events.insert_one({
            "user_id":     user_id,
            "amount":      amount,
            "event_type":  event_type,
            "description": description,
            "timestamp":   datetime.utcnow()
        })

    async def get_wallet_history(
        self, user_id: int, limit: int = 20
    ) -> List[Dict[str, Any]]:
        """بازگرداندن جدیدترین رویدادهای کیف‌پول به ترتیب timestamp نزولی."""
        cursor = self.collection_wallet_events.find(
            {"user_id": user_id},
            {"_id": 0, "amount": 1, "event_type": 1, "description": 1, "timestamp": 1}
        ).sort("timestamp", -1).limit(limit)
        return await cursor.to_list(length=limit)
      
    #------------------------------------------------------------------------------------
    async def close(self):
            """
            بستن اتصال به MongoDB هنگام خاموشی بات
            """
            # متد closeِ خود MongoClient همگام‌نشده است،
            # اما می‌توانیم آن را داخل متد async فراخوانی کنیم.
            self.client.close()
            self.logger.info("✅ Database connection closed.")        