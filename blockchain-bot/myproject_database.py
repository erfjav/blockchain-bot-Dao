

# myproject_database.py

import logging
import os
from datetime import datetime
from typing import Optional, Dict, Any

from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import PyMongoError


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

            self.collection_users = self.db["users"]
            self.collection_languages = self.db["user_languages"]
            self.collection_translation_cache = self.db["translation_cache"]

            self.logger.info("✅ Database connected successfully.")

        except Exception as e:
            self.logger.error(f"❌ Database connection failed: {e}")
            raise

    async def check_connection(self):
        """Ping MongoDB to ensure it’s up."""
        try:
            await self.client.admin.command("ping")
            self.logger.info("✅ MongoDB ping successful.")
        except Exception as e:
            self.logger.error(f"❌ MongoDB ping failed: {e}")
            raise


    async def initialize_all_connections(self):
        """Initialize and verify all database connections"""
        try:
            # Check main database connection
            await self.check_connection()
            
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
    
        

    async def get_user_balance(self, user_id: int) -> int:
        doc = await self.collection_users.find_one({"user_id": user_id}, {"tokens": 1})
        return doc.get("tokens", 0) if doc else 0
        
        
# myproject_database.py  ← داخل class Database
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
        