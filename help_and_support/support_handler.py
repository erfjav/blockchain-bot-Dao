

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

from bot_ui.language_Manager import TranslationManager
from bot_ui.keyboards import TranslatedKeyboards
from error_handler import ErrorHandler
from state_manager import push_state

logger = logging.getLogger(__name__)


class SupportHandler:
    def __init__(
        self,
        keyboards: TranslatedKeyboards,
        translation_manager: TranslationManager,
        error_handler: ErrorHandler,
    ) -> None:
        self.keyboards = keyboards
        self.translation_manager = translation_manager
        self.error_handler = error_handler
        self.support_username = os.getenv("SUPPORT_USER_USERNAME", "YourSupportUser")
        self.logger = logging.getLogger(self.__class__.__name__)

    async def show_support_info(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        # ───➤ ست‌کردن state برای بخش Support
        push_state(context, "support_menu")
        context.user_data['state'] = "support_menu"

        chat_id = update.effective_chat.id
        try:
            msg_en = (
                "🎧 <b>Need help?</b>\n\n"
                "For any questions about payments, tokens, or technical issues, "
                "message our support team at @" + self.support_username + "."
            )
            
            translated_msg = await self.translation_manager.translate_for_user(msg_en, chat_id)
            # استفاده از کیبورد Back/Exit
            reply_kb = await self.keyboards.build_back_exit_keyboard(chat_id)

            await update.message.reply_text(
                translated_msg,
                parse_mode="HTML",
                reply_markup=reply_kb,
            )
        except Exception as e:
            await self.error_handler.handle(update, context, e, context_name="show_support_info")


