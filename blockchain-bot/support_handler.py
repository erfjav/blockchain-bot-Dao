

from __future__ import annotations
"""
support_handler.py – هندلر «🎧 Support»
--------------------------------------
• پیام راهنمای تماس با پشتیبانی + لینک تلگرام پشتیبان.
• متن ترجمه شده بر اساس زبان کاربر.

متغیر محیطی:
    SUPPORT_USER_USERNAME (مثلاً AskGenieAI_Support)
"""

import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from language_Manager import TranslationManager
from keyboards import TranslatedKeyboards
from error_handler import ErrorHandler

logger = logging.getLogger(__name__)


class SupportHandler:
    def __init__(
        self,
        keyboards: TranslatedKeyboards,
        translation_manager: TranslationManager,
        error_handler: ErrorHandler,
    ) -> None:
        self.keyboards = keyboards
        self.t = translation_manager
        self.eh = error_handler
        self.support_username = os.getenv("SUPPORT_USER_USERNAME", "YourSupportUser")
        self.logger = logging.getLogger(self.__class__.__name__)

    async def show_support_info(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.effective_chat.id
        try:
            msg_en = (
                "🎧 <b>Need help?</b>\n\n"
                "For any questions about payments, tokens, or technical issues, press the button below or message our support team at @" + self.support_username + "."
            )
            kb = InlineKeyboardMarkup(
                [[InlineKeyboardButton("🆘 Contact Support", url=f"https://t.me/{self.support_username}")]]
            )
            await update.message.reply_text(
                await self.t.translate_for_user(msg_en, chat_id),
                parse_mode="HTML",
                reply_markup=kb,
            )
        except Exception as e:
            await self.eh.handle(update, context, e, context_name="show_support_info")
