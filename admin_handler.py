

# admin_handler.py
# ────────────────────────────────────────────────────────────────────────
from __future__ import annotations

import logging
from decimal import Decimal

from telegram import Update
from telegram.ext import ContextTypes, CommandHandler

from core.price_provider import DynamicPriceProvider
from bot_ui.language_Manager import TranslationManager
from bot_ui.keyboards import TranslatedKeyboards
from state_manager import pop_state, push_state

from config import ADMIN_USER_IDS


class AdminHandler:
    """فرمان‌های مدیریتی مربوط به قیمت پویا و تنظیمات توکن."""

    def __init__(
        self,
        price_provider: DynamicPriceProvider,
        keyboards: TranslatedKeyboards,
        translation_manager: TranslationManager,
    ) -> None:
        self.price_provider = price_provider
        self.translation_manager = translation_manager
        self.keyboards = keyboards
        self.admin_ids = set(ADMIN_USER_IDS)
        self.logger = logging.getLogger(self.__class__.__name__)


    async def show_admin_panel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        نمایش منوی پنل ادمین با دکمه‌های مدیریتی فقط برای ادمین‌ها.
        این منو شامل دکمه‌های زیر است:
            - 📸 Price Snapshot: نمایش وضعیت قیمت و ولت
            - 💾 Set Total Supply: راهنمای تغییر سقف عرضه توکن
            - 🗑 Flush Price Cache: پاک‌سازی کش قیمت
            - ⬅️ Back: بازگشت به منوی قبل

        اگر سیستم چندزبانه داری، از کیبورد ترجمه‌شونده استفاده می‌کند.
        اگر خواستی گزینه‌های بیشتری اضافه کنی، فقط در متد build_admin_panel_keyboard لیست دکمه‌ها را گسترش بده.
        """
        chat_id = update.effective_chat.id

        try:
            
            push_state(context, "admin_panel_menu")         # ← این خط اضافه شد
            context.user_data["state"] = "admin_panel_menu" # ← برای سازگاری
            # توضیح منوی ادمین (می‌توانی با توجه به زبان کاربر ترجمه هم بکنی)
            panel_message = (
                "🛠 <b>Admin Panel</b>\n"
                "Select an action below:\n\n"
                "<b>📸 Price Snapshot</b>: Show wallet and price info\n"
                "<b>💾 Set Total Supply</b>: Guide for updating total supply\n"
                "<b>🗑 Flush Price Cache</b>: Reset token price cache\n"
                "<b>⬅️ Back</b>: Return to the previous menu"
            )

            # ساخت کیبورد ترجمه‌شده مخصوص ادمین (حتماً self.keyboards از کلاس TranslatedKeyboards باشد)
            reply_markup = await self.keyboards.build_admin_panel_keyboard(chat_id)

            await update.message.reply_text(
                panel_message,
                reply_markup=reply_markup,
                parse_mode="HTML"
            )
        except Exception as e:
            # ثبت لاگ و ارسال پیام خطا به ادمین
            self.logger.error(f"Admin panel error: {e}")
            await update.message.reply_text(
                "⚠️ An error occurred while opening the Admin Panel.",
                parse_mode="HTML"
            )

    # ─────────────────────── public commands ────────────────────────────
    
    async def price_snapshot_cmd(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """/price_snapshot → وضعیت جاری ولت + قیمت."""
        try:
            
            push_state(context, "admin_price_snapshot")
            context.user_data["state"] = "admin_price_snapshot"            
            
            if not self._is_admin(update):  # مجوز
                return

            snap = await self.price_provider.snapshot()
            msg_en = (
                "📊 <b>Token price snapshot</b>\n"
                f"• Wallet balance: <code>${snap['wallet_balance_usd']:.2f}</code>\n"
                f"• Circulating supply: <code>{snap['circulating_supply']:,}</code>\n"
                f"• Price: <b>${snap['price_usd']:.6f}</b>"
            )
            await update.message.reply_text(
                await self.translation_manager.translate_for_user(
                    msg_en, update.effective_chat.id
                ),
                parse_mode="HTML",
                reply_markup=await self.keyboards.build_back_exit_keyboard(update.effective_chat.id)
            )
        except Exception as e:
            self.logger.error(f"Error in price_snapshot_cmd: {e}")
            await update.message.reply_text(
                "⚠️ An error occurred while showing the price snapshot.",
                parse_mode="HTML"
            )
    
    async def set_total_supply_cmd(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """/set_total_supply 15000000 → اصلاح سقف عرضه (state: admin_set_total_supply)"""
        try:
            # ثبت state اختصاصی
            push_state(context, "admin_set_total_supply")
            context.user_data["state"] = "admin_set_total_supply"

            if not self._is_admin(update):
                return

            if not context.args:
                await update.message.reply_text(
                    "Usage: /set_total_supply 15000000",
                    reply_markup=await self.keyboards.build_back_exit_keyboard(update.effective_chat.id)
                )
                return

            try:
                new_supply = int(context.args[0])
                if new_supply <= 0:
                    raise ValueError
            except ValueError:
                await update.message.reply_text(
                    "Send a positive integer.",
                    reply_markup=await self.keyboards.build_back_exit_keyboard(update.effective_chat.id)
                )
                return

            # تغییر مقدار در runtime
            self.price_provider.TOTAL_SUPPLY = Decimal(new_supply)
            # پاک کردن کش تا فوراً اعمال شود
            await self._flush_cache()
            await update.message.reply_text(
                f"✅ TOTAL_SUPPLY set to {new_supply:,} tokens.",
                reply_markup=await self.keyboards.build_back_exit_keyboard(update.effective_chat.id)
            )
        except Exception as e:
            self.logger.error(f"Error in set_total_supply_cmd: {e}")
            await update.message.reply_text(
                "⚠️ An error occurred while updating the total supply.",
                parse_mode="HTML"
            )

    async def flush_price_cache_cmd(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """/flush_price_cache → پاک‌کردن کش قیمت (state: admin_flush_price_cache)"""
        try:
            # ثبت state اختصاصی
            push_state(context, "admin_flush_price_cache")
            context.user_data["state"] = "admin_flush_price_cache"

            if not self._is_admin(update):
                return

            await self._flush_cache()
            await update.message.reply_text(
                "🗑 Price cache cleared.",
                reply_markup=await self.keyboards.build_back_exit_keyboard(update.effective_chat.id)
            )
        except Exception as e:
            self.logger.error(f"Error in flush_price_cache_cmd: {e}")
            await update.message.reply_text(
                "⚠️ An error occurred while flushing the price cache.",
                parse_mode="HTML"
            )

    # ─────────────────────── helper utilities ───────────────────────────
    async def _flush_cache(self) -> None:
        self.price_provider._cache_price = None  # noqa: SLF001
        self.price_provider._cache_ts = 0

    def _is_admin(self, update: Update) -> bool:
        chat_id = update.effective_chat.id
        if chat_id not in self.admin_ids:
            self.logger.warning("Unauthorized admin command from %s", chat_id)
            return False
        return True

