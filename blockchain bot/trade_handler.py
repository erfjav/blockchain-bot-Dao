

from __future__ import annotations
"""
trade_handler.py – 💰 Trade module (Buy / Sell) for your Telegram bot
--------------------------------------------------------------------
منطق کامل خرید و فروش توکن با صفحهٔ گفتگو (ConversationHandler).

◀️ جریان «فروش»
   1. کاربر «💸 Sell» را می‌زند → موجودی و قیمت فعلی نمایش داده می‌شود.
   2. بات مقدار توکنِ موردنظر برای فروش را می‌پرسد.
   3. پس از دریافت عدد، درخواستی در کانال TRADE_CHANNEL ارسال می‌شود
      شامل ID‌ کاربر (member_no یا referral_code)، تعداد توکن و دکمهٔ پشتیبانی.

▶️ جریان «خرید»
   1. کاربر «🛒 Buy» را می‌زند → قیمت فعلی نمایش داده می‌شود.
   2. بات تعداد توکن موردنیاز را می‌پرسد.
   3. پس از دریافت عدد، قیمت پیشنهادیِ کاربر برای هر توکن را می‌پرسد.
   4. درخواستی در کانال TRADE_CHANNEL ارسال می‌شود شامل تعداد، قیمت پیشنهادی و دکمهٔ پشتیبانی.

پیش‌نیازها
-----------
• در settings یا env:  TRADE_CHANNEL_ID  ,  SUPPORT_USER_USERNAME
• وابستگی به:
    - TranslatedKeyboards       → build_trade_menu_keyboard / build_back_exit_keyboard
    - TranslationManager       → translate_for_user()
    - Database                 → get_user_balance(user_id)  (async)
    - price_provider.get_price() (async یا sync) → قیمت توکن به دلار
    - ReferralManager.get_profile(user_id)      → برای member_no یا referral_code
"""

import logging
import os
from typing import Tuple, List

from telegram import (
    Update,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
)
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)

from keyboards import TranslatedKeyboards
from language_Manager import TranslationManager
from error_handler import ErrorHandler
from Referral_logic_code import ReferralManager

from myproject_database import Database  # Async wrapper

TRADE_CHANNEL_ID = int(os.getenv("TRADE_CHANNEL_ID", "0"))
SUPPORT_USER_USERNAME = os.getenv("SUPPORT_USER_USERNAME", "YourSupportUser")

# Conversation states
SELL_AMOUNT, BUY_AMOUNT, BUY_PRICE = range(3)

logger = logging.getLogger(__name__)


