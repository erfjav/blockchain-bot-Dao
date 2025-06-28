

from __future__ import annotations
"""
payment_handler.py – هندلر «💳 Payment»
--------------------------------------
• پیام ثابت برای واریز 50 دلار به کیف پول پروژه
• ترجمهٔ متن با TranslationManager
• دکمه‌های Back / Exit برای بازگشت به منو

متغیرهای محیطی (اختیاری):
    PAYMENT_WALLET_ADDRESS   آدرس ولت (TRX / USDT / ETH …)
"""

import os
import logging
from telegram import Update
from telegram.ext import ContextTypes

from language_Manager import TranslationManager
from keyboards import TranslatedKeyboards
from error_handler import ErrorHandler

from config import PAYMENT_WALLET_ADDRESS

logger = logging.getLogger(__name__)


class PaymentHandler:
    PLACEHOLDER_ADDRESS = "TXXYYZZ_PLACEHOLDER_ADDRESS"

    def __init__(
        self,
        keyboards: TranslatedKeyboards,
        translation_manager: TranslationManager,
        error_handler: ErrorHandler,
    ) -> None:
        self.keyboards = keyboards
        self.t = translation_manager
        self.eh = error_handler
        self.wallet_address = PAYMENT_WALLET_ADDRESS
        self.logger = logging.getLogger(self.__class__.__name__)

    async def show_payment_instructions(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.effective_chat.id
        try:
            msg_en = (
                "💳 <b>Payment Instructions</b>\n\n"
                "1️⃣ Copy the wallet address below.\n"
                "2️⃣ Send <b>$50</b> in USDT (TRC-20) to this address.\n"
                "3️⃣ After confirmation, send TxID to support for activation.\n\n"
                f"<code>{self.wallet_address}</code>"
            )
            await update.message.reply_text(
                await self.t.translate_for_user(msg_en, chat_id),
                parse_mode="HTML",
                reply_markup=await self.keyboards.build_back_exit_keyboard(chat_id),
            )
        except Exception as e:
            await self.eh.handle(update, context, e, context_name="show_payment_instructions")
