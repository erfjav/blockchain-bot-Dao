from __future__ import annotations
"""
Profile.py – Unified profile handler
-----------------------------------
•  *Member No* and *Referral Code* are **always** visible so the user can share
  their invitation link immediately after pressing **/start**.
•  Other fields (*Tokens*, *Pending Commission*, *Down‑line Count* & the paged
  list of referrals) become meaningful **only after the user has purchased a
  plan (``joined=True``)**.
  – Before joining, those extra fields are shown with an em‑dash placeholder.
  – If the user taps a section that needs post‑payment data we remind them with
    the translated sentence::

        You don’t have a profile yet. Please join the plan first.

This file replaces previous drafts and is now aligned with:
  ✓ `Database.get_profile` / `Database.get_downline`
  ✓ `ReferralManager.ensure_user` (alias `ensure_profile` was added)
"""

import logging
import math
from typing import Any, Dict, Final, List

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

# from language_Manager import TranslationManager
from keyboards import TranslatedKeyboards
from error_handler import ErrorHandler
from myproject_database import Database
from Referral_logic_code import ReferralManager
# from Translated_Inline_Keyboards import TranslatedInlineKeyboards
from state_manager import push_state, pop_state
from coinaddrvalidator import validate


def valid_wallet_format(address: str) -> bool:
    # اگر coin را ندهید، خودش تشخیص می‌دهد یا می‌توانید specify کنید:
    #   validate(address, 'BTC') یا 'ETH' و …
    return validate(address)

# ░░ Configuration ░░───────────────────────────────────────────────────────────
PAGE_SIZE: Final[int] = 30  # members shown per page
logger = logging.getLogger(__name__)


