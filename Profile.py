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

from language_Manager import TranslationManager
from keyboards import TranslatedKeyboards
from error_handler import ErrorHandler
from myproject_database import Database
from Referral_logic_code import ReferralManager
# from Translated_Inline_Keyboards import TranslatedInlineKeyboards
from state_manager import push_state, pop_state
from coinaddrvalidator import validate
from web3 import Web3
from pymongo.errors import DuplicateKeyError


def valid_wallet_format(address: str, chain: str = "ETH") -> bool:
    """
    • chain="ETH" (یا "BSC"): 
      – length 42, start 0x, Web3 + coinaddrvalidator.validate
    • chain="BTC", "LTC", ...: 
      – فقط coinaddrvalidator.validate
    """
    if chain.upper() in {"ETH", "BSC"}:
        # شرط ظاهری اتریوم/بی‌اس‌سی
        if not (address.startswith("0x") and len(address) == 42 and
                all(c in "0123456789abcdefABCDEF" for c in address[2:])):
            return False
        # اعتبارسنجی دقیق
        return Web3.is_address(address) and validate(address, chain.upper())
    else:
        # برای سایر زنجیره‌ها فقط از coinaddrvalidator بهره ببر
        return validate(address, chain.upper())


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
        translation_manager: TranslationManager,
        # inline_translator: TranslatedInlineKeyboards,
        error_handler: ErrorHandler,
        
    ) -> None:
        self.db = db
        self.referral_manager = referral_manager
        self.keyboards = keyboards
        self.translation_manager = translation_manager
        # self.inline_translator = inline_translator
        self.error_handler = error_handler
        self.logger = logging.getLogger(self.__class__.__name__)

    # ───────────────────────────────── Telegram entry‑point ───────────────────


    async def show_profile_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """
        نمایش منوی اولیهٔ پروفایل با ترجمه و کیبورد:
        ["See Profile", "Wallet", "Back", "Exit"]
        """
        try:
            
            chat_id   = update.effective_chat.id

            # متن خوش‌آمد و توضیحات دکمه‌ها
            welcome_text = (
                "📋 *Welcome to Your Profile Menu!*\n\n"
                "You’ve entered your personal space where you can:\n\n"
                "🔹 *See Profile* – View your basic information, subscription details, referral stats, and more.\n\n"
                "🔹 *Wallet* – Check your registered crypto wallet address or update it if needed.\n"
                "🧭 *Please select one of the options from the menu below to continue.*"
            )

            # ترجمه متن برای زبان کاربر
            translated_text = await self.translation_manager.translate_for_user(welcome_text, chat_id)

            # ارسال پیام با کیبورد ترجمه‌شده
            await update.message.reply_text(
                translated_text,
                parse_mode="Markdown",
                reply_markup=await self.keyboards.build_profile_menu_keyboard(chat_id)
            )
        except Exception as e:
            self.logger.error(f"Error in show_profile_menu: {e}")
            await update.message.reply_text("⚠️ An error occurred while loading your profile menu.")

#########----------------------------------------------------------------------------------------------------
    async def show_wallet_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """
        نمایش منوی کیف‌پول با ترجمه و توضیحات:
        شامل: ثبت/ویرایش آدرس، انتقال، موجودی و تاریخچه
        """
        try:
            chat_id   = update.effective_chat.id

            # پیام توضیح منوی کیف‌پول
            wallet_text = (
                "👛 *Welcome to Your Wallet Menu!*\n\n"
                "Here you can manage your wallet and perform key operations:\n\n"
                "🔹 *Set Wallet* – Register your crypto wallet address for the first time.\n"
                "🔹 *Edit Wallet* – Update or change your existing wallet address.\n"
                "🔄 *Transfer Tokens* – Send your tokens to another address.\n"
                "💰 *View Balance* – See your current available token balance.\n"
                "📜 *View History* – Review all your past wallet transactions.\n\n"
                "🧭 *Please choose an option from the menu below to continue.*"
            )

            # ترجمه پیام با توجه به زبان کاربر
            translated_text = await self.translation_manager.translate_for_user(wallet_text, chat_id)

            # ارسال پیام با کیبورد ترجمه‌شده
            await update.message.reply_text(
                translated_text,
                parse_mode="Markdown",
                reply_markup=await self.keyboards.build_wallet_keyboard(chat_id)
            )

        except Exception as e:
            self.logger.error(f"Error in show_wallet_menu: {e}")
            await update.message.reply_text("⚠️ An error occurred while loading your wallet menu.")

