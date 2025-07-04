

# admin_handler.py
# ────────────────────────────────────────────────────────────────────────
from __future__ import annotations

import logging
from decimal import Decimal

from telegram import Update
from telegram.ext import ContextTypes, CommandHandler

from dynamic_price_provider import DynamicPriceProvider
from language_Manager import TranslationManager
from config import ADMIN_USER_IDS


class AdminHandler:
    """فرمان‌های مدیریتی مربوط به قیمت پویا و تنظیمات توکن."""

    def __init__(
        self,
        price_provider: DynamicPriceProvider,
        translation_manager: TranslationManager,
    ) -> None:
        self.price_provider = price_provider
        self.translation_manager = translation_manager
        self.admin_ids = set(ADMIN_USER_IDS)
        self.logger = logging.getLogger(self.__class__.__name__)

    # ─────────────────────── public commands ────────────────────────────
    async def price_snapshot_cmd(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """‎/price_snapshot → وضعیت جاری ولت + قیمت."""
        if not self._is_admin(update):  # مجوز
            return

        snap = await self.price_provider.snapshot()
        msg_en = (
            "📊 <b>Token price snapshot</b>\n"
            f"• Wallet balance: <code>${snap['wallet_balance_usd']:.2f}</code>\n"
            f"• Circulating supply: <code>{snap['circulating_supply']:,}</code>\n"
            f"• Price: <b>${snap['price_usd']:.6f}</b>"
        )
        await update.message.reply_text(
            await self.translation_manager.translate_for_user(
                msg_en, update.effective_chat.id
            ),
            parse_mode="HTML",
        )

    async def set_total_supply_cmd(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """‎/set_total_supply 15000000 → اصلاح سقف عرضه."""
        if not self._is_admin(update):
            return

        if not context.args:
            await update.message.reply_text("Usage: /set_total_supply 15000000")
            return

        try:
            new_supply = int(context.args[0])
            if new_supply <= 0:
                raise ValueError
        except ValueError:
            await update.message.reply_text("Send a positive integer.")
            return

        # تغییر مقدار در runtime
        self.price_provider.TOTAL_SUPPLY = Decimal(new_supply)
        # پاک کردن کش تا فوراً اعمال شود
        await self._flush_cache()
        await update.message.reply_text(
            f"✅ TOTAL_SUPPLY set to {new_supply:,} tokens."
        )

    async def flush_price_cache_cmd(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """‎/flush_price_cache → پاک‌کردن کش قیمت (برای تست)."""
        if not self._is_admin(update):
            return
        await self._flush_cache()
        await update.message.reply_text("🗑 Price cache cleared.")

    # ─────────────────────── helper utilities ───────────────────────────
    async def _flush_cache(self) -> None:
        self.price_provider._cache_price = None  # noqa: SLF001
        self.price_provider._cache_ts = 0

    def _is_admin(self, update: Update) -> bool:
        chat_id = update.effective_chat.id
        if chat_id not in self.admin_ids:
            self.logger.warning("Unauthorized admin command from %s", chat_id)
            return False
        return True

    # ─────────────────────── handler factory ────────────────────────────
    def get_handlers(self) -> list[CommandHandler]:
        """استفاده در setup: application.add_handlers(...)."""
        return [
            CommandHandler("price_snapshot", self.price_snapshot_cmd),
            CommandHandler("set_total_supply", self.set_total_supply_cmd),
            CommandHandler("flush_price_cache", self.flush_price_cache_cmd),
        ]



# from telegram.ext import CommandHandler
# from telegram import Update
# from telegram.ext import ContextTypes
# from price_provider import DynamicPriceProvider
# from language_Manager import TranslationManager
# from config import ADMIN_USER_IDS

# class AdminHandler:
#     def __init__(self, price_provider:DynamicPriceProvider, translation_manager: TranslationManager):
#         self.price_provider = price_provider
#         self.translation_manager = translation_manager
#         self.admin_ids = ADMIN_USER_IDS

#     async def set_price_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
#         chat_id = update.effective_chat.id
#         if chat_id not in self.admin_ids:
#             return

#         if not context.args:
#             await update.message.reply_text("Usage: /set_price 1.75")
#             return
#         try:
#             new_price = float(context.args[0])
#             await self.price_provider.set_price(new_price)
#             await update.message.reply_text(f"✅ Price set to ${new_price:.4f}")
#         except ValueError:
#             await update.message.reply_text("Send a valid positive number.")
