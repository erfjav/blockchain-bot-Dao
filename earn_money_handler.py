

from __future__ import annotations
"""
EarnMoneyHandler – Placeholder برای «💼 Earn Money»
"""

import logging
from telegram import Update
from telegram.ext import ContextTypes

from bot_ui.language_Manager import TranslationManager
from bot_ui.keyboards import TranslatedKeyboards
from state_manager import push_state

logger = logging.getLogger(__name__)


class EarnMoneyHandler:
    def __init__(
        self,
        keyboards: TranslatedKeyboards,
        translation_manager: TranslationManager,
    ) -> None:
        self.keyboards = keyboards
        self.translation_manager = translation_manager
        self.logger = logging.getLogger(self.__class__.__name__)

    async def coming_soon(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
                # ───➤ ست‌کردن state برای «Earn Money»
        push_state(context, "earn_money_menu")
        context.user_data['state'] = "earn_money_menu"
        
        chat_id = update.effective_chat.id
        msg_en = "🚧 This feature is coming soon."
        await update.message.reply_text(
            await self.translation_manager.translate_for_user(msg_en, chat_id),
            reply_markup=await self.keyboards.build_back_exit_keyboard(chat_id),
        )
