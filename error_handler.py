

import logging
from telegram import Update
from telegram.error import BadRequest, Forbidden
from telegram.ext import ContextTypes

from keyboards import TranslatedKeyboards
from language_Manager import TranslationManager


class ErrorHandler:
    """
    Generic error-handler that logs the traceback and sends
    a short, user-friendly message in the user's language.
    """

    def __init__(
        self,
        translation_manager: TranslationManager,
        keyboards: TranslatedKeyboards,
    ):
        self.logger = logging.getLogger(__name__)
        self.translation_manager = translation_manager
        self.keyboards = keyboards

    # ──────────────────────────────────────────────────────────────
    async def handle(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        exc: Exception,
        context_name: str = "operation",
    ):
        # 1) log full traceback
        self.logger.error(f"[{context_name}] {exc!r}", exc_info=True)

        # 2) answer callback_query (prevents “Query is too old …”)
        if getattr(update, "callback_query", None):
            try:
                await update.callback_query.answer()
            except Exception:
                pass  # ignore if already answered / expired

        # 3) pick the safest chat to send an error message
        chat_id: int | None = None
        if update.effective_user:                       # private user available
            chat_id = update.effective_user.id
        elif (
            update.effective_chat
            and update.effective_chat.type == "private"
        ):
            chat_id = update.effective_chat.id

        if not chat_id:
            return  # nowhere safe to send a message

        # 4) build translated error string
        msg_en = f"⚠️ An error occurred during {context_name}."
        msg_final = await self.translation_manager.translate_for_user(
            msg_en, chat_id
        )

        # 5) send via bot.send_message → avoids “Inline keyboard expected”
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text=msg_final,
                reply_markup=await self.keyboards.build_back_exit_keyboard(
                    chat_id
                ),
            )
        except (BadRequest, Forbidden):
            # user blocked the bot or markup unsupported – silently ignore
            pass



# # error_handler.py
# import logging
# from telegram import Update
# from keyboards import TranslatedKeyboards
# from language_Manager import TranslationManager


# class ErrorHandler:
#     def __init__(self, translation_manager: TranslationManager, keyboards: TranslatedKeyboards):
        
#         self.logger = logging.getLogger(__name__)
#         self.translation_manager = translation_manager
#         self.keyboards = keyboards

#     async def handle(self, update: Update, context, error: Exception, context_name="operation"):
#         # لاگ خطا
#         self.logger.error(f"Error during {context_name}: {error}")

#         # آماده‌سازی متن پیام
#         chat_id = update.effective_chat.id
#         msg_en = f"An error occurred during {context_name}."
#         msg_final = await self.translation_manager.translate_for_user(msg_en, chat_id)

#         # انتخاب درست هدف ارسال پیام
#         if getattr(update, "callback_query", None) and update.callback_query.message:
#             target = update.callback_query.message
#         else:
#             target = update.message

#         # ارسال پیام به کاربر
#         await target.reply_text(
#             msg_final,
#             reply_markup=await self.keyboards.build_back_exit_keyboard(chat_id)
#         )