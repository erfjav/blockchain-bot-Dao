




# error_handler.py
import logging
from telegram import Update
from keyboards import TranslatedKeyboards
from language_Manager import TranslationManager


class ErrorHandler:
    def __init__(self, translation_manager: TranslationManager, keyboards: TranslatedKeyboards):
        
        self.logger = logging.getLogger(__name__)
        self.translation_manager = translation_manager
        self.keyboards = keyboards

    async def handle(self, update: Update, context, error: Exception, context_name="operation"):
        # لاگ خطا
        self.logger.error(f"Error during {context_name}: {error}")

        # آماده‌سازی متن پیام
        chat_id = update.effective_chat.id
        msg_en = f"An error occurred during {context_name}."
        msg_final = await self.translation_manager.translate_for_user(msg_en, chat_id)

        # انتخاب درست هدف ارسال پیام
        if getattr(update, "callback_query", None) and update.callback_query.message:
            target = update.callback_query.message
        else:
            target = update.message

        # ارسال پیام به کاربر
        await target.reply_text(
            msg_final,
            reply_markup=await self.keyboards.build_back_exit_keyboard(chat_id)
        )