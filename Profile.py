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
from state_manager import push_state

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
        error_handler: ErrorHandler,
    ) -> None:
        self.db = db
        self.referral_manager = referral_manager
        self.keyboards = keyboards
        self.translation_manager = translation_manager
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

            # 3) Fetch or create minimal profile skeleton
            profile: Dict[str, Any] | None = await self.db.get_profile(chat_id)
            if profile is None:
                profile = await self.referral_manager.ensure_user(chat_id, first_name)

            joined: bool = bool(profile.get("joined", False))
            member_no: int = profile["member_no"]
            referral_code: str = profile["referral_code"]
            tokens: int | None = profile.get("tokens")
            commission: float | None = profile.get("commission_usd")
            downline_count: int = profile.get("downline_count", 0)

            # 4) Translator shortcut
            tr = self.translation_manager.translate_for_user

            # 5) Compose message body
            placeholder = "—"
            lines: List[str] = [
                f"<b>{tr('Member No')}:</b> {member_no}",
                f"<b>{tr('Referral Code')}:</b> <code>{referral_code}</code>",
                "─────────────",
                f"<b>{tr('Tokens')}:</b> {tokens if joined else placeholder}",
                f"<b>{tr('Pending Commission')}:</b> {commission if joined else placeholder}",
                f"<b>{tr('Down‑line Count')}:</b> {downline_count if joined else placeholder}",
            ]

            if not joined:
                lines += ["", tr("You don’t have a profile yet. Please join the plan first.")]

            # 6) Inline keyboard – share link always first
            bot_username: str = context.bot.username  # e.g. AskGenieAIbot
            referral_link: str = f"https://t.me/{bot_username}?start={referral_code}"
            rows: List[List[InlineKeyboardButton]] = [
                [InlineKeyboardButton(tr("🔗 Share Referral Link"), url=referral_link)]
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
                InlineKeyboardButton(tr("Back"), callback_data="back"),
                InlineKeyboardButton(tr("Exit"), callback_data="exit"),
            ])

            # 9) Send / edit
            await reply_func(
                "\n".join(lines),
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(rows),
            )

        except Exception as exc:
            await self.error_handler.handle(update, context, exc, context_name="show_profile")





# from __future__ import annotations
# """
# Profile.py – profile handler with paginated multi‑level downline list.
# """

# import logging
# import math
# from typing import Dict, Any, List

# from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
# from telegram.ext import ContextTypes

# from language_Manager import TranslationManager
# from keyboards import TranslatedKeyboards
# from error_handler import ErrorHandler
# from myproject_database import Database
# from Referral_logic_code import ReferralManager
# from state_manager import push_state

# logger = logging.getLogger(__name__)

# PAGE_SIZE = 30  # members per page


# class ProfileHandler:
#     """Shows user profile with paginated downline."""

#     def __init__(
#         self,
#         db: Database,
#         referral_manager: ReferralManager,
#         keyboards: TranslatedKeyboards,
#         translation_manager: TranslationManager,
#         error_handler: ErrorHandler,
#     ) -> None:
#         self.db = db
#         self.referral_manager = referral_manager
#         self.keyboards = keyboards
#         self.translation_manager = translation_manager
#         self.error_handler = error_handler
#         self.logger = logging.getLogger(self.__class__.__name__)

#     # ───────────────────────────────────── Telegram entry ────────────────────

#     async def show_profile(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
#         """Handles both /profile messages and pagination callback queries."""
#         try:
            
#             # ───➤ ست‌کردن state برای نمایش پروفایل
#             push_state(context, "showing_profile")
#             context.user_data['state'] = "showing_profile"            
            
#             # Detect whether this is an initial message or a callback
#             if update.callback_query:
#                 query = update.callback_query
#                 await query.answer()
#                 chat_id = query.from_user.id
#                 # callback_data pattern: profile_page_{n}
#                 page = int(query.data.rsplit("_", 1)[-1])
#                 reply_func = query.edit_message_text
#             else:
#                 chat_id = update.effective_chat.id
#                 page = 1
#                 reply_func = update.message.reply_text

#             # -----------------------------------------------------------------
#             # Fetch profile and paginated downline
#             # -----------------------------------------------------------------
#             profile: Dict[str, Any] = await self.referral_manager.get_profile(chat_id)
#             if not profile:
#                 msg_en = "You don’t have a profile yet. Please join the plan first."
#                 await reply_func(
#                     await self.translation_manager.translate_for_user(msg_en, chat_id),
#                     reply_markup=await self.keyboards.build_back_exit_keyboard(chat_id),
#                 )
#                 return

#             ref_code: str = profile["referral_code"]
#             member_no: int = profile["member_no"]
#             tokens: int = profile.get("tokens", 0)
#             commission: float = profile.get("commission_usd", 0.0)

#             downline_data = await self.referral_manager.get_downline_paginated(
#                 chat_id, page=page, page_size=PAGE_SIZE
#             )
#             members: List[Dict[str, Any]] = downline_data["members"]
#             total: int = downline_data["total"]

#             # -----------------------------------------------------------------
#             # Build message (English → translated later)
#             # -----------------------------------------------------------------
#             lines = [
#                 "<b>Your Profile</b>",
#                 f"• Member No: <b>{member_no}</b>",
#                 f"• Code: <code>{ref_code}</code>",
#                 f"• Tokens: <b>{tokens}</b>",
#                 f"• Pending Commission: <b>${commission:.2f}</b>",
#                 f"• Down-line Count: <b>{total}</b>",
#             ]

#             if total:
#                 lines.append(
#                     f"\n<b>Your Referrals (Page {page}/{math.ceil(total / PAGE_SIZE)}):</b>"
#                 )
#                 start_index = (page - 1) * PAGE_SIZE + 1
#                 for i, member in enumerate(members, start_index):
#                     lines.append(
#                         f"{i}. {member['first_name']} — <code>{member['referral_code']}</code>"
#                     )

#             msg_en = "\n".join(lines)
#             msg_final = await self.translation_manager.translate_for_user(msg_en, chat_id)

#             # -----------------------------------------------------------------
#             # Inline keyboard: share link + pagination controls
#             # -----------------------------------------------------------------
#             bot_username = context.bot.username
#             referral_link = f"https://t.me/{bot_username}?start={ref_code}"

#             rows: List[List[InlineKeyboardButton]] = [
#                 [InlineKeyboardButton("🔗 Share Referral Link", url=referral_link)]
#             ]
#             nav_row: List[InlineKeyboardButton] = []
#             if page > 1:
#                 nav_row.append(
#                     InlineKeyboardButton("⬅️ Prev", callback_data=f"profile_page_{page - 1}")
#                 )
#             if page * PAGE_SIZE < total:
#                 nav_row.append(
#                     InlineKeyboardButton("Next ➡️", callback_data=f"profile_page_{page + 1}")
#                 )
#             if nav_row:
#                 rows.append(nav_row)

#             inline_kb = InlineKeyboardMarkup(rows)

#             await reply_func(
#                 msg_final,
#                 parse_mode="HTML",
#                 reply_markup=inline_kb,
#             )

#         except Exception as e:
#             await self.error_handler.handle(update, context, e, context_name="show_profile")