class TradeHandler:
    """Registers handlers for the 💰 Trade flow."""

    def __init__(
        self,
        keyboards: TranslatedKeyboards,
        translation_manager: TranslationManager,
        db: Database,
        price_provider,
        referral_manager: ReferralManager,
        error_handler: ErrorHandler,
        
    ) -> None:
        self.keyboards = keyboards
        self.translation_manager = translation_manager
        self.db = db
        self.price_provider = price_provider
        self.referral_manager = referral_manager
        self.error_handler = error_handler
        self.logger = logging.getLogger(self.__class__.__name__)

    # ───────────────────────────────────────── helper utilities ────────────

    async def _get_user_identifier(self, user_id: int) -> str:
        """Return member_no if available else referral_code as display ID."""
        profile = await self.referral_manager.get_profile(user_id)
        if not profile:
            return str(user_id)
        return str(profile.get("member_no") or profile.get("referral_code") or user_id)

    def _support_inline_keyboard(self) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            [[InlineKeyboardButton("🆘 Support", url=f"https://t.me/{SUPPORT_USER_USERNAME}")]]
        )

    # ───────────────────────────────────────── entry points ────────────────

    async def trade_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Shows translated trade menu."""
        chat_id = update.effective_chat.id
        kb: ReplyKeyboardMarkup = await self.keyboards.build_trade_menu_keyboard(chat_id)
        await update.message.reply_text(
            await self.translation_manager.translate_for_user("Select an option:", chat_id),
            reply_markup=kb,
        )
        return ConversationHandler.END  # just menu – not entering conversation yet

    # ───────────────────────────────────────── SELL FLOW ──────────────────

    async def sell_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.effective_chat.id
        balance = await self.db.get_user_balance(chat_id)  # ← implement in Database
        price = await self.price_provider.get_price()

        msg_en = (
            f"Current token price: ${price:.4f}\n"
            f"Your balance: {balance} tokens\n\n"
            "How many tokens do you want to sell?"
        )
        await update.message.reply_text(
            await self.translation_manager.translate_for_user(msg_en, chat_id),
            reply_markup=await self.keyboards.build_back_exit_keyboard(chat_id),
        )
        return SELL_AMOUNT

    async def sell_amount(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.effective_chat.id
        txt = update.message.text.strip()
        if not txt.isdigit() or int(txt) <= 0:
            await update.message.reply_text(
                await self.translation_manager.translate_for_user("Please send a valid number.", chat_id)
            )
            return SELL_AMOUNT

        amount = int(txt)
        identifier = await self._get_user_identifier(chat_id)

        # Send to trade channel
        text_channel = (
            f"🚨 SELL Request\n"
            f"ID: {identifier}\n"
            f"Amount: {amount} tokens\n\n"
            "Contact support to proceed:"
        )
        await update.get_bot().send_message(
            chat_id=TRADE_CHANNEL_ID,
            text=text_channel,
            reply_markup=self._support_inline_keyboard(),
        )

        # Acknowledge user
        await update.message.reply_text(
            await self.translation_manager.translate_for_user(
                "Your sell request has been submitted to support.", chat_id
            ),
            reply_markup=await self.keyboards.build_back_exit_keyboard(chat_id),
        )
        return ConversationHandler.END

    # ───────────────────────────────────────── BUY FLOW ───────────────────

    async def buy_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.effective_chat.id
        price = await self.price_provider.get_price()
        msg_en = (
            f"Current token price: ${price:.4f}\n\n"
            "How many tokens do you need?"
        )
        await update.message.reply_text(
            await self.translation_manager.translate_for_user(msg_en, chat_id),
            reply_markup=await self.keyboards.build_back_exit_keyboard(chat_id),
        )
        return BUY_AMOUNT

    async def buy_amount(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.effective_chat.id
        txt = update.message.text.strip()
        if not txt.isdigit() or int(txt) <= 0:
            await update.message.reply_text(
                await self.translation_manager.translate_for_user("Please send a valid number.", chat_id)
            )
            return BUY_AMOUNT

        context.user_data["buy_amount"] = int(txt)
        await update.message.reply_text(
            await self.translation_manager.translate_for_user(
                "At what price (USD) per token are you willing to buy?", chat_id
            )
        )
        return BUY_PRICE

    async def buy_price(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.effective_chat.id
        txt = update.message.text.strip()
        try:
            price_per_token = float(txt)
            if price_per_token <= 0:
                raise ValueError
        except ValueError:
            await update.message.reply_text(
                await self.translation_manager.translate_for_user("Please send a valid price.", chat_id)
            )
            return BUY_PRICE

        amount = context.user_data.get("buy_amount", 0)
        identifier = await self._get_user_identifier(chat_id)

        # Send to trade channel
        text_channel = (
            f"🚨 BUY Request\n"
            f"ID: {identifier}\n"
            f"Amount: {amount} tokens\n"
            f"Price: ${price_per_token:.4f} per token\n\n"
            "Contact support to proceed:"
        )
        await update.get_bot().send_message(
            chat_id=TRADE_CHANNEL_ID,
            text=text_channel,
            reply_markup=self._support_inline_keyboard(),
        )

        await update.message.reply_text(
            await self.translation_manager.translate_for_user(
                "Your buy request has been submitted to support.", chat_id
            ),
            reply_markup=await self.keyboards.build_back_exit_keyboard(chat_id),
        )
        return ConversationHandler.END

    # ───────────────────────────────────────── cancel / fallback ───────────

    async def cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.effective_chat.id
        await update.message.reply_text(
            await self.translation_manager.translate_for_user("Operation cancelled.", chat_id),
            reply_markup=await self.keyboards.build_main_menu_keyboard_v2(chat_id),
        )
        return ConversationHandler.END

    # ───────────────────────────────────────── registration helper ─────────

    def get_conversation_handler(self) -> ConversationHandler:
        """Return a fully wired ConversationHandler to add to application."""

        return ConversationHandler(
            entry_points=[
                MessageHandler(filters.Regex(r"^💸 Sell$"), self.sell_start),
                MessageHandler(filters.Regex(r"^🛒 Buy$"), self.buy_start),
            ],
            states={
                SELL_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.sell_amount)],
                BUY_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.buy_amount)],
                BUY_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.buy_price)],
            },
            fallbacks=[MessageHandler(filters.Regex(r"^(⬅️ Back|➡️ Exit)$"), self.cancel)],
            allow_reentry=True,
        )
