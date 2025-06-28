

import logging
from telegram import Update
from telegram.ext import ContextTypes
from error_handler import ErrorHandler
from language_Manager import TranslationManager
from Translated_Inline_Keyboards import TranslatedInlineKeyboards
from keyboards import TranslatedKeyboards
from myproject_database import Database

class HelpHandler:
    """
    A class to handle help messages for the bot, including sending a short help message
    and detailed help for various features with inline buttons.
    """
    def __init__(
        self,
        logger: logging.Logger,
        db: Database,
        keyboards: TranslatedKeyboards,
        translation_manager: TranslationManager,
        inline_translator: TranslatedInlineKeyboards,
        error_handler: ErrorHandler,
    ): 
        self.db = db
        self.logger = logger
        self.inline_translator = inline_translator
        self.translation_manager = translation_manager
        self.keyboards = keyboards
        self.error_handler = error_handler

    async def show_Guide(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            chat_id = update.effective_chat.id

            help_text = (
                "💰 <b>Welcome to your Blockchain Assistant Bot!</b>\n\n"
                "Here’s what you can do with this bot:\n\n"
                "• 📈 <b>Buy and sell crypto</b> securely and fast\n"
                "• 🔄 <b>Convert tokens</b> instantly with real-time rates\n"
                "• 💸 <b>Track token prices</b> live and manage your portfolio\n"
                "• 👥 <b>Earn through referrals</b> and increase your crypto holdings\n"
                "• 🌐 <b>Change language</b> to your native one for full accessibility\n"
                "• 🆘 <b>Need help?</b> Tap any option in the menu or contact support\n\n"
                "Tap any button below to get started!"
            )

            translated_text = await self.translation_manager.translate_for_user(help_text, chat_id)

            await update.message.reply_text(
                translated_text,
                parse_mode="HTML",
                reply_markup=await self.keyboards.build_back_exit_keyboard(chat_id)
            )

        except Exception as e:
            await self.error_handler.handle(update, context, e, context_name="show_help")
