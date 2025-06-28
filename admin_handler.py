

from telegram.ext import CommandHandler
from telegram import Update
from telegram.ext import ContextTypes
from price_provider import PriceProvider
from language_Manager import TranslationManager
from config import ADMIN_USER_IDS

class AdminHandler:
    def __init__(self, price_provider:PriceProvider, translation_manager: TranslationManager):
        self.price_provider = price_provider
        self.translation_manager = translation_manager
        self.admin_ids = ADMIN_USER_IDS

    async def set_price_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.effective_chat.id
        if chat_id not in self.admin_ids:
            return

        if not context.args:
            await update.message.reply_text("Usage: /set_price 1.75")
            return
        try:
            new_price = float(context.args[0])
            await self.price_provider.set_price(new_price)
            await update.message.reply_text(f"✅ Price set to ${new_price:.4f}")
        except ValueError:
            await update.message.reply_text("Send a valid positive number.")