class ProfileHandler:
    """Handles creation & presentation of user profile screens."""

    def __init__(
        self,
        db: Database,
        referral_manager: ReferralManager,
        keyboards: TranslatedKeyboards,
        # translation_manager: TranslationManager,
        # inline_translator: TranslatedInlineKeyboards,
        error_handler: ErrorHandler,
        
    ) -> None:
        self.db = db
        self.referral_manager = referral_manager
        self.keyboards = keyboards
        # self.translation_manager = translation_manager
        # self.inline_translator = inline_translator
        self.error_handler = error_handler
        self.logger = logging.getLogger(self.__class__.__name__)

    # ───────────────────────────────── Telegram entry‑point ───────────────────

    async def show_profile(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        page: int = 1,
    ) -> None:
        """Main handler for both */profile* command and pagination callbacks."""

        try:
            # 1) Detect origin (fresh /profile vs. pagination callback)
            if update.callback_query:
                query = update.callback_query
                await query.answer()
                chat_id = query.from_user.id
                callback_parts = query.data.split("_")
                if len(callback_parts) == 3 and callback_parts[1] == "page":
                    page = int(callback_parts[2])
                reply_func = query.edit_message_text
            else:
                chat_id = update.effective_chat.id
                page = 1
                reply_func = update.message.reply_text  # type: ignore[attr-defined]

            first_name: str = (
                update.effective_user.first_name if update.effective_user else "Friend"
            )

            # 2) Persist FSM state (optional)
            push_state(context, "showing_profile")
            context.user_data["state"] = "showing_profile"
            
            # 3) fetch profile – second fetch after ensure_user guarantees completeness
            profile: Dict[str, Any] | None = await self.db.get_profile(chat_id)
            if profile is None or "member_no" not in profile or "referral_code" not in profile:
                await self.referral_manager.ensure_user(chat_id, first_name)
                profile = await self.db.get_profile(chat_id)  # now assured to be complete               

            joined: bool = bool(profile.get("joined", False))
            member_no: int = profile["member_no"]
            referral_code: str = profile["referral_code"]
            tokens: int | None = profile.get("tokens")
            commission: float | None = profile.get("commission_usd")
            downline_count: int = profile.get("downline_count", 0)
            wallet_address = await self.db.get_wallet_address(chat_id)
            
            # 5) Compose message body
            placeholder = "—"
            lines: List[str] = [
                f"<b>{('Member No')}:</b> {member_no}",
                f"<b>{('Referral Code')}:</b> <code>{referral_code}</code>",
                f"<b>Wallet Address:</b> <code>{wallet_address or placeholder}</code>",
                "─────────────",
                f"<b>{('Tokens')}:</b> {tokens if joined else placeholder}",
                f"<b>{('Pending Commission')}:</b> {commission if joined else placeholder}",
                f"<b>{('Down‑line Count')}:</b> {downline_count if joined else placeholder}\n\n",

                # ✦ Explanation of referral link
                f"To invite friends and grow your <b>Down-line</b>, simply tap on \n\n "
                f"<b>🔗 Share&nbsp;Referral&nbsp;Link</b>.\n\n "
                f"Your personal referral link will be automatically sent to the selected contact. 🚀",                
                            
            ]

            if not joined:
                lines += [
                    "",
                    (
                        "<b>You don’t have a profile yet.</b> To view your full profile details — "
                        "including your <b>tokens</b>, <b>commissions</b>, and <b>down-line statistics</b> — "
                        "please <b>join a plan</b> first."
                    )
                ]
       
            # 6) Inline keyboard – share link always first
            bot_username: str = context.bot.username  # e.g. AskGenieAIbot
            deep_link: str   = f"https://t.me/{bot_username}?start={referral_code}"

            # لینک «Share» بومی تلگرام؛ کاربر لیست مخاطبان را می‌بیند و می‌تواند لینک را مستقیماً بفرستد
            share_url: str = (
                "https://t.me/share/url"
                f"?url={deep_link}"
                "&text=🚀 Join me on Bot!"
            )

            rows: List[List[InlineKeyboardButton]] = [
                [InlineKeyboardButton("🔗 Share Referral Link", url=share_url)]
            ]

            # 7) Down‑line list (only if joined & has referrals)
            if joined and downline_count:
                downline: List[Dict[str, Any]] = await self.db.get_downline(chat_id, page)
                start_idx: int = (page - 1) * PAGE_SIZE + 1
                for idx, member in enumerate(downline, start=start_idx):
                    
                    rows.append([
                        InlineKeyboardButton(
                            f"{idx}. {member['first_name']} — <code>{member['referral_code']}</code>",
                            callback_data="noop",  # informational only
                        )
                    ])

                # Pagination
                total_pages = max(1, math.ceil(downline_count / PAGE_SIZE))
                nav_row: List[InlineKeyboardButton] = []
                if page > 1:
                    nav_row.append(
                        InlineKeyboardButton("⬅️ Prev", callback_data=f"profile_page_{page - 1}")
                    )
                if page < total_pages:
                    nav_row.append(
                        InlineKeyboardButton("Next ➡️", callback_data=f"profile_page_{page + 1}")
                    )
                if nav_row:
                    rows.append(nav_row)

            # 8) Back & Exit (always)
            rows.append([
                InlineKeyboardButton(("Back"), callback_data="back"),
                InlineKeyboardButton(("Exit"), callback_data="exit"),
            ])

            # # حالا فقط همین یک خط:
            # reply_markup = await self.inline_translator.build_inline_keyboard_for_user(rows, chat_id)
            inline_kb = InlineKeyboardMarkup(rows)
            # 9) Send / edit
            await reply_func(
                "\n".join(lines),
                parse_mode="HTML",
                reply_markup=inline_kb,
            )

            # 10) Reply-Keyboard (⬅️ Back / ➡️ Exit) — همیشه پایین صفحه بماند
            await context.bot.send_message(
                chat_id=chat_id,
                text="ℹ️ No profile information available.",  # متن می‌تواند خالی یا یک نیم‌فاصله باشد
                reply_markup=await self.keyboards.build_wallet_keyboard(chat_id)
            )

        except Exception as exc:
            await self.error_handler.handle(update, context, exc, context_name="show_profile")

    # -----------------------------------------------------------------
    async def back_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        ⬅️ Back  – صرفاً یک «Undo» سطحی:
        • آخرین state را از استک حذف می‌کند.
        • اگر state جدید 'showing_profile' باشد، پروفایل را رفرش می‌کند.
        • در غیر این‌صورت، فقط آیکون ⬅️ را روی پیام می‌گذارد تا
            کاربر بداند به مرحلهٔ قبل بازگشته است.
        """
        query = update.callback_query
        await query.answer()

        prev_state = pop_state(context)          # state جدید پس از pop
        if prev_state == "showing_profile":
            await self.show_profile(update, context)
        else:
            await query.edit_message_text("◀️", reply_markup=None)


    # ------------------------------------------------------------------
    async def exit_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        ❌ Exit – پایان فلوی جاری:
        • پیام اینلاین را پاک می‌کند (یا متن «Done» می‌گذارد).
        • تمام داده‌های موقتی کاربر را از user_data پاک می‌کند.
        """
        query = update.callback_query
        await query.answer()

        try:
            await query.message.delete()
        except Exception:
            await query.edit_message_text("✅ Done.")
        context.user_data.clear()


    # ------------------------------------------------------------------
    async def noop_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        دکمه‌های purely-informational (مانند لیست زیرمجموعه‌ها) را از حالت
        «loading…» خارج می‌کند تا تجربهٔ UX روان بماند.
        """
        await update.callback_query.answer()
#################################################################################################################


    async def edit_wallet(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Prompt the user to add or update their wallet address.

        - If no address is stored yet, show a welcome explanation:
          the bot needs this address to send token rewards or process payments.
        - If an address already exists, display it and ask for the new one.
        """
        chat_id = update.effective_chat.id

        # ۱) بررسی می‌کنیم آیا قبلاً آدرسی ذخیره شده یا خیر
        old_address = await self.db.get_wallet_address(chat_id)

        if old_address:
            # مسیر ویرایش: به کاربر آدرس فعلی را نشان می‌دهیم
            prompt_text = (
                f"📋 Your current wallet address is:\n"
                f"<code>{old_address}</code>\n\n"
                "If you’d like to change it, please send the new address now:"
            )
        else:
            # مسیر ثبت اولیه: توضیح می‌دهیم که آدرس چرا لازم است
            prompt_text = (
                "👋 Welcome! Here you can register your crypto wallet address.\n"
                "We use this address to send you token rewards and handle payments securely.\n\n"
                "Please send your wallet address now:"
            )

        # ۲) ارسال پیام با دکمه‌های Back/Exit
        await update.message.reply_text(
            prompt_text,
            parse_mode="HTML",
            reply_markup=await self.keyboards.build_back_exit_keyboard(chat_id)
        )

        # ۳) ست کردن state برای دریافت پیام بعدی در handle_wallet_input
        push_state(context, "awaiting_wallet")
        context.user_data["state"] = "awaiting_wallet"

    # -----------------------------------------------------------------------------------------

    async def handle_wallet_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Handle the user's wallet address input:
        1) Read the incoming text as the address.
        2) Validate format.
        3) Save or update in the database.
        4) Send a confirmation with the new address.
        5) Clear FSM state and show updated profile.
        """
        chat_id = update.effective_chat.id
        address = update.message.text.strip()

        # ۱) بررسی اولیه فرمت (مثلاً با coinaddrvalidator)
        if not valid_wallet_format(address):
            return await update.message.reply_text(
                "❌ The address you entered is not valid. Please try again:",
                reply_markup=await self.keyboards.build_back_exit_keyboard(chat_id)
            )

        # ۲) ذخیره یا به‌روزرسانی آدرس در MongoDB
        await self.db.set_wallet_address(chat_id, address)

        # ۳) تأیید به کاربر
        await update.message.reply_text(
            f"✅ Your wallet address has been successfully set to:\n"
            f"<code>{address}</code>",
            parse_mode="HTML",
            reply_markup=await self.keyboards.build_back_exit_keyboard(chat_id)
        )

        # ۴) پاک کردن state و نمایش پروفایل به‌روز
        pop_state(context)
        await self.show_profile(update, context)


    # async def edit_wallet(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    #     # ۱) تشخیص منبع فراخوانی: Inline یا ReplyKeyboard
    #     if update.callback_query:
    #         query = update.callback_query
    #         await query.answer()
    #         chat_id = query.from_user.id
    #         # ویرایش پیام قبلی
    #         await query.edit_message_text("لطفاً آدرس کیف پول خود را ارسال کنید:")
    #     else:
    #         # update.message
    #         chat_id = update.effective_chat.id
    #         await update.message.reply_text("لطفاً آدرس کیف پول خود را ارسال کنید:")

    #     # ۲) ست کردن state تا پیام بعدی به handle_wallet_input برود
    #     push_state(context, "awaiting_wallet")
    #     context.user_data["state"] = "awaiting_wallet"

        
    # #------------------------------------------------------------------------------------------------
    # async def handle_wallet_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    #     chat_id = update.effective_chat.id
    #     address = update.message.text.strip()

    #     # (اختیاری) اعتبارسنجی ابتدایی آدرس
    #     if not valid_wallet_format(address):
    #         return await update.message.reply_text("آدرس وارد شده معتبر نیست. دوباره تلاش کنید:")

    #     # ذخیره در دیتابیس
    #     await self.db.set_wallet_address(chat_id, address)

    #     # پاک کردن state و بازگشت به پروفایل
    #     pop_state(context)
    #     await update.message.reply_text("آدرس کیف پول با موفقیت ثبت شد.")
    #     await self.show_profile(update, context)