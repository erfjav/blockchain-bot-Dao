


# withdraw_handler.py

from datetime import datetime
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from language_Manager import TranslationManager
from keyboards import TranslatedKeyboards
from myproject_database import Database

MIN_WITHDRAW_USD = 10.0

class WithdrawHandler:
    # def __init__(self, db, keyboards, translation_manager):

    def __init__(
        self,
        db: Database,
        keyboards: TranslatedKeyboards,
        translation_manager: TranslationManager,
        
    ) -> None:
               
        self.db = db
        self.keyboards = keyboards
        self.translation_manager = translation_manager

    # ─────────────────────────────────────────────────────────────
    async def show_withdraw(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        مرحلهٔ ➊: نمایش موجودی و درخواست تأیید برداشت.
        """
        chat_id = update.effective_chat.id
        balance = await self.db.get_fiat_balance(chat_id)

        msg_en = (
            f"Your withdrawable balance: <b>${balance:.2f}</b>\n\n"
            "Press <b>Confirm Withdraw</b> to request payout."
        )
        kb = InlineKeyboardMarkup(
            [[InlineKeyboardButton("🆗 Confirm Withdraw", callback_data="withdraw_confirm")]]
        )
        await update.message.reply_text(
            await self.translation_manager.translate_for_user(msg_en, chat_id),
            reply_markup=kb,
            parse_mode="HTML",
        )
        context.user_data["state"] = "awaiting_withdraw_confirm"

    # ─────────────────────────────────────────────────────────────
    async def confirm_withdraw_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        مرحلهٔ ➋: ثبت در صف برداشت.
        """
        query = update.callback_query
        await query.answer()
        chat_id = query.from_user.id

        balance = await self.db.get_fiat_balance(chat_id)
        if balance < MIN_WITHDRAW_USD:
            return await query.answer("Balance too low for withdrawal.", show_alert=True)

        address = await self.db.get_withdraw_address(chat_id)
        if not address:
            return await query.answer("Set your withdraw address first.", show_alert=True)

        wid = await self.db.create_withdraw_request(chat_id, balance, address)
        await self.db.set_fiat_balance(chat_id, 0)   # صفر کردن موجودی

        await query.edit_message_text(
            f"✅ Withdrawal request #{wid} submitted.\n"
            "We will process it within 24 hours."
        )
        context.user_data.clear()
