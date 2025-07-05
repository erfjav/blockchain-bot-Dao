

from __future__ import annotations
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from typing import List, TYPE_CHECKING

if TYPE_CHECKING:
    # این import‌ها تنها برای تایپ هینتینگ استفاده می‌شوند و در زمان اجرا وارد نمی‌شوند.
    from .translation import SimpleTranslator
    from myproject_database import Database

model_names = {
    "gpt-4o", "🎨 Gemini 2.5 Flash", "⚖️ GPT-4.1 Mini",
    "Grok 3 Mini Beta", "Gemini 2.5 Pro", "Llama 4 Maverick",
    "Llama 4 Scout", "🧠 GPT-o3", "🤖 Grok 3 Beta", "🆓 Freemium",
    "⚡o3 Mini High", "⚡o4 Mini High", "🧠 Asha Reasoning",
    "🚀 Gemini 2.5 Pro Vision", "⚡ Gemini 2.5 Flash Vision", "🧠 GPT-4o Vision"
}


class TranslatedInlineKeyboards:
    def __init__(self, db: Database, translator: SimpleTranslator, exceptions: List[str] = None):
        """
        :param translator: نمونه‌ای از SimpleTranslator که متد translate_text(text, target_lang)
                           دارد.
        :param exceptions: لیستی از متونی که نباید ترجمه شوند.
        """
        self.translator = translator
        self.db = db
        # لیست استثنا: می‌توانید به دلخواه خود مقادیر اضافه یا تغییر دهید.
        self.exceptions = exceptions if exceptions is not None else model_names

    async def _translate_inline_buttons(
        self,
        raw_buttons: List[List[InlineKeyboardButton]],
        user_lang: str
    ) -> InlineKeyboardMarkup:
        """
        یک لیست دوبعدی از دکمه‌های اینلاین دریافت می‌کند و
        متن دکمه‌ها را به زبان کاربر ترجمه می‌کند.
        اگر دکمه URL داشته باشد، آن را حفظ می‌کند.
        """
        translated_buttons: List[List[InlineKeyboardButton]] = []
        for row in raw_buttons:
            new_row: List[InlineKeyboardButton] = []
            for button in row:
                # متن انگلیسی اصلی
                text_en = button.text

                # ترجمه یا حفظ استثنا
                if text_en in self.exceptions:
                    text_translated = text_en
                else:
                    text_translated = await self.translator.translate_text(text_en, user_lang)

                # بازسازی دکمه با حفظ callback_data و url
                new_row.append(
                    InlineKeyboardButton(
                        text_translated,
                        callback_data=button.callback_data,
                        url=button.url
                    )
                )
            translated_buttons.append(new_row)

        return InlineKeyboardMarkup(translated_buttons)


    # async def _translate_inline_buttons(self, raw_buttons: List[List[InlineKeyboardButton]], user_lang: str) -> InlineKeyboardMarkup:
    #     """
    #     یک لیست دوبعدی از دکمه‌های اینلاین دریافت می‌کند و متن دکمه‌های آن‌ها را به زبان کاربر ترجمه می‌کند.
    #     اگر متن دکمه در لیست استثنا باشد، بدون ترجمه در کیبورد قرار می‌گیرد.
    #     """
    #     translated_buttons = []
    #     for row in raw_buttons:
    #         new_row = []
    #         for button in row:
    #             text_en = button.text
    #             # اگر متن دکمه در لیست استثنا باشد، ترجمه انجام نمی‌دهیم.
    #             if text_en in self.exceptions:
    #                 text_translated = text_en
    #             else:
    #                 # اینجا نیازی به import محلی نیست چون self.translator از قبل در سازنده مقداردهی شده است.
    #                 # اما اگر در آینده مشکلی ایجاد شد، می‌توانید import را در داخل این بلوک قرار دهید.
    #                 text_translated = await self.translator.translate_text(text_en, user_lang)
    #             new_button = InlineKeyboardButton(text=text_translated, callback_data=button.callback_data)
    #             new_row.append(new_button)
    #         translated_buttons.append(new_row)
    #     return InlineKeyboardMarkup(translated_buttons)

    async def build_inline_keyboard_for_user(self, raw_buttons: List[List[InlineKeyboardButton]], user_id: int) -> InlineKeyboardMarkup:
        """
        ساخت InlineKeyboardMarkup برای کاربر با chat_id مشخص.
        دکمه‌ها به زبان کاربر ترجمه می‌شوند و در صورت عدم وجود زبان، از انگلیسی به عنوان پیش‌فرض استفاده می‌شود.
        """
        user_lang = await self.db.get_user_language(user_id)
        if not user_lang:
            user_lang = 'en'
        return await self._translate_inline_buttons(raw_buttons, user_lang)



