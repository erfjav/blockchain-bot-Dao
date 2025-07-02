

from __future__ import annotations
"""
TokenPriceHandler – پاسخ‌دهی به دکمهٔ «📊 Token Price»
----------------------------------------------------
• وابسته به PriceProvider برای دریافت قیمت توکن
• ترجمهٔ پیام با TranslationManager
• دکمه‌های Back / Exit با TranslatedKeyboards
"""

import logging
from telegram import Update
from telegram.ext import ContextTypes

from price_provider import PriceProvider
from language_Manager import TranslationManager
from keyboards import TranslatedKeyboards
from error_handler import ErrorHandler
from state_manager import push_state

logger = logging.getLogger(__name__)


class TokenPriceHandler:
    def __init__(
        self,
        price_provider: PriceProvider,
        keyboards: TranslatedKeyboards,
        translation_manager: TranslationManager,
        error_handler: ErrorHandler,
    ) -> None:
        self.price_provider = price_provider
        self.keyboards = keyboards
        self.translation_manager= translation_manager
        self.error_handler = error_handler
        self.logger = logging.getLogger(self.__class__.__name__)

    async def show_price(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Send current token price to the user."""
        
                # ───➤ ست‌کردن state برای نمایش قیمت توکن
        push_state(context, "showing_token_price")
        context.user_data['state'] = "showing_token_price"
        
        chat_id = update.effective_chat.id
        try:
            price = await self.price_provider.get_price()
            msg_en = f"Current token price: ${price:.4f}"
            await update.message.reply_text(
                await self.translation_manager.translate_for_user(msg_en, chat_id),
                reply_markup=await self.keyboards.build_back_exit_keyboard(chat_id),
            )
        except Exception as e:
            await self.error_handler.handle(update, context, e, context_name="show_price")
