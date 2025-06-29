
from __future__ import annotations
"""
Profile.py – profile handler with paginated multi‑level downline list.
"""

import logging
import math
from typing import Dict, Any, List

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from language_Manager import TranslationManager
from keyboards import TranslatedKeyboards
from error_handler import ErrorHandler
from myproject_database import Database
from Referral_logic_code import ReferralManager
from state_manager import push_state

logger = logging.getLogger(__name__)

PAGE_SIZE = 30  # members per page


class ProfileHandler:
    """Shows user profile with paginated downline."""

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

    # ───────────────────────────────────── Telegram entry ────────────────────

    async def show_profile(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handles both /profile messages and pagination callback queries."""
        try:
            
            # ───➤ ست‌کردن state برای نمایش پروفایل
            push_state(context, "showing_profile")
            context.user_data['state'] = "showing_profile"            
            
            # Detect whether this is an initial message or a callback
            if update.callback_query:
                query = update.callback_query
                await query.answer()
                chat_id = query.from_user.id
                # callback_data pattern: profile_page_{n}
                page = int(query.data.rsplit("_", 1)[-1])
                reply_func = query.edit_message_text
            else:
                chat_id = update.effective_chat.id
                page = 1
                reply_func = update.message.reply_text

            # -----------------------------------------------------------------
            # Fetch profile and paginated downline
            # -----------------------------------------------------------------
            profile: Dict[str, Any] = await self.referral_manager.get_profile(chat_id)
            if not profile:
                msg_en = "You don’t have a profile yet. Please join the plan first."
                await reply_func(
                    await self.translation_manager.translate_for_user(msg_en, chat_id),
                    reply_markup=await self.keyboards.build_back_exit_keyboard(chat_id),
                )
                return

            ref_code: str = profile["referral_code"]
            member_no: int = profile["member_no"]
            tokens: int = profile.get("tokens", 0)
            commission: float = profile.get("commission_usd", 0.0)

            downline_data = await self.referral_manager.get_downline_paginated(
                chat_id, page=page, page_size=PAGE_SIZE
            )
            members: List[Dict[str, Any]] = downline_data["members"]
            total: int = downline_data["total"]

            # -----------------------------------------------------------------
            # Build message (English → translated later)
            # -----------------------------------------------------------------
            lines = [
                "<b>Your Profile</b>",
                f"• Member No: <b>{member_no}</b>",
                f"• Code: <code>{ref_code}</code>",
                f"• Tokens: <b>{tokens}</b>",
                f"• Pending Commission: <b>${commission:.2f}</b>",
                f"• Down-line Count: <b>{total}</b>",
            ]

            if total:
                lines.append(
                    f"\n<b>Your Referrals (Page {page}/{math.ceil(total / PAGE_SIZE)}):</b>"
                )
                start_index = (page - 1) * PAGE_SIZE + 1
                for i, member in enumerate(members, start_index):
                    lines.append(
                        f"{i}. {member['first_name']} — <code>{member['referral_code']}</code>"
                    )

            msg_en = "\n".join(lines)
            msg_final = await self.translation_manager.translate_for_user(msg_en, chat_id)

            # -----------------------------------------------------------------
            # Inline keyboard: share link + pagination controls
            # -----------------------------------------------------------------
            bot_username = context.bot.username
            referral_link = f"https://t.me/{bot_username}?start={ref_code}"

            rows: List[List[InlineKeyboardButton]] = [
                [InlineKeyboardButton("🔗 Share Referral Link", url=referral_link)]
            ]
            nav_row: List[InlineKeyboardButton] = []
            if page > 1:
                nav_row.append(
                    InlineKeyboardButton("⬅️ Prev", callback_data=f"profile_page_{page - 1}")
                )
            if page * PAGE_SIZE < total:
                nav_row.append(
                    InlineKeyboardButton("Next ➡️", callback_data=f"profile_page_{page + 1}")
                )
            if nav_row:
                rows.append(nav_row)

            inline_kb = InlineKeyboardMarkup(rows)

            await reply_func(
                msg_final,
                parse_mode="HTML",
                reply_markup=inline_kb,
            )

        except Exception as e:
            await self.error_handler.handle(update, context, e, context_name="show_profile")

