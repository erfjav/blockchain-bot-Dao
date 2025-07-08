

# help_and_support/__init__.py

"""
This package contains modules for user help and support functionality,
including FAQ handlers, user assistance, and support messaging for the bot.
"""

from .HelpHandler import HelpHandler
from .support_handler import SupportHandler

# Define what is available for import when using `from help_and_support import *`
__all__ = [
    "HelpHandler",
    "SupportHandler",
]
