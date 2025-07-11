

from __future__ import annotations
"""
ConvertTokenHandler – Placeholder برای «🔄 Convert Token»
"""

import logging
from telegram import Update
from telegram.ext import ContextTypes

from bot_ui.language_Manager import TranslationManager
from bot_ui.keyboards import TranslatedKeyboards
from state_manager import push_state

logger = logging.getLogger(__name__)


class ConvertTokenHandler:
    def __init__(
        self,
        keyboards: TranslatedKeyboards,
        translation_manager: TranslationManager,
    ) -> None:
        self.keyboards = keyboards
        self.t = translation_manager
        self.logger = logging.getLogger(self.__class__.__name__)

    async def coming_soon(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        
                # ───➤ ست‌کردن state برای «Convert Token»
        push_state(context, "convert_token")
        context.user_data['state'] = "convert_token"
        
        chat_id = update.effective_chat.id
        
        msg_en = "🚧 This feature is coming soon."
        await update.message.reply_text(
            await self.t.translate_for_user(msg_en, chat_id),
            reply_markup=await self.keyboards.build_back_exit_keyboard(chat_id),
        )
