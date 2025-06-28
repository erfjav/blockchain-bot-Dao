


# language_Manager.py

class TranslationManager:
    def __init__(self, db, translator):
        self.db = db
        self.translator = translator

    async def get_translated_message(self, text: str, user_lang: str) -> str:
        if user_lang.lower() == "en":
            return text

        cached_translation = await self.db.get_cached_translation(text, user_lang)
        if cached_translation is not None:
            return cached_translation

        translated_text = await self.translator.translate_text(text, user_lang)
        return translated_text

    async def translate_for_user(self, text: str, chat_id: int) -> str:
        """
        ترجمه پیام برای کاربر با chat_id مشخص.
        زبان کاربر از دیتابیس گرفته می‌شه و اگه نبود، انگلیسی در نظر گرفته می‌شه.
        """
        user_lang = await self.db.get_user_language(chat_id)
        if not user_lang:
            user_lang = 'en'
        return await self.get_translated_message(text, user_lang)
