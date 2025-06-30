

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
from price_provider import PriceProvider          # ← NEW

from myproject_database import Database  # Async wrapper
from state_manager import push_state, pop_state

TRADE_CHANNEL_ID = int(os.getenv("TRADE_CHANNEL_ID", "0"))
SUPPORT_USER_USERNAME = os.getenv("SUPPORT_USER_USERNAME", "YourSupportUser")

# Conversation states
SELL_AMOUNT, SELL_PRICE , BUY_AMOUNT, BUY_PRICE = range(4)

logger = logging.getLogger(__name__)


class TradeHandler:
    """Registers handlers for the 💰 Trade flow."""

    def __init__(
        self,
        db: Database,        
        keyboards: TranslatedKeyboards,
        translation_manager: TranslationManager,
        price_provider: PriceProvider,
        referral_manager: ReferralManager,
        error_handler: ErrorHandler,
        
    ) -> None:
        
        self.db = db
        self.keyboards = keyboards
        self.translation_manager = translation_manager
        self.price_provider = price_provider
        self.referral_manager = referral_manager
        self.error_handler = error_handler
        
        self.logger = logging.getLogger(self.__class__.__name__)

    # ─────────────────── helper utilities ────────────────────────────────────────────────────────

    async def _get_user_identifier(self, user_id: int) -> str:
        """Return member_no if available else referral_code as display ID."""
        profile = await self.db.get_profile(user_id)
        if not profile:
            return str(user_id)
        return str(profile.get("member_no") or profile.get("referral_code") or user_id)
    
    #---------------------------------------------------------------------
    def _support_inline_keyboard(self) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            [[InlineKeyboardButton("🆘 Support", url=f"https://t.me/{SUPPORT_USER_USERNAME}")]]
        )

    # ────────────────────────── entry points ─────────────────────────────────────────────────────────────
    async def trade_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        نمایش منوی معامله (خرید/فروش)
        • کاربر را وارد بخش Trading می‌کند
        • توضیح مختصر دربارهٔ امکانات این بخش
        • نمایش دکمه‌های Buy و Sell
        """
        try:
            # ───➤ ست‌کردن state برای نمایش منوی Trade
            push_state(context, "trade_menu")
            context.user_data['state'] = "trade_menu"

            chat_id = update.effective_chat.id
            kb: ReplyKeyboardMarkup = await self.keyboards.build_trade_menu_keyboard(chat_id)

            # ───➤ متن خوش‌آمدگویی و راهنمایی
            msg_en = (
                "<b>🪙 Welcome to the Trade Menu!</b>\n\n"
                "You are now in the <b>Trading Section</b> of the bot. Here you can:\n"
                "• <b>🛒 Buy</b> tokens at the current market price\n"
                "• <b>💸 Sell</b> tokens from your balance\n\n"
                "Please tap one of the buttons below to proceed with your trade."
            )

            await update.message.reply_text(
                await self.translation_manager.translate_for_user(msg_en, chat_id),
                parse_mode="HTML",
                reply_markup=kb,
            )

            return

        except Exception as e:
            # در صورت بروز خطا، به ErrorHandler ارجاع بده
            await self.error_handler.handle( update, context, e, context_name="trade_menu")

    # ───────────────────── SELL FLOW ─────────────────────────────────────────────────
    async def sell_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        شروع فرایند فروش ـ مرحلهٔ گرفتن مقدار
        """
        try:
            push_state(context, "awaiting_sell_amount")
            context.user_data["state"] = "awaiting_sell_amount"

            chat_id   = update.effective_chat.id
            balance   = await self.db.get_user_balance(chat_id)      # باید موجود باشد
            price_now = await self.price_provider.get_price()

            msg_en = (
                f"Current token price: ${price_now:.4f}\n"
                f"Your balance: {balance} tokens\n\n"
                "How many tokens do you want to sell?"
            )
            await update.message.reply_text(
                await self.translation_manager.translate_for_user(msg_en, chat_id),
                reply_markup=await self.keyboards.build_back_exit_keyboard(chat_id),
            )
        except Exception as e:
            await self.error_handler.handle(update, context, e, context_name="sell_start")

    #--------------------------------------------------------------------------
    async def sell_amount(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            chat_id = update.effective_chat.id
            txt     = update.message.text.strip()

            if not txt.isdigit() or int(txt) <= 0:
                await update.message.reply_text(
                    await self.translation_manager.translate_for_user("Please send a valid number.", chat_id)
                )
                return  # در همان state می‌مانیم

            # مقدار را ذخیره می‌کنیم و state بعدی را ست می‌کنیم
            context.user_data["sell_amount"] = int(txt)
            pop_state(context)                      # خارج از awaiting_sell_amount
            push_state(context, SELL_PRICE)
            context.user_data["state"] = SELL_PRICE

            await update.message.reply_text(
                await self.translation_manager.translate_for_user(
                    "At what price (USD) per token are you willing to sell?", chat_id
                ),
                reply_markup=await self.keyboards.build_back_exit_keyboard(chat_id),
            )

        except Exception as e:
            await self.error_handler.handle(update, context, e, context_name="sell_amount")
            
    #-------------------------------------------------------------------------
    async def sell_price(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            chat_id = update.effective_chat.id
            txt     = update.message.text.strip()

            try:
                price_per_token = float(txt)
                if price_per_token <= 0:
                    raise ValueError
            except ValueError:
                await update.message.reply_text(
                    await self.translation_manager.translate_for_user("Please send a valid price.", chat_id)
                )
                return  # در همان state می‌مانیم

            amount     = context.user_data.get("sell_amount", 0)
            identifier = await self._get_user_identifier(chat_id)

            text_channel = (
                f"🚨 SELL Request\n"
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
                    "Your sell request has been submitted to support.", chat_id
                ),
                reply_markup=await self.keyboards.build_back_exit_keyboard(chat_id),
            )

            # پاک‌سازی state و داده‌ها
            pop_state(context)
            context.user_data.clear()

        except Exception as e:
            await self.error_handler.handle(update, context, e, context_name="sell_price")

    # ─────────────────────────── BUY FLOW ─────────────────────────────────
    async def buy_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    
                # ───➤ ست‌کردن state برای انتظار مقدار خرید
        push_state(context, "awaiting_buy_amount")
        context.user_data['state'] = "awaiting_buy_amount"
        
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
    
    # trade_handler.py  – فقط بخش‌های مهم
    #------------------------------------------------------------------------------------------------------
    async def buy_amount(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.effective_chat.id
        txt = update.message.text.strip()

        if not txt.isdigit() or int(txt) <= 0:
            await update.message.reply_text(
                await self.translation_manager.translate_for_user("Please send a valid number.", chat_id)
            )
            return  # همین state می‌ماند

        context.user_data["buy_amount"] = int(txt)
        await update.message.reply_text(
            await self.translation_manager.translate_for_user(
                "At what price (USD) per token are you willing to buy?", chat_id
            )
        )
        # فقط state را به‌روز کنید؛ نیازی به return مقدار خاص نیست
        context.user_data['state'] = 'awaiting_buy_price'
        push_state(context, 'awaiting_buy_price')

    #------------------------------------------------------------------------------------------------------
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
            return  # همان state می‌ماند

        amount = context.user_data.get("buy_amount", 0)
        identifier = await self._get_user_identifier(chat_id)

        # ارسال به کانال ترید
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

        # تأیید برای کاربر
        await update.message.reply_text(
            await self.translation_manager.translate_for_user(
                "Your buy request has been submitted to support.", chat_id
            ),
            reply_markup=await self.keyboards.build_back_exit_keyboard(chat_id),
        )

        # پاک‌سازی state
        context.user_data.clear()
        pop_state(context)
    
    
    
##############################################################################################################
    
    # #-------------------------------------------------------------------------------------------------
    # async def buy_amount(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        
    #     chat_id = update.effective_chat.id
    #     txt = update.message.text.strip()
        
    #     if not txt.isdigit() or int(txt) <= 0:
    #         # اگر عدد نامعتبر بود، همان state را نگه دار
    #         push_state(context, "awaiting_buy_amount")
    #         context.user_data['state'] = "awaiting_buy_amount"
            
    #         await update.message.reply_text(
    #             await self.translation_manager.translate_for_user("Please send a valid number.", chat_id)
    #         )
    #         return BUY_AMOUNT

    #     context.user_data["buy_amount"] = int(txt)
    #     await update.message.reply_text(
    #         await self.translation_manager.translate_for_user(
    #             "At what price (USD) per token are you willing to buy?", chat_id
    #         )
    #     )
    #     return BUY_PRICE
    
    # #-------------------------------------------------------------------------------------------------
    # async def buy_price(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        
    #     chat_id = update.effective_chat.id
    #     txt = update.message.text.strip()
    #     try:
    #         price_per_token = float(txt)
    #         if price_per_token <= 0:
    #             raise ValueError
            
    #     except ValueError:
    #         # اگر قیمت نامعتبر بود، همان state را ست کن
    #         push_state(context, "awaiting_buy_price")
    #         context.user_data['state'] = "awaiting_buy_price"
            
    #         await update.message.reply_text(
    #             await self.translation_manager.translate_for_user("Please send a valid price.", chat_id)
    #         )
    #         return BUY_PRICE

    #     amount = context.user_data.get("buy_amount", 0)
    #     identifier = await self._get_user_identifier(chat_id)

    #     # Send to trade channel
    #     text_channel = (
    #         f"🚨 BUY Request\n"
    #         f"ID: {identifier}\n"
    #         f"Amount: {amount} tokens\n"
    #         f"Price: ${price_per_token:.4f} per token\n\n"
    #         "Contact support to proceed:"
    #     )
    #     await update.get_bot().send_message(
    #         chat_id=TRADE_CHANNEL_ID,
    #         text=text_channel,
    #         reply_markup=self._support_inline_keyboard(),
    #     )

    #     await update.message.reply_text(
    #         await self.translation_manager.translate_for_user(
    #             "Your buy request has been submitted to support.", chat_id
    #         ),
    #         reply_markup=await self.keyboards.build_back_exit_keyboard(chat_id),
    #     )
    #     return ConversationHandler.END



    # async def sell_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        
        
    #             # ───➤ ست‌کردن state برای انتظار مقدار فروش
    #     push_state(context, "awaiting_sell_amount")
    #     context.user_data['state'] = "awaiting_sell_amount"
        
    #     chat_id = update.effective_chat.id
    #     balance = await self.db.get_user_balance(chat_id)  # ← implement in Database
    #     price = await self.price_provider.get_price()

    #     msg_en = (
    #         f"Current token price: ${price:.4f}\n"
    #         f"Your balance: {balance} tokens\n\n"
    #         "How many tokens do you want to sell?"
    #     )
    #     await update.message.reply_text(
    #         await self.translation_manager.translate_for_user(msg_en, chat_id),
    #         reply_markup=await self.keyboards.build_back_exit_keyboard(chat_id),
    #     )
    #     return SELL_AMOUNT
    
    
        
    # async def sell_amount(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    #     chat_id = update.effective_chat.id
    #     txt = update.message.text.strip()
    #     if not txt.isdigit() or int(txt) <= 0:

    #         push_state(context, "awaiting_sell_amount")
    #         context.user_data['state'] = "awaiting_sell_amount"            
            
    #         await update.message.reply_text(
    #             await self.translation_manager.translate_for_user("Please send a valid number.", chat_id)
    #         )
    #         return SELL_AMOUNT

    #     amount = int(txt)
    #     identifier = await self._get_user_identifier(chat_id)

    #     # Send to trade channel
    #     text_channel = (
    #         f"🚨 SELL Request\n"
    #         f"ID: {identifier}\n"
    #         f"Amount: {amount} tokens\n\n"
    #         "Contact support to proceed:"
    #     )
    #     await update.get_bot().send_message(
    #         chat_id=TRADE_CHANNEL_ID,
    #         text=text_channel,
    #         reply_markup=self._support_inline_keyboard(),
    #     )

    #     # Acknowledge user
    #     await update.message.reply_text(
    #         await self.translation_manager.translate_for_user(
    #             "Your sell request has been submitted to support.", chat_id
    #         ),
    #         reply_markup=await self.keyboards.build_back_exit_keyboard(chat_id),
    #     )
    #     return ConversationHandler.END