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
from datetime import datetime
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from bot_ui.language_Manager import TranslationManager
from bot_ui.keyboards import TranslatedKeyboards
from error_handler import ErrorHandler
from myproject_database import Database
from Referral_logic_code import ReferralManager
from bot_ui.Translated_Inline_Keyboards import TranslatedInlineKeyboards
from state_manager import push_state, pop_state
from coinaddrvalidator import validate
import base58
from web3 import Web3
from pymongo.errors import DuplicateKeyError

from config import MAIN_LEADER_IDS, SECOND_ADMIN_USER_IDS


def valid_tron_address(address: str) -> bool:
    """
    اعتبارسنجی آدرس Tron (USDT-TRC20 و هر توکن دیگری روی Tron):
      • باید با 'T' شروع شود
      • طول بین 34 تا 35 کاراکتر Base58 باشد
      • کاراکترهای Base58: 123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz
      • بررسی checksum با base58.decode_check
      • اعتبارسنجی نهایی با coinaddrvalidator
    """
    # ۱) بررسی شکل ظاهری اولیه
    if not address.startswith("T"):
        return False
    if not (34 <= len(address) <= 35):
        return False

    # ۲) بررسی اینکه فقط کاراکترهای Base58 استفاده شده
    base58_chars = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    if any(c not in base58_chars for c in address):
        return False

    # ۳) Decode با checksum برای اطمینان از عدم خطای تایپی
    try:
        # این متد در صورت شکست در checksum خطا می‌اندازد
        _ = base58.b58decode_check(address)
    except Exception:
        return False

    # ۴) اعتبارسنجی نهایی با coinaddrvalidator (اگر پشتیبانی کند)
    try:
        return validate(address, "TRON")
    except Exception:
        # اگر coinaddrvalidator پشتیبانی نداشت، باز هم OK است
        return True

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
        inline_translator: TranslatedInlineKeyboards,
        error_handler: ErrorHandler,
        
    ) -> None:
        self.db = db
        self.referral_manager = referral_manager
        self.keyboards = keyboards
        self.translation_manager = translation_manager
        self.inline_translator = inline_translator
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

            # ➊ ثبت state در پشته
            push_state(context, "profile_menu")
            context.user_data["state"] = "profile_menu"            
            
            chat_id   = update.effective_chat.id

            # متن خوش‌آمد و توضیحات دکمه‌ها
            welcome_text = (
                "📋 *Welcome to Your Profile Menu!*\n\n"
                "You’ve entered your personal space where you can:\n\n"
                "🔹 *See Profile* – View your basic information, subscription details, referral stats, and more.\n\n"
                "🔹 *Wallet* – Check your registered crypto wallet address or update it if needed.\n\n"
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
            # ➊ ثبت state در پشته
            push_state(context, "profile_wallet_menu")
            context.user_data["state"] = "profile_wallet_menu"
            
            chat_id   = update.effective_chat.id

            # پیام توضیح منوی کیف‌پول
            wallet_text = (
                "🏦 *Welcome to Your Wallet Menu!*\n\n"
                "Here you can manage your wallet and perform key operations:\n\n"
                "🔹 *Set Wallet* – Register your crypto wallet address for the first time.\n\n"
                "🔹 *Edit Wallet* – Update or change your existing wallet address.\n\n"
                "🔄 *Transfer Tokens* – Send your tokens to another address.\n\n"
                "💰 *View Balance* – See your current available token balance.\n\n"
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
                
                # await self.referral_manager.ensure_user(chat_id, first_name)

                await self.referral_manager.ensure_user(
                    user_id=chat_id,
                    first_name=first_name
                )
                
                
                profile = await self.db.get_profile(chat_id)  # now assured to be complete               

                # if still None, abort gracefully
                if profile is None:
                    await reply_func(
                        "❗️خطا در بارگذاری پروفایل. لطفاً کمی بعد دوباره امتحان کنید.",
                        parse_mode="HTML"
                    )
                    return

            joined: bool = bool(profile.get("joined", False))
            
            member_no: int = profile["member_no"]
            referral_code: str = profile["referral_code"]
            tokens: int | None = profile.get("tokens")
            commission: float | None = profile.get("commission_usd")
            balance: float = profile.get("balance_usd", 0.0)
            downline_count: int = profile.get("downline_count", 0)
            wallet_address = await self.db.get_wallet_address(chat_id)
            
            is_manager = chat_id in MAIN_LEADER_IDS or chat_id in SECOND_ADMIN_USER_IDS
            star_tag = "⭐" if is_manager else ""
            
            username = update.effective_user.username if update.effective_user and update.effective_user.username else "—"            
            
            # 5) Compose message body
            placeholder = "—"
            lines: List[str] = [
                f"<b>{('Member No')}:</b> {member_no}{star_tag}",
                f"<b>{('Referral Code')}:</b> <code>{referral_code}</code>",
                f"<b>Wallet Address:</b> <code>{wallet_address or placeholder}</code>",
                "─────────────",
                f"<b>{('Tokens')}:</b> {tokens if (joined or is_manager) else placeholder}",
                f"<b>Current Balance:</b> {f'${balance:.2f}' if (joined or is_manager) else placeholder}",
                f"<b>{('Pending Commission')}:</b> {commission if (joined or is_manager) else placeholder}",
                f"<b>{('Down‑line Count')}:</b> {downline_count if (joined or is_manager) else placeholder}\n\n",

                # ✦ Explanation of referral link
                f"To invite friends and grow your <b>Down-line</b>, simply tap on \n\n "
                f"<b>🔗 Share&nbsp;Referral&nbsp;Link</b>.\n\n "
                f"Your personal referral link will be automatically sent to the selected contact. 🚀",                
                            
            ]

            if is_manager:
                # اول User ID، بعد Username اضافه میشه
                lines.insert(0, f"<b>User ID:</b> <code>{chat_id}</code>")
                lines.insert(1, f"<b>Username:</b> @{username}" if username != "—" else "<b>Username:</b> <i>Not set</i>")

            if not (joined or is_manager):
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

            #---------------------------------------------------------------------------------------------------------
            # اینجا دکمه گزارش پرداخت رو فقط برای لیدرها اضافه کن:
            if is_manager:
                rows.append([InlineKeyboardButton("📋 View All Payouts", callback_data="view_all_payouts_1")])
                
            #---------------------------------------------------------------------------------------------------------
            # 7) Down‑line list (only if joined & has referrals)
            if joined and downline_count:
                downline: List[Dict[str, Any]] = await self.db.get_downline(chat_id, page)
                start_idx: int = (page - 1) * PAGE_SIZE + 1
                for idx, member in enumerate(downline, start=start_idx):
                    
                    rows.append([
                        InlineKeyboardButton(
                            f"{idx}. {member['first_name']} — {member['referral_code']}",
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

            # inline_kb = InlineKeyboardMarkup(rows)
            
            inline_kb = await self.inline_translator.build_inline_keyboard_for_user(rows, chat_id)

            translated_text = await self.translation_manager.translate_for_user("\n".join(lines), chat_id)
            # 9) Send / edit
            await reply_func(
                translated_text,
                parse_mode="HTML",
                reply_markup=inline_kb,
            )

            translated_note = await self.translation_manager.translate_for_user(
                "📋 Profile loaded. You can use the buttons below to continue.",
                chat_id
            )

            # 10) Reply-Keyboard (⬅️ Back / ➡️ Exit) — همیشه پایین صفحه بماند
            await context.bot.send_message(
                chat_id=chat_id,
                text=translated_note,  
                reply_markup=await self.keyboards.build_back_exit_keyboard(chat_id)
            )

        except Exception as exc:
            await self.error_handler.handle(update, context, exc, context_name="show_profile")
            
    #---------------------------------------------------------------------------------------------------------------
    async def handle_view_all_payouts(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        نمایش لیست پرداخت‌های لیدر با قابلیت صفحه‌بندی (فقط برای لیدرها)
        """
        query = update.callback_query
        chat_id = query.from_user.id

        # بررسی فقط لیدرها ببینند
        from config import MAIN_LEADER_IDS, SECOND_ADMIN_USER_IDS
        is_manager = chat_id in MAIN_LEADER_IDS or chat_id in SECOND_ADMIN_USER_IDS
        if not is_manager:
            await query.answer("You are not authorized.")
            return

        # استخراج شماره صفحه از کال‌بک دیتا
        data = query.data  # مثل: view_all_payouts_1
        try:
            page = int(data.split('_')[-1])
        except Exception:
            page = 1

        page_size = 5
        skip = (page - 1) * page_size

        # واکشی رکوردها از دیتابیس
        total_count = await self.db.collection_leader_payments.count_documents({"user_id": chat_id})
        cursor = self.db.collection_leader_payments.find(
            {"user_id": chat_id}
        ).sort("date", -1).skip(skip).limit(page_size)
        payouts = await cursor.to_list(length=page_size)

        if not payouts:
            await query.edit_message_text(
                "No payouts recorded yet.",
                parse_mode="HTML"
            )
            return

        # ساخت پیام گزارش
        lines = ["<b>Your Payout History</b>\n"]
        for p in payouts:
            date_str = p.get("date")
            if isinstance(date_str, datetime):
                date_str = date_str.strftime("%Y-%m-%d")
            elif isinstance(date_str, str):
                # اگر iso string بود (برای Mongo)، فقط تاریخش رو بردار
                date_str = date_str[:10]
            lines.append(
                f"• <b>{date_str}</b> — "
                f"{p['amount']} {p['token']} (<code>{p['tx_hash'][:10]}…</code>)"
            )
        msg = "\n".join(lines)

        # دکمه‌های صفحه قبل/بعد
        buttons = []
        if page > 1:
            buttons.append(InlineKeyboardButton("⬅️ Previous", callback_data=f"view_all_payouts_{page - 1}"))
        if skip + page_size < total_count:
            buttons.append(InlineKeyboardButton("Next ➡️", callback_data=f"view_all_payouts_{page + 1}"))

        # اضافه کردن Back و Exit به همان ردیف
        buttons.append(InlineKeyboardButton("⬅️ Back", callback_data="back"))
        buttons.append(InlineKeyboardButton("Exit", callback_data="exit"))
        
        keyboard = InlineKeyboardMarkup([buttons]) if buttons else None

        await query.edit_message_text(
            msg,
            reply_markup=keyboard,
            parse_mode="HTML"
        )

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
        
    #-------------------------------------------------------------------------------------    
    async def edit_wallet(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        نمایش آدرس فعلی (اگر وجود دارد) و درخواست آدرس جدید کیف‌پول
        """
        try:
                        # ذخیره state
            push_state(context, "awaiting_wallet")
            context.user_data["state"] = "awaiting_wallet"
            
            chat_id = update.effective_chat.id
            old_address = await self.db.get_wallet_address(chat_id)

            if old_address:
                prompt_text = (
                    "📋 <b>Your current wallet address is:</b>\n"
                    f"<code>{old_address}</code>\n\n"
                    "If you’d like to update it, please send the new wallet address now:"
                )
            else:
                prompt_text = (
                    "👋 <b>Welcome!</b>\n\n"
                    "To begin, please register your <b>TRON wallet address</b> below.\n"
                    "This is required to receive your token rewards and payouts securely on the TRON network (e.g., USDT-TRC20).\n\n"
                    "⚠️ Make sure your address:\n"
                    "  • Starts with <code>T</code>\n"
                    "  • Is approximately 34 characters long\n"
                    "  • Belongs to a supported wallet such as TronLink, Trust Wallet, or TokenPocket\n\n"
                    "🔐 <b>Send your TRON wallet address now:</b>"
                )

            translated_text = await self.translation_manager.translate_for_user(prompt_text, chat_id)

            await update.message.reply_text(
                translated_text,
                parse_mode="HTML",
                reply_markup=await self.keyboards.build_back_exit_keyboard(chat_id)
            )

        except Exception as e:
            self.logger.error(f"Error in edit_wallet: {e}")
            await update.message.reply_text(
                "⚠️ <b>An error occurred while editing your wallet address.</b>",
                parse_mode="HTML"
            )

    #------------------------------------------------------------------------------------------------------
    async def handle_wallet_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        بررسی فرمت، تکراری نبودن و ثبت آدرس کیف‌پول
        """
        chat_id = update.effective_chat.id
        raw = (update.message.text or "").strip()
        address = raw

        try:
            # ۱) بررسی فرمت آدرس
            if not valid_tron_address(address):

                text = (
                    "❌ <b>The wallet address you entered is not valid.</b>\n\n"
                    "Please enter a valid <b>TRON wallet address</b>. It must start with <code>T</code> and typically be 34 characters long.\n\n"
                    "✅ <b>Examples of valid TRON addresses:</b>\n"
                    "  • <code>TKr3jPnQ4H1eG8XYZABcdEfGhI2345678</code>\n"
                    "  • <code>TXy9LmNoPQrStUvWxYz1234567890ABcd</code>\n\n"
                    "💡 <b>Recommended TRON wallets:</b>\n"
                    "  • <b>TronLink</b> (browser extension & mobile app)\n"
                    "  • <b>Trust Wallet</b> (multi-chain mobile wallet)\n"
                    "  • <b>TokenPocket</b> (multi-chain support)\n"
                    "  • <b>Math Wallet</b>\n\n"
                    "🔎 <i>TRON network is extremely cost-effective</i> — transaction fees are usually under <b>0.01 USDT</b>. So feel free to retry without worrying about fees.\n\n"
                    "➡️ Now, please enter your correct TRON wallet address:"
                )


                translated = await self.translation_manager.translate_for_user(text, chat_id)
                return await update.message.reply_text(
                    translated,
                    parse_mode="HTML",
                    reply_markup=await self.keyboards.build_back_exit_keyboard(chat_id)
                )

            # ۲) بررسی تکراری نبودن آدرس
            existing = await self.db.get_user_by_wallet(address)
            if existing and existing != chat_id:
                text = (
                    "❌ <b>This wallet address is already in use by another user.</b>\n"
                    "Please enter a different wallet address:"
                )
                translated = await self.translation_manager.translate_for_user(text, chat_id)
                return await update.message.reply_text(
                    translated,
                    parse_mode="HTML",
                    reply_markup=await self.keyboards.build_back_exit_keyboard(chat_id)
                )

            # ۳) ذخیره آدرس
            try:
                await self.db.set_wallet_address(chat_id, address)
            except DuplicateKeyError:
                text = (
                    "❌ <b>This wallet address is already registered.</b>\n"
                    "Please send a different address:"
                )
                translated = await self.translation_manager.translate_for_user(text, chat_id)
                return await update.message.reply_text(
                    translated,
                    parse_mode="HTML",
                    reply_markup=await self.keyboards.build_back_exit_keyboard(chat_id)
                )

            # ۴) تایید موفقیت
            text = (
                "✅ <b>Your wallet address has been successfully updated.</b>\n"
                f"New address: <code>{address}</code>"
            )
            translated = await self.translation_manager.translate_for_user(text, chat_id)
            await update.message.reply_text(
                translated,
                parse_mode="HTML",
                reply_markup=await self.keyboards.build_back_exit_keyboard(chat_id)
            )

            # ۵) پاک‌سازی state و بازگشت به پروفایل
            pop_state(context)
            context.user_data.pop("state", None)
            await self.show_profile(update, context)

        except Exception as e:
            self.logger.error(f"Error in handle_wallet_input: {e}")
            await update.message.reply_text(
                "⚠️ <b>An unexpected error occurred while saving your wallet address.</b>",
                parse_mode="HTML"
            )
    
    #-------------------------------------------------------------------------------------   
    async def view_balance(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        نمایش موجودی توکن با ترجمه و فرمت‌بندی
        """
        chat_id = update.effective_chat.id

        try:
            balance = await self.db.get_user_balance(chat_id)

            text = f"💰 <b>Your current token balance is:</b> <code>{balance:.2f}</code> tokens"
            translated_text = await self.translation_manager.translate_for_user(text, chat_id)

            await update.message.reply_text(
                translated_text,
                parse_mode="HTML",
                reply_markup=await self.keyboards.build_back_exit_keyboard(chat_id)
            )

        except Exception as e:
            self.logger.error(f"Error in view_balance: {e}")
            error_text = "⚠️ <b>Unable to load your balance at the moment.</b>"
            translated_text = await self.translation_manager.translate_for_user(error_text, chat_id)
            await update.message.reply_text(translated_text, parse_mode="HTML")

    #-------------------------------------------------------------------------------------   
    async def view_history(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        نمایش تاریخچه‌ی تغییرات کیف‌پول با ترجمه
        """
        chat_id = update.effective_chat.id

        try:

            events = await self.db.get_wallet_history(chat_id, limit=10)

            if not events:
                text = "📭 <b>No transaction history found.</b>"
            else:
                lines = []
                for e in events:
                    ts = e["timestamp"].strftime("%Y-%m-%d %H:%M")
                    amt = f"{e['amount']:+.2f}"
                    event_type = e["event_type"].replace("_", " ").title()
                    lines.append(f"🕒 <code>{ts}</code> | <b>{amt}</b> tokens | {event_type}")
                text = "📜 <b>Recent Wallet Activity:</b>\n\n" + "\n".join(lines)

            translated_text = await self.translation_manager.translate_for_user(text, chat_id)

            await update.message.reply_text(
                translated_text,
                parse_mode="HTML",
                reply_markup=await self.keyboards.build_back_exit_keyboard(chat_id)
            )

        except Exception as e:
            self.logger.error(f"Error in view_history: {e}")
            error_text = "⚠️ <b>Could not retrieve wallet history.</b>"
            translated_text = await self.translation_manager.translate_for_user(error_text, chat_id)
            await update.message.reply_text(translated_text, parse_mode="HTML")

    #---------------------------------------------------------------------------------------------------   
    async def initiate_transfer(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Step 1: Check wallet address and balance, then ask for transfer amount.
        """
        chat_id = update.effective_chat.id

        try:
            # user_lang = await self.db.get_user_language(chat_id) or "en"

            # ۱) بررسی وجود آدرس کیف‌پول
            wallet = await self.db.get_wallet_address(chat_id)
            if not wallet:
                text = (
                    "❌ <b>No wallet address found!</b>\n"
                    "Please register your wallet address before making a transfer."
                )
                translated_text = await self.translation_manager.translate_for_user(text, chat_id)
                return await update.message.reply_text(
                    translated_text,
                    parse_mode="HTML",
                    reply_markup=await self.keyboards.build_back_exit_keyboard(chat_id)
                )

            # ۲) بررسی موجودی
            balance = await self.db.get_user_balance(chat_id)
            if balance <= 0:
                text = (
                    "❌ <b>Your balance is zero.</b>\n"
                    "You must have tokens available before initiating a transfer."
                )
                translated_text = await self.translation_manager.translate_for_user(text, chat_id)
                return await update.message.reply_text(
                    translated_text,
                    parse_mode="HTML",
                    reply_markup=await self.keyboards.build_back_exit_keyboard(chat_id)
                )

            # ۳) ذخیره state و موجودی
            push_state(context, "awaiting_transfer_amount")
            context.user_data["state"] = "awaiting_transfer_amount"
            context.user_data["wallet_balance"] = balance

            # ۴) ارسال پیام درخواست مقدار انتقال
            text = (
                f"💰 <b>Your current balance:</b> <code>{balance:.2f}</code> tokens\n\n"
                f"📤 <b>How many tokens</b> would you like to transfer to:\n<code>{wallet}</code> ?"
            )
            translated_text = await self.translation_manager.translate_for_user(text, chat_id)

            await update.message.reply_text(
                translated_text,
                parse_mode="HTML",
                reply_markup=await self.keyboards.build_back_exit_keyboard(chat_id)
            )

        except Exception as e:
            self.logger.error(f"Error in initiate_transfer: {e}")
            await update.message.reply_text(
                "⚠️ <b>An unexpected error occurred while preparing the transfer.</b>",
                parse_mode="HTML"
            )
        
    #-----------------------------------------------------------------------------------------------------
    async def handle_transfer_amount(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Step 2: Validate user input amount and process token transfer
        """
        chat_id = update.effective_chat.id
        text = (update.message.text or "").strip()

        try:
            # user_lang = await self.db.get_user_language(chat_id) or "en"

            # ۱) بررسی عدد بودن مقدار وارد شده
            try:
                amount = float(text)
            except ValueError:
                invalid_input_text = (
                    "❌ <b>Invalid input!</b>\n"
                    "Please enter a valid numeric amount to transfer:"
                )
                translated_text = await self.translation_manager.translate_for_user(invalid_input_text, chat_id)
                return await update.message.reply_text(
                    translated_text,
                    parse_mode="HTML",
                    reply_markup=await self.keyboards.build_back_exit_keyboard(chat_id)
                )

            # ۲) بررسی اعتبار مقدار وارد شده
            balance = context.user_data.get("wallet_balance", 0.0)
            if amount <= 0 or amount > balance:
                invalid_amount_text = (
                    f"❌ <b>Invalid amount!</b>\n"
                    f"You can only transfer between <b>0</b> and <b>{balance:.2f}</b> tokens."
                )
                translated_text = await self.translation_manager.translate_for_user(invalid_amount_text, chat_id)
                return await update.message.reply_text(
                    translated_text,
                    parse_mode="HTML",
                    reply_markup=await self.keyboards.build_back_exit_keyboard(chat_id)
                )

            # ۳) کسر از موجودی و ثبت رویداد انتقال
            await self.db.adjust_balance(chat_id, -amount)
            await self.db.record_wallet_event(
                chat_id, -amount, "transfer_to_wallet", "Transferred to on-chain wallet"
            )

            # ۴) پیام موفقیت‌آمیز
            success_text = (
                f"✅ <b>Transfer successful!</b>\n"
                f"<b>{amount:.2f} tokens</b> were sent to your registered on-chain wallet."
            )
            translated_text = await self.translation_manager.translate_for_user(success_text, chat_id)
            await update.message.reply_text(
                translated_text,
                parse_mode="HTML",
                reply_markup=await self.keyboards.build_back_exit_keyboard(chat_id)
            )

        except Exception as e:
            self.logger.error(f"Error in handle_transfer_amount: {e}")
            error_text = (
                "⚠️ <b>Unexpected error occurred during the transfer.</b>\n"
                "Please try again later."
            )
            translated_text = await self.translation_manager.translate_for_user(error_text, chat_id)
            await update.message.reply_text(translated_text, parse_mode="HTML")

        finally:
            # ۵) پاک‌سازی state
            pop_state(context)
            context.user_data.pop("state", None)
            context.user_data.pop("wallet_balance", None)
