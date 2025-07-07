

# token_price_handler.py
#──────────────────────────────────────────────────────────────────────────
from __future__ import annotations

import logging
from decimal import Decimal

from telegram import Update
from telegram.ext import ContextTypes

from core.price_provider import DynamicPriceProvider
from bot_ui.language_Manager import TranslationManager
from bot_ui.keyboards import TranslatedKeyboards
from error_handler import ErrorHandler
from state_manager import push_state


class TokenPriceHandler:
    """
    نمایش قیمت لحظه‌ای توکن
    ─────────────────────────────────────────────────────────
    • ورودی: «📊 Token Price» در منوی اصلی (Message) یا CallbackQuery «Back»
    • خروجی: پیام حاوی قیمت و کیبورد «Back / Exit»
    """

    def __init__(
        self,
        price_provider: DynamicPriceProvider,
        keyboards: TranslatedKeyboards,
        translation_manager: TranslationManager,
        error_handler: ErrorHandler,
    ) -> None:
        self.price_provider = price_provider
        self.keyboards = keyboards
        self.translation_manager = translation_manager
        self.error_handler = error_handler
        self.logger = logging.getLogger(self.__class__.__name__)

    #───────────────────────────── PUBLIC ──────────────────────────────
    async def show_price(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """
        محاسبهٔ قیمت و ارسال / ویرایش پیام خروجی.
        تشخیص می‌دهد آپدیتِ دریافتی Message است یا CallbackQuery.
        """
        # نوع Update و تابع ارسال مناسب
        if update.callback_query:
            query = update.callback_query
            await query.answer()
            chat_id = query.message.chat_id
            send_func = query.edit_message_text
        else:
            chat_id = update.effective_chat.id
            send_func = update.message.reply_text

        # ثبت state (برای back_handler)
        push_state(context, "showing_token_price")

        try:
            # ➊ دریافت قیمت
            price: Decimal = await self.price_provider.get_price()

            # ➋ پیام پایه به انگلیسی
            msg_en = (
                "💲 <b>Live Token Price (Updated):</b>\n\n"
                f"<code>${price:.6f}</code>\n\n"
                "This reflects the most recent market value."
            )

            # ➌ ترجمهٔ نهایی با توجه به زبان کاربر
            msg_final = await self.translation_manager.translate_for_user(
                msg_en, chat_id
            )

            # ➍ ارسال / ویرایش پیام
            await send_func(
                msg_final,
                parse_mode="HTML",
                reply_markup=await self.keyboards.build_back_exit_keyboard(chat_id),
            )
            self.logger.info("Token price sent to %s: %s", chat_id, price)

        except Exception as exc:
            # تمام خطاها به ErrorHandler مرکزی
            await self.error_handler.handle(
                update, context, exc, context_name="token_price"
            )

