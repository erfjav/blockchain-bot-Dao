

# translation.py

from __future__ import annotations
import logging
from typing import Optional, TYPE_CHECKING
from core.models import Model

if TYPE_CHECKING:
    from myproject_database import Database


logger = logging.getLogger(__name__)


class SimpleTranslator:
    """
    یک کلاس حرفه‌ای برای ترجمه چندزبانه‌ی متن‌ها و دکمه‌های UI در ربات تلگرام.
    از LLM برای ترجمه استفاده می‌کند و ترجمه‌ها را در کش دیتابیس ذخیره می‌کند.
    """

    def __init__(self, model_type: str = "gpt-4o", db: Optional[Database] = None):
        self.db: Optional[Database] = db
        self.model_type = model_type
        self.model = Model(model_type=self.model_type)

    async def detect_language(self, text: str) -> str:
        """
        تشخیص زبان متن (بازگشت کد زبان مانند 'fa' یا 'en')
        اگر متن نامفهوم یا خالی باشد، 'en' برگردانده می‌شود.
        """
        if not text or len(text.strip()) == 0:
            return "en"

        try:
            prompt = (
                "Detect the language of the following text and return ONLY the ISO 639-1 code (e.g., 'en', 'fa', 'ar'). "
                "If the text is gibberish or invalid, return 'invalid'.\n\n"
                f"Text: {text}\n\nAnswer:"
            )
            response = await self.model.generate_response(prompt=prompt)
            lang_code = response.strip().lower().split()[0]
            return lang_code[:2]
        except Exception as e:
            logger.error(f"Error detecting language: {e}")
            return "en"

    async def translate_text(self, text: str, target_lang: str) -> str:
        """
        ترجمه‌ی دقیق و حرفه‌ای متن به زبان مورد نظر برای استفاده در UI ربات.
        ترجمه‌ها کش می‌شوند و از LLM برای دقت بالا استفاده می‌شود.
        """
        if not text or not target_lang or target_lang.lower() == "en":
            return text

        try:
            if self.db:
                cached = await self.db.get_cached_translation(text, target_lang)
                if cached:
                    return cached

            prompt = (
                f"Translate the following text to {target_lang}:\n\n"
                f"{text}\n\n"
                f"Context: This text will be used in a multilingual Telegram bot. "
                f"It may be a UI element (button, menu, label) or a user-facing message.\n\n"
                f"Translation Instructions:\n"
                f"1. Preserve emojis, symbols, punctuation, and formatting (e.g., <b>…</b>) exactly as they are.\n"
                f"2. Use natural, concise UI-friendly terms common in {target_lang} for buttons like 'Back', 'Help', etc.\n"
                f"3. Do not use literal or robotic translations.\n"
                f"4. Avoid translating terms like 'gpt-4o', 'Claude', 'FLUX', 'PDF', or commands like 'page 2'.\n"
                f"5. For terms like 'My Plan', translate with the meaning of subscription, not personal schedule.\n"
                f"6. For anything with the word 'ticket', assume it's a support ticket.\n"
                f"7. Return ONLY the translated version of the text without any explanation or comments.\n"
                f"8. Do not translate brand names or technical model identifiers.\n"
                f"9. Keep numbers in English format (0-9).\n"
                f"10. Translations should be consistent across the bot (e.g., use same word for 'Plan' everywhere).\n"
            )

            response = await self.model.generate_response(prompt=prompt)
            translation = response.strip()

            if self.db:
                await self.db.update_translation_cache(text, target_lang, translation)

            return translation
        except Exception as e:
            logger.error(f"Error translating text: {e}")
            return text