#########----------------------------------------------------------------------------------------------------

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
                reply_markup=await self.keyboards.build_back_exit_keyboard(chat_id)
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
        chat_id     = update.effective_chat.id
        old_address = await self.db.get_wallet_address(chat_id)
        if old_address:
            prompt_text = (
                "📋 Your current wallet address is:\n"
                f"<code>{old_address}</code>\n\n"
                "If you’d like to change it, send the new address now:"
            )
        else:
            prompt_text = (
                "👋 Welcome! Please register your crypto wallet address.\n"
                "We need this to send token rewards and handle payments securely.\n\n"
                "Send your wallet address now:"
            )

        await update.message.reply_text(
            prompt_text,
            parse_mode="HTML",
            reply_markup=await self.keyboards.build_back_exit_keyboard(chat_id)
        )
        push_state(context, "awaiting_wallet")
        context.user_data["state"] = "awaiting_wallet"

    async def handle_wallet_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.effective_chat.id
        raw     = (update.message.text or "").strip()
        address = raw.lower()

        # 1) structural + Web3 check
        if not valid_wallet_format(address):
            return await update.message.reply_text(
                "❌ The address you entered is not valid. Please try again:",
                reply_markup=await self.keyboards.build_back_exit_keyboard(chat_id)
            )

        # 2) duplicate?
        existing = await self.db.get_user_by_wallet(address)
        if existing and existing != chat_id:
            return await update.message.reply_text(
                "❌ This wallet address is already registered by another user. Please use a different address.",
                reply_markup=await self.keyboards.build_back_exit_keyboard(chat_id)
            )

        # 3) save
        try:
            await self.db.set_wallet_address(chat_id, address)
        except DuplicateKeyError:
            return await update.message.reply_text(
                "❌ This wallet address is already registered. Please send a different one.",
                reply_markup=await self.keyboards.build_back_exit_keyboard(chat_id)
            )

        # 4) confirm
        await update.message.reply_text(
            f"✅ Your wallet address has been set to:\n<code>{address}</code>",
            parse_mode="HTML",
            reply_markup=await self.keyboards.build_back_exit_keyboard(chat_id)
        )

        # 5) clear state & refresh profile
        pop_state(context)
        context.user_data.pop("state", None)
        await self.show_profile(update, context)
    
    
####################################################################################################

    async def view_balance(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        نمایش موجودی توکن
        """
        chat_id = update.effective_chat.id
        balance = await self.db.get_user_balance(chat_id)
        text = f"💰 موجودی توکن شما: <b>{balance:.2f}</b> توکن"
        await update.message.reply_text(
            text,
            parse_mode="HTML",
            reply_markup=await self.keyboards.build_wallet_keyboard(chat_id)
        )

    async def view_history(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        نمایش تاریخچه تغییرات موجودی
        """
        chat_id = update.effective_chat.id
        events = await self.db.get_wallet_history(chat_id, limit=10)
        if not events:
            text = "📭 هیچ رویدادی یافت نشد."
        else:
            lines = []
            for e in events:
                ts  = e["timestamp"].strftime("%Y-%m-%d %H:%M")
                amt = f"{e['amount']:+.2f}"
                lines.append(f"{ts} | {amt} توکن | {e['event_type']}")
            text = "📜 تاریخچه‌ی اخیر:\n" + "\n".join(lines)
        await update.message.reply_text(
            text,
            parse_mode="HTML",
            reply_markup=await self.keyboards.build_wallet_keyboard(chat_id)
        )
        
    #---------------------------------------------------------------------------------------------------    
    async def initiate_transfer(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        گام اول: پرسش مقدار توکن برای انتقال
        """
        chat_id = update.effective_chat.id
        # ۱) چک آدرس کیف‌پول
        wallet = await self.db.get_wallet_address(chat_id)
        if not wallet:
            return await update.message.reply_text(
                "❌ شما هنوز آدرس کیف‌پول ثبت نکرده‌اید.",
                reply_markup=await self.keyboards.build_wallet_keyboard(chat_id)
            )
        # ۲) موجودی فعلی
        balance = await self.db.get_user_balance(chat_id)
        if balance <= 0:
            return await update.message.reply_text(
                "❌ موجودی شما صفر است و نمی‌توانید انتقال انجام دهید.",
                reply_markup=await self.keyboards.build_wallet_keyboard(chat_id)
            )
        # ۳) تنظیم state و ذخیره موجودی
        push_state(context, "awaiting_transfer_amount")
        context.user_data["state"] = "awaiting_transfer_amount"
        context.user_data["wallet_balance"] = balance
        # ۴) پرسش مقدار
        await update.message.reply_text(
            f"موجودی شما: {balance:.2f} توکن\nچند توکن می‌خواهید به {wallet} انتقال دهید؟",
            reply_markup=await self.keyboards.build_wallet_keyboard(chat_id)
        )

    async def handle_transfer_amount(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        گام دوم: دریافت مقدار، اعتبارسنجی و ثبت انتقال
        """
        chat_id = update.effective_chat.id
        text    = (update.message.text or "").strip()
        try:
            amount = float(text)
        except ValueError:
            return await update.message.reply_text(
                "❌ مقدار وارد شده عدد نیست. لطفاً یک عدد معتبر وارد کنید:",
                reply_markup=await self.keyboards.build_wallet_keyboard(chat_id)
            )
        balance = context.user_data.get("wallet_balance", 0.0)
        if amount <= 0 or amount > balance:
            return await update.message.reply_text(
                f"❌ مقدار نامعتبر است. باید بین 0 و {balance:.2f} باشد.",
                reply_markup=await self.keyboards.build_wallet_keyboard(chat_id)
            )
        # ۵) ذخیره انتقال (ساده: فقط دیتابیس آپدیت و رویداد ثبت می‌شود)
        await self.db.adjust_balance(chat_id, -amount)
        await self.db.record_wallet_event(
            chat_id, -amount, "transfer_to_wallet", f"Transferred to on-chain wallet"
        )
        await update.message.reply_text(
            f"✅ موفقیت‌آمیز! مقدار {amount:.2f} توکن به کیف‌پول شما انتقال یافت.",
            reply_markup=await self.keyboards.build_wallet_keyboard(chat_id)
        )
        # ۶) پاک‌سازی state
        pop_state(context)
        context.user_data.pop("state", None)
        context.user_data.pop("wallet_balance", None)        