

# bot_ui/__init__.py

"""
This package contains modules related to the Telegram bot UI elements,
including keyboards and translation management.
"""

from .keyboards import TranslatedKeyboards
from .Translated_Inline_Keyboards import TranslatedInlineKeyboards
from .language_Manager import TranslationManager
from .translation import SimpleTranslator

# Define what is available for import when using `from bot_ui import *`
__all__ = [
    "TranslatedKeyboards",
    "TranslatedInlineKeyboards",
    "TranslationManager",
    "SimpleTranslator",
]
