

from __future__ import annotations
import os
from typing import List, TYPE_CHECKING

from telegram import KeyboardButton, ReplyKeyboardMarkup

# اگر از config مرکزی استفاده می‌کنی:
from config import ADMIN_USER_IDS

if TYPE_CHECKING:
    from translation import SimpleTranslator
    from myproject_database import Database




class TranslatedKeyboards:
    def __init__(self, db: Database, translator: SimpleTranslator):
        """
        :param db: پایگاه داده برای دریافت زبان کاربر
        :param translator: یک کلاس ترجمه مثل SimpleTranslator که متدی به نام translate_text دارد
        """
        self.db = db
        self.translator = translator

    # ----------------- منطق ترجمه دکمه‌ها -----------------
    async def _translate_buttons(
        self,
        raw_buttons: List[List[str]],
        user_lang: str,
        resize: bool = True,
        one_time: bool = False
    ) -> ReplyKeyboardMarkup:
        """
        تمام دکمه‌ها را به زبان کاربر ترجمه می‌کند (هیچ استثنایی وجود ندارد).
        """
        translated_buttons = []
        for row in raw_buttons:
            new_row = []
            for text_en in row:
                text_translated = await self.translator.translate_text(text_en, user_lang)
                new_row.append(KeyboardButton(text_translated))
            translated_buttons.append(new_row)

        return ReplyKeyboardMarkup(
            translated_buttons, resize_keyboard=resize, one_time_keyboard=one_time
        )


    # ----------------- ترجمه و ساخت کیبورد -----------------
    async def build_keyboard_for_user(
        self,
        raw_buttons: List[List[str]],
        chat_id: int,
        resize: bool = True,
        one_time: bool = False
    ) -> ReplyKeyboardMarkup:
        """
        بر اساس chat_id زبان کاربر را می‌گیرد و کیبورد ترجمه‌شده می‌سازد.
        """
        user_lang = await self.db.get_user_language(chat_id)
        if not user_lang:
            user_lang = 'en'
        return await self._translate_buttons(raw_buttons, user_lang, resize, one_time)

    # ----------------- منوی اصلی نسخه ۲ -----------------
    def main_menu_keyboard_v2(self) -> List[List[str]]:
        """
        لیست دکمه‌های منوی اصلی به زبان انگلیسی (برای ترجمه شدن خودکار)
        """
        return [
            ["🚀 Start", "📘 Guide"],
            ["💰 Trade", "💳 Payment"],
            ["🎧 Support", "📊 Token Price"],
            ["👤 Profile", "🌐 Language"],
            ["🔄 Convert Token", "💼 Earn Money"]
        ]

    async def build_main_menu_keyboard_v2(
        self,
        chat_id: int,
        resize: bool = True,
        one_time: bool = False
    ) -> ReplyKeyboardMarkup:
        """
        ساخت کیبورد ترجمه‌شده منوی اصلی نسخه ۲ (با دکمه Admin برای مدیر)
        """
        raw_buttons = self.main_menu_keyboard_v2()
        if chat_id == ADMIN_USER_IDS:
            raw_buttons.append(["🛠 Admin Panel"])
        return await self.build_keyboard_for_user(raw_buttons, chat_id, resize, one_time)

    def trade_menu_keyboard(self) -> List[List[str]]:
        """
        دکمه‌های کیبورد بخش 💰 Trade را بازمی‌گرداند.
        """
        return [
            ["🛒 Buy", "💸 Sell"],
            ["⬅️ Back", "➡️ Exit"]
        ]

    async def build_trade_menu_keyboard(
        self, chat_id: int, resize: bool = True, one_time: bool = True
    ) -> ReplyKeyboardMarkup:
        """
        ساخت کیبورد ترجمه‌شده‌ی منوی 💰 Trade
        """
        raw_buttons = self.trade_menu_keyboard()
        return await self.build_keyboard_for_user(raw_buttons, chat_id, resize, one_time)

    def back_exit_keyboard(self) -> List[List[str]]:
        """
        کیبورد ساده شامل فقط دکمه‌های Back و Exit.
        """
        return [
            ["⬅️ Back", "➡️ Exit"]
        ]

    async def build_back_exit_keyboard(
        self, chat_id: int, resize: bool = True, one_time: bool = False
    ) -> ReplyKeyboardMarkup:
        """
        ساخت کیبورد ترجمه‌شده فقط با دکمه‌های Back و Exit.
        """
        raw_buttons = self.back_exit_keyboard()
        return await self.build_keyboard_for_user(raw_buttons, chat_id, resize, one_time)
