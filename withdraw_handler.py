
# withdraw_handler.py
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from bot_ui.language_Manager import TranslationManager
from bot_ui.keyboards import TranslatedKeyboards
from bot_ui.Translated_Inline_Keyboards import TranslatedInlineKeyboards
from error_handler import ErrorHandler
from myproject_database import Database
from Referral_logic_code import ReferralManager
from core.blockchain_client import BlockchainClient
from state_manager import push_state, pop_state

import config

# ───── پیکربندی ثابت‌ها ────────────────────────────────────────────

WALLET_SPLIT_70      = config.WALLET_SPLIT_70.lower()
SPLIT_WALLET_A_PRIV = config.SPLIT_WALLET_A_PRIV

WITHDRAW_AMOUNT_USD   = 50               # مبلغ ثابت عضویت
REQUIRED_REFERRALS    = 2                # حداقل زیرمجموعهٔ مستقیم
WITHDRAW_INTERVAL_DAYS = 30              # فاصلهٔ مجاز بین دو برداشت (روز)

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
        inline_translator: TranslatedInlineKeyboards,
        translation_manager: TranslationManager,
        error_handler: ErrorHandler,
        # blockchain (اختیاری – اگر تسویه خودکار دارید)
        blockchain_client: BlockchainClient | None = None,
    ) -> None:
        self.db = db
        self.referral_manager = referral_manager
        self.keyboards = keyboards
        self.translation_manager = translation_manager
        self.inline_translator = inline_translator
        self.error_handler = error_handler
        self.blockchain = blockchain_client
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


            # ۳) فاصلهٔ ۳۰ روز بین برداشت‌ها
            last_req = await self.db.get_last_withdraw_request(chat_id)
            if last_req and last_req.get("created_at"):
                last_date = last_req["created_at"]
                delta = datetime.utcnow() - last_date
                if delta < timedelta(days=WITHDRAW_INTERVAL_DAYS):
                    days_left = WITHDRAW_INTERVAL_DAYS - delta.days
                    next_date = (last_date + timedelta(days=WITHDRAW_INTERVAL_DAYS)).strftime("%Y-%m-%d")
                    text = (
                        "❌ <b>Withdrawal not available yet.</b>\n"
                        f"Your last withdrawal was on <b>{last_date.strftime('%Y-%m-%d')}</b>.\n"
                        f"Next withdrawal available in <b>{days_left} day(s)</b> (on {next_date})."
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
            
            # kb = InlineKeyboardMarkup(rows)

            kb = await self.inline_translator.build_inline_keyboard_for_user(rows, chat_id)

            translated = await self.translation_manager.translate_for_user(msg, chat_id)
            await update.message.reply_text(translated, parse_mode="HTML", reply_markup=kb)

        except Exception as exc:
            await self.error_handler.handle(update, context, exc, "show_withdraw_menu")


    # ──────────────────────────────────────────────────────────────────
    async def confirm_withdraw_callback(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """
        هنگامی که کاربر «✔️ Confirm Withdraw» می‌زند:
        1) شرایط دوباره چک می‌شود
        2) درخواست در DB ثبت می‌گردد
        3) ۵۰ USDT از کیف‌پول A به آدرس کاربر ارسال می‌شود
        4) txid در DB ذخیره و پیام موفقیت به کاربر نمایش داده می‌شود
        """
        query = update.callback_query
        await query.answer()
        chat_id = query.from_user.id

        try:
            # ─── اطلاعات کاربر
            wallet       = await self.db.get_wallet_address(chat_id)
            downline_cnt = await self.db.get_downline_count(chat_id)

            # ─── شرایط برداشت
            if downline_cnt < REQUIRED_REFERRALS or not wallet:
                text = (
                    "❌ Withdrawal conditions are no longer satisfied.\n"
                    "Please refresh the page and try again."
                )
                await query.edit_message_text(text, parse_mode="HTML")
                return


            # ➋′ تکرار چک فاصلهٔ ۳۰ روز (defensive re-check)
            last_req = await self.db.get_last_withdraw_request(chat_id)
            if last_req and last_req.get("created_at"):
                last_date = last_req["created_at"]
                if datetime.utcnow() - last_date < timedelta(days=WITHDRAW_INTERVAL_DAYS):
                    days_left = WITHDRAW_INTERVAL_DAYS - (datetime.utcnow() - last_date).days
                    await query.edit_message_text(
                        "❌ Withdrawal not available yet.\n"
                        f"Next withdrawal in <b>{days_left}</b> day(s).",
                        parse_mode="HTML"
                    )
                    return


            # ➊ ثبت درخواست در DB (status=pending)
            await self.db.create_withdraw_request(chat_id, wallet, WITHDRAW_AMOUNT_USD)

            # ➋ پاک‌سازی زیرمجموعه‌ها و وضعیت
            await self.db.clear_downline(chat_id)
            await self.db.mark_membership_withdrawn(chat_id)

            # ➌ انتقال آنی روی بلاک‌چین (از SPLIT_WALLET_A)
            tx_id: str = await self.blockchain.transfer_trc20(
                from_private_key=SPLIT_WALLET_A_PRIV,
                to_address=wallet,
                amount=WITHDRAW_AMOUNT_USD,
                memo=f"withdraw-{chat_id}",
            )

            # ➍ ثبت txid و تغییر وضعیت در DB
            await self.db.mark_withdraw_paid(chat_id, tx_id)

            # ➎ پیام موفقیت به کاربر
            success_msg = (
                f"✅ Withdrawal successful!\n\n"
                f"• Amount: <b>{WITHDRAW_AMOUNT_USD:.2f} USDT</b>\n"
                f"• TxID: <code>{tx_id}</code>\n\n"
                "Funds will appear after network confirmations."
            )
            translated = await self.translation_manager.translate_for_user(success_msg, chat_id)
            await query.edit_message_text(translated, parse_mode="HTML")

            # ➏ برگشت به منوی اصلی
            await context.bot.send_message(
                chat_id,
                text="🏠 Returning to main menu…",
                reply_markup=await self.keyboards.build_main_menu_keyboard_v2(chat_id),
            )

            self.logger.info(f"[withdraw] {chat_id} paid out {WITHDRAW_AMOUNT_USD} USDT (txid={tx_id})")

        except Exception as exc:
            # در صورت خطا، وضعیت را failed کنید تا مدیر بتواند دستی بررسی کند
            await self.db.mark_withdraw_failed(chat_id, str(exc))
            self.logger.error(f"withdraw error: {exc}", exc_info=True)

            error_text = (
                "🚫 <b>Automatic payout failed.</b>\n"
                "Support has been notified and will process your withdrawal manually."
            )
            translated = await self.translation_manager.translate_for_user(error_text, chat_id)
            await query.edit_message_text(translated, parse_mode="HTML")
            
    # ────────────────────────── util: پاسخ با ترجمه ────────────────────────────
    async def _reply(self, update: Update, context: ContextTypes.DEFAULT_TYPE,
                     text: str, chat_id: int) -> None:
        translated = await self.translation_manager.translate_for_user(text, chat_id)
        await update.message.reply_text(
            translated, parse_mode="HTML",
            reply_markup=await self.keyboards.build_back_exit_keyboard(chat_id)
        )



###########################################################################################################
    # # ─────────────────────────────── تأیید نهایی ───────────────────────────────
    # async def confirm_withdraw_callback(
    #     self, update: Update, context: ContextTypes.DEFAULT_TYPE
    # ) -> None:
    #     """
    #     کاربر دکمهٔ «Confirm Withdraw» را می‌زند.
    #     • درخواست در DB ثبت می‌شود
    #     • زیرمجموعه‌ها حذف و عضویت به حالت «withdrawn» می‌رود
    #     • پیام موفقیت و زمان‌بندی پرداخت ارسال می‌شود
    #     """
    #     query = update.callback_query
    #     await query.answer()
    #     chat_id = query.from_user.id

    #     try:
    #         wallet = await self.db.get_wallet_address(chat_id)
    #         downline_cnt = await self.db.get_downline_count(chat_id)

    #         # آخرین چک سریع
    #         if downline_cnt < REQUIRED_REFERRALS:
    #             text = (
    #                 "❌ Withdrawal conditions are no longer satisfied.\n"
    #                 "Please refresh the page and try again."
    #             )
    #             await query.edit_message_text(text, parse_mode="HTML")
    #             return

    #         # ➊ ثبت درخواست برداشت در DB
    #         await self.db.create_withdraw_request(
    #             chat_id,
    #             wallet,
    #             WITHDRAW_AMOUNT_USD,
    #         )

    #         # ➋ پاک‌سازی زیرمجموعه‌ها + تغییر وضعیت عضویت
    #         await self.db.clear_downline(chat_id)
    #         await self.db.mark_membership_withdrawn(chat_id)

    #         # ➌ (اختیاری) انتقال آنی روی بلاک‌چین
    #         # tx_id = await self.blockchain.transfer_usdt(wallet, WITHDRAW_AMOUNT_USD)

    #         # ➍ پیام موفقیت
    #         translated = await self.translation_manager.translate_for_user(
    #             f"✅ Withdrawal request registered.\n{PROCESSING_NOTE}", chat_id
    #         )
    #         await query.edit_message_text(translated, parse_mode="HTML")

    #         # ➎ Reply-keyboard Back/Exit
    #         await context.bot.send_message(
    #             chat_id,
    #             text="🏠 Returning to main menu…",
    #             reply_markup=await self.keyboards.build_main_menu_keyboard_v2(chat_id),
    #         )

    #         self.logger.info(f"[withdraw] user {chat_id} requested withdrawal of ${WITHDRAW_AMOUNT_USD}")

    #     except Exception as exc:
    #         await self.error_handler.handle(update, context, exc, "confirm_withdraw_callback")