
# withdraw_handler.py
from __future__ import annotations

import logging
from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from language_Manager import TranslationManager
from keyboards import TranslatedKeyboards
from error_handler import ErrorHandler
from myproject_database import Database
from Referral_logic_code import ReferralManager
from state_manager import push_state, pop_state


# ───── پیکربندی ثابت‌ها ────────────────────────────────────────────
WITHDRAW_AMOUNT_USD   = 50               # مبلغ ثابت عضویت
REQUIRED_REFERRALS    = 2                # حداقل زیرمجموعهٔ مستقیم
PROCESSING_NOTE       = (
    "⏳ Your withdrawal request has been submitted.\n\n"
    "Funds will be transferred to your registered wallet shortly."
)

logger = logging.getLogger(__name__)


class WithdrawHandler:
    """
    منطق کامل برداشت حق عضویت:
      • بررسی شرایط (پرداخت اولیه + ≥۲ زیرمجموعه)
      • ثبت درخواست برداشت
      • پاک‌سازی زیرمجموعه و تغییر وضعیت عضویت
    """

    def __init__(
        self,
        db: Database,
        referral_manager: ReferralManager,
        keyboards: TranslatedKeyboards,
        translation_manager: TranslationManager,
        error_handler: ErrorHandler,
        # blockchain (اختیاری – اگر تسویه خودکار دارید)
        # blockchain_client: BlockchainClient | None = None,
    ) -> None:
        self.db = db
        self.referral_manager = referral_manager
        self.keyboards = keyboards
        self.translation_manager = translation_manager
        self.error_handler = error_handler
        # self.blockchain = blockchain_client
        self.logger = logging.getLogger(self.__class__.__name__)

    # ───────────────────────────────── Telegram entry-point ───────────────────
    async def show_withdraw_menu(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """
        نمایش صفحهٔ برداشت:
          • اگر واجد شرایط نیست → پیام خطا
          • اگر واجد شرایط است → دکمهٔ «Confirm Withdraw»
        """
        chat_id = update.effective_chat.id
        try:
            profile = await self.db.get_profile(chat_id)
            downline_cnt = await self.db.get_downline_count(chat_id)
            wallet = await self.db.get_wallet_address(chat_id)

            # ── ۱) شرط عضویت پرداخت‌شده
            if not (profile and profile.get("joined")):
                text = (
                    "❌ <b>You have not paid the membership fee yet.</b>\n"
                    "Please complete your $50 payment first."
                )
                await self._reply(update, context, text, chat_id)
                return

            # ── ۲) داشتن حداقل ۲ زیرمجموعه
            if downline_cnt < REQUIRED_REFERRALS:
                needed = REQUIRED_REFERRALS - downline_cnt
                text = (
                    "❌ <b>You are not eligible to withdraw yet.</b>\n"
                    f"You need <b>{needed}</b> more direct referral(s) to unlock withdrawal."
                )
                await self._reply(update, context, text, chat_id)
                return

            # ── ۳) وجود آدرس کیف‌پول
            if not wallet:
                text = (
                    "❌ <b>No wallet address on file.</b>\n"
                    "Please set your wallet address in the Wallet menu first."
                )
                await self._reply(update, context, text, chat_id)
                return

            # ── ۴) نمایش دکمهٔ تأیید برداشت
            push_state(context, "withdraw_menu")
            context.user_data["state"] = "withdraw_menu"

            msg = (
                "💸 <b>Withdraw Eligibility Check Passed!</b>\n\n"
                f"• Amount: <b>${WITHDRAW_AMOUNT_USD} USDT</b>\n"
                f"• Destination: <code>{wallet}</code>\n"
                f"• Direct Referrals: <b>{downline_cnt}</b>\n\n"
                "If you wish to proceed, tap <b>Confirm Withdraw</b> below."
            )

            rows = [
                [InlineKeyboardButton("✔️ Confirm Withdraw", callback_data="withdraw_confirm")],
                [InlineKeyboardButton("⬅️ Back", callback_data="back"),
                 InlineKeyboardButton("Exit ➡️", callback_data="exit")],
            ]
            kb = InlineKeyboardMarkup(rows)

            translated = await self.translation_manager.translate_for_user(msg, chat_id)
            await update.message.reply_text(translated, parse_mode="HTML", reply_markup=kb)

        except Exception as exc:
            await self.error_handler.handle(update, context, exc, "show_withdraw_menu")

    # ─────────────────────────────── تأیید نهایی ───────────────────────────────
    async def confirm_withdraw_callback(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """
        کاربر دکمهٔ «Confirm Withdraw» را می‌زند.
        • درخواست در DB ثبت می‌شود
        • زیرمجموعه‌ها حذف و عضویت به حالت «withdrawn» می‌رود
        • پیام موفقیت و زمان‌بندی پرداخت ارسال می‌شود
        """
        query = update.callback_query
        await query.answer()
        chat_id = query.from_user.id

        try:
            wallet = await self.db.get_wallet_address(chat_id)
            downline_cnt = await self.db.get_downline_count(chat_id)

            # آخرین چک سریع
            if downline_cnt < REQUIRED_REFERRALS:
                text = (
                    "❌ Withdrawal conditions are no longer satisfied.\n"
                    "Please refresh the page and try again."
                )
                await query.edit_message_text(text, parse_mode="HTML")
                return

            # ➊ ثبت درخواست برداشت در DB
            await self.db.create_withdraw_request(
                chat_id,
                wallet,
                WITHDRAW_AMOUNT_USD,
            )

            # ➋ پاک‌سازی زیرمجموعه‌ها + تغییر وضعیت عضویت
            await self.db.clear_downline(chat_id)
            await self.db.mark_membership_withdrawn(chat_id)

            # ➌ (اختیاری) انتقال آنی روی بلاک‌چین
            # tx_id = await self.blockchain.transfer_usdt(wallet, WITHDRAW_AMOUNT_USD)

            # ➍ پیام موفقیت
            translated = await self.translation_manager.translate_for_user(
                f"✅ Withdrawal request registered.\n{PROCESSING_NOTE}", chat_id
            )
            await query.edit_message_text(translated, parse_mode="HTML")

            # ➎ Reply-keyboard Back/Exit
            await context.bot.send_message(
                chat_id,
                text="🏠 Returning to main menu…",
                reply_markup=await self.keyboards.build_main_menu_keyboard_v2(chat_id),
            )

            self.logger.info(f"[withdraw] user {chat_id} requested withdrawal of ${WITHDRAW_AMOUNT_USD}")

        except Exception as exc:
            await self.error_handler.handle(update, context, exc, "confirm_withdraw_callback")

    # ────────────────────────── util: پاسخ با ترجمه ────────────────────────────
    async def _reply(self, update: Update, context: ContextTypes.DEFAULT_TYPE,
                     text: str, chat_id: int) -> None:
        translated = await self.translation_manager.translate_for_user(text, chat_id)
        await update.message.reply_text(
            translated, parse_mode="HTML",
            reply_markup=await self.keyboards.build_back_exit_keyboard(chat_id)
        )

