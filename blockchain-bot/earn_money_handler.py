

from __future__ import annotations
"""
EarnMoneyHandler – Placeholder برای «💼 Earn Money»
"""

import logging
from telegram import Update
from telegram.ext import ContextTypes

from language_Manager import TranslationManager
from keyboards import TranslatedKeyboards

logger = logging.getLogger(__name__)


class EarnMoneyHandler:
    def __init__(
        self,
        keyboards: TranslatedKeyboards,
        translation_manager: TranslationManager,
    ) -> None:
        self.keyboards = keyboards
        self.t = translation_manager
        self.logger = logging.getLogger(self.__class__.__name__)

    async def coming_soon(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.effective_chat.id
        msg_en = "🚧 This feature is coming soon."
        await update.message.reply_text(
            await self.t.translate_for_user(msg_en, chat_id),
            reply_markup=await self.keyboards.build_back_exit_keyboard(chat_id),
        )
