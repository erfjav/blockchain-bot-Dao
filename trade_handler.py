

from __future__ import annotations
"""
trade_handler.py – 💰 Trade module (Buy / Sell) for your Telegram bot
--------------------------------------------------------------------
منطق کامل خرید و فروش توکن با صفحهٔ گفتگو (ConversationHandler).

◀️ جریان «فروش»
   1. کاربر «💸 Sell» را می‌زند → موجودی و قیمت فعلی نمایش داده می‌شود.
   2. بات مقدار توکنِ موردنظر برای فروش را می‌پرسد.
   3. پس از دریافت عدد، درخواستی در کانال TRADE_CHANNEL ارسال می‌شود
      شامل ID‌ کاربر (member_no یا referral_code)، تعداد توکن و دکمهٔ پشتیبانی.

▶️ جریان «خرید»
   1. کاربر «🛒 Buy» را می‌زند → قیمت فعلی نمایش داده می‌شود.
   2. بات تعداد توکن موردنیاز را می‌پرسد.
   3. پس از دریافت عدد، قیمت پیشنهادیِ کاربر برای هر توکن را می‌پرسد.
   4. درخواستی در کانال TRADE_CHANNEL ارسال می‌شود شامل تعداد، قیمت پیشنهادی و دکمهٔ پشتیبانی.

پیش‌نیازها
-----------
• در settings یا env:  TRADE_CHANNEL_ID  ,  SUPPORT_USER_USERNAME
• وابستگی به:
    - TranslatedKeyboards       → build_trade_menu_keyboard / build_back_exit_keyboard
    - TranslationManager       → translate_for_user()
    - Database                 → get_user_balance(user_id)  (async)
    - price_provider.get_price() (async یا sync) → قیمت توکن به دلار
    - ReferralManager.get_profile(user_id)      → برای member_no یا referral_code
"""

import logging
import os, re
from typing import Tuple, List
from datetime import datetime
from telegram import (
    Update,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
)
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)

from keyboards import TranslatedKeyboards
from language_Manager import TranslationManager
from error_handler import ErrorHandler
from Referral_logic_code import ReferralManager
from price_provider import PriceProvider          # ← NEW

from myproject_database import Database  # Async wrapper
from state_manager import push_state, pop_state
from blockchain_client import BlockchainClient

from config import TRADE_WALLET_ADDRESS as TRON_WALLET

TRADE_CHANNEL_ID = int(os.getenv("TRADE_CHANNEL_ID", "0"))
SUPPORT_USER_USERNAME = os.getenv("SUPPORT_USER_USERNAME", "YourSupportUser")

# Conversation states
SELL_AMOUNT, SELL_PRICE , BUY_AMOUNT, BUY_PRICE = range(4)

logger = logging.getLogger(__name__)


class TradeHandler:
    """Registers handlers for the 💰 Trade flow."""

    def __init__(
        self,
        db: Database,        
        keyboards: TranslatedKeyboards,
        translation_manager: TranslationManager,
        price_provider: PriceProvider,
        referral_manager: ReferralManager,
        blockchain : BlockchainClient,
        error_handler: ErrorHandler,
        
    ) -> None:
        
        self.db = db
        self.keyboards = keyboards
        self.translation_manager = translation_manager
        self.price_provider = price_provider
        self.referral_manager = referral_manager
        self.blockchain= blockchain
        self.error_handler = error_handler
        
        self.logger = logging.getLogger(self.__class__.__name__)

    # ─────────────────── helper utilities ────────────────────────────────────────────────────────

    async def _get_user_identifier(self, user_id: int) -> str:
        """Return member_no if available else referral_code as display ID."""
        profile = await self.db.get_profile(user_id)
        if not profile:
            return str(user_id)
        return str(profile.get("member_no") or profile.get("referral_code") or user_id)
    
    #---------------------------------------------------------------------
    def _support_inline_keyboard(self) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            [[InlineKeyboardButton("🆘 Support", url=f"https://t.me/{SUPPORT_USER_USERNAME}")]]
        )

    # ────────────────────────── entry points ─────────────────────────────────────────────────────────────
    async def trade_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        نمایش منوی معامله (خرید/فروش)
        • کاربر را وارد بخش Trading می‌کند
        • توضیح مختصر دربارهٔ امکانات این بخش
        • نمایش دکمه‌های Buy و Sell
        """
        try:
            # ───➤ ست‌کردن state برای نمایش منوی Trade
            push_state(context, "trade_menu")
            context.user_data['state'] = "trade_menu"

            chat_id = update.effective_chat.id
            kb: ReplyKeyboardMarkup = await self.keyboards.build_trade_menu_keyboard(chat_id)

            # ───➤ متن خوش‌آمدگویی و راهنمایی
            msg_en = (
                "<b>🪙 Welcome to the Trade Menu!</b>\n\n"
                "You are now in the <b>Trading Section</b> of the bot. Here you can:\n"
                "• <b>🛒 Buy</b> tokens at the current market price\n"
                "• <b>💸 Sell</b> tokens from your balance\n\n"
                "Please tap one of the buttons below to proceed with your trade."
            )

            await update.message.reply_text(
                await self.translation_manager.translate_for_user(msg_en, chat_id),
                parse_mode="HTML",
                reply_markup=kb,
            )

            return

        except Exception as e:
            # در صورت بروز خطا، به ErrorHandler ارجاع بده
            await self.error_handler.handle( update, context, e, context_name="trade_menu")

    # ───────────────────── SELL FLOW ─────────────────────────────────────────────────
    async def sell_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        شروع فرایند فروش ـ مرحلهٔ گرفتن مقدار
        """
        try:
            push_state(context, "awaiting_sell_amount")
            context.user_data["state"] = "awaiting_sell_amount"

            chat_id   = update.effective_chat.id
            balance   = await self.db.get_user_balance(chat_id)      # باید موجود باشد
            price_now = await self.price_provider.get_price()

            msg_en = (
                f"Current token price: ${price_now:.4f}\n"
                f"Your balance: {balance} tokens\n\n"
                "How many tokens do you want to sell?"
            )
            await update.message.reply_text(
                await self.translation_manager.translate_for_user(msg_en, chat_id),
                reply_markup=await self.keyboards.build_back_exit_keyboard(chat_id),
            )
        except Exception as e:
            await self.error_handler.handle(update, context, e, context_name="sell_start")

    #--------------------------------------------------------------------------

    # -----------------------------------------------------------------
    async def sell_amount(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        گام اول فروش: دریافت تعداد، سپس عبور به گام قیمت.
        """
        try:
            chat_id = update.effective_chat.id
            txt     = update.message.text.strip()

            # ── اعتبارسنجی عدد ─────────────────────────────────────────
            if not txt.isdigit() or int(txt) <= 0:
                await update.message.reply_text(
                    await self.translation_manager.translate_for_user("Please send a valid number.", chat_id)
                )
                return  # در همان state `awaiting_sell_amount` می‌مانیم

            amount = int(txt)
            context.user_data["sell_amount"] = amount

            # ── انتقال state → awaiting_sell_price ─────────────────────
            pop_state(context)                               # خارج از awaiting_sell_amount
            push_state(context, "awaiting_sell_price")
            context.user_data["state"] = "awaiting_sell_price"

            # ── پرسش قیمت از فروشنده ─────────────────────────────────
            await update.message.reply_text(
                await self.translation_manager.translate_for_user(
                    "At what price (USD) per token are you willing to sell?", chat_id
                ),
                reply_markup=await self.keyboards.build_back_exit_keyboard(chat_id),
            )

        except Exception as e:
            await self.error_handler.handle(update, context, e, context_name="sell_amount")
    
    
    # async def sell_amount(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    #     try:
    #         chat_id = update.effective_chat.id
    #         txt     = update.message.text.strip()

    #         if not txt.isdigit() or int(txt) <= 0:
    #             await update.message.reply_text(
    #                 await self.translation_manager.translate_for_user("Please send a valid number.", chat_id)
    #             )
    #             return  # در همان state می‌مانیم

    #         # مقدار را ذخیره می‌کنیم و state بعدی را ست می‌کنیم
    #         context.user_data["sell_amount"] = int(txt)
    #         pop_state(context)                      # خارج از awaiting_sell_amount
    #         push_state(context, SELL_PRICE)
    #         context.user_data["state"] = SELL_PRICE

    #         await update.message.reply_text(
    #             await self.translation_manager.translate_for_user(
    #                 "At what price (USD) per token are you willing to sell?", chat_id
    #             ),
    #             reply_markup=await self.keyboards.build_back_exit_keyboard(chat_id),
    #         )

    #     except Exception as e:
    #         await self.error_handler.handle(update, context, e, context_name="sell_amount")
            
    # #-------------------------------------------------------------------------
    
    # -----------------------------------------------------------------
    async def sell_price(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        گام دومِ فروش: دریافت قیمت از فروشنده، ثبت Order، ارسال پیام کانال
        """
        try:
            chat_id = update.effective_chat.id
            txt     = update.message.text.strip()

            # ── اعتبارسنجی قیمت ───────────────────────────────────────
            try:
                price_per_token = float(txt)
                if price_per_token <= 0:
                    raise ValueError
            except ValueError:
                await update.message.reply_text(
                    await self.translation_manager.translate_for_user(
                        "Please send a valid price.", chat_id
                    )
                )
                return  # در همان state می‌مانیم

            amount     = context.user_data.get("sell_amount", 0)
            identifier = await self._get_user_identifier(chat_id)

            # ── پیام کانال + دکمهٔ Buy ────────────────────────────────
            text_channel = (
                f"🚨 SELL Request\n"
                f"ID: {identifier}\n"
                f"Amount: {amount} tokens\n"
                f"Price: ${price_per_token:.4f} per token\n\n"
                "Contact support to proceed:"
            )
            msg = await update.get_bot().send_message(      # ← msg برای message_id
                chat_id=TRADE_CHANNEL_ID,
                text=text_channel,
                reply_markup=self._support_inline_keyboard(),
            )

            # ── ذخیرهٔ سفارش در دیتابیس ───────────────────────────────
            order_id = await self.db.create_sell_order(
                {
                    "seller_id":      chat_id,
                    "amount":         amount,
                    "price":          price_per_token,
                    "channel_msg_id": msg.message_id,
                }
            )

            # ── افزودن دکمهٔ «🛒 Buy» به پیام کانال ───────────────────
            buy_kb = InlineKeyboardMarkup(
                [
                    [InlineKeyboardButton("🛒 Buy", callback_data=f"buy_order_{order_id}")],
                    [
                        InlineKeyboardButton(
                            "SOS Support", url=f"https://t.me/{SUPPORT_USER_USERNAME}"
                        )
                    ],
                ]
            )
            await msg.edit_reply_markup(buy_kb)

            # ── تأیید برای فروشنده ───────────────────────────────────
            await update.message.reply_text(
                await self.translation_manager.translate_for_user(
                    "Your sell request has been submitted to support.", chat_id
                ),
                reply_markup=await self.keyboards.build_back_exit_keyboard(chat_id),
            )

            # ── پاک‌سازی state ───────────────────────────────────────
            pop_state(context)
            context.user_data.clear()

        except Exception as e:
            await self.error_handler.handle(update, context, e, context_name="sell_price")

    # ───────────────────────────────────────────────────────────────────
    async def buy_order_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        buyer_id = query.from_user.id

        order_id = int(query.data.split("_")[-1])
        order = await self.db.collection_orders.find_one({"order_id": order_id})
        if not order or order["status"] != "open":
            return await query.edit_message_reply_markup(None)   # Order closed / already taken

        if buyer_id == order.get("seller_id"):
            return await query.answer("You cannot buy your own order.", show_alert=True)

        total = order["amount"] * order["price"]
        context.user_data["pending_order"] = order_id
        context.user_data["state"] = "awaiting_trade_txid"

        # ── Send payment instructions to buyer ─────────────────────────
        text_en = (
            f"Total to pay: <b>${total:.2f}</b>\n"
            f"Send USDT-TRC20 to:\n<code>{TRON_WALLET}</code>\n\n"
            "After sending, press <b>I Paid</b> and submit the TXID."
        )
        kb = InlineKeyboardMarkup(
            [[InlineKeyboardButton("💳 I Paid", callback_data=f"paid_{order_id}")]]
        )
        await context.bot.send_message(
            chat_id=buyer_id,
            text=text_en,
            reply_markup=kb,
            parse_mode="HTML",
        )

        # ── Mark order as pending & store buyer_id ─────────────────────
        await self.db.collection_orders.update_one(
            {"order_id": order_id},
            {"$set": {
                "status":     "pending_payment",
                "buyer_id":   buyer_id,
                "updated_at": datetime.utcnow()
            }}
        )
   
    
    # # trade_handler.py  ───────────────────────────────────────────────
    # async def buy_order_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    #     query = update.callback_query
    #     await query.answer()
    #     buyer_id = query.from_user.id

    #     order_id = int(query.data.split("_")[-1])
    #     order = await self.db.collection_orders.find_one({"order_id": order_id})
    #     if not order or order["status"] != "open":
    #         return await query.edit_message_reply_markup(None)   # Order closed

    #     if buyer_id == order["seller_id"]:
    #         return await query.answer("You cannot buy your own order.", show_alert=True)

    #     total = order["amount"] * order["price"]
    #     context.user_data["pending_order"] = order_id
    #     context.user_data["state"] = "awaiting_trade_txid"

    #     text_en = (
    #         f"Total to pay: <b>${total:.2f}</b>\n"
    #         f"Send USDT-TRC20 to:\n<code>{TRON_WALLET}</code>\n\n"
    #         "After sending, press <b>I Paid</b> and submit the TXID."
    #     )
    #     kb = InlineKeyboardMarkup(
    #         [[InlineKeyboardButton("💳 I Paid", callback_data=f"paid_{order_id}")]]
    #     )
    #     await context.bot.send_message(
    #         chat_id=buyer_id,
    #         text=text_en,
    #         reply_markup=kb,
    #         parse_mode="HTML",
    #     )

    #     # وضعیت سفارش ← در انتظار پرداخت
    #     await self.db.collection_orders.update_one(
    #         {"order_id": order_id}, {"$set": {"status": "pending_payment"}}
    #     )
 
    # ─────────────────────────── BUY FLOW ─────────────────────────────────
    async def buy_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    
                # ───➤ ست‌کردن state برای انتظار مقدار خرید
        push_state(context, "awaiting_buy_amount")
        context.user_data['state'] = "awaiting_buy_amount"
        
        chat_id = update.effective_chat.id
        price = await self.price_provider.get_price()
        msg_en = (
            f"Current token price: ${price:.4f}\n\n"
            "How many tokens do you need?"
        )
        await update.message.reply_text(
            await self.translation_manager.translate_for_user(msg_en, chat_id),
            reply_markup=await self.keyboards.build_back_exit_keyboard(chat_id),
        )
        return BUY_AMOUNT
    
    # trade_handler.py  – فقط بخش‌های مهم
    #------------------------------------------------------------------------------------------------------
    async def buy_amount(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.effective_chat.id
        txt = update.message.text.strip()

        if not txt.isdigit() or int(txt) <= 0:
            await update.message.reply_text(
                await self.translation_manager.translate_for_user("Please send a valid number.", chat_id)
            )
            return  # همین state می‌ماند

        context.user_data["buy_amount"] = int(txt)
        await update.message.reply_text(
            await self.translation_manager.translate_for_user(
                "At what price (USD) per token are you willing to buy?", chat_id
            )
        )
        # فقط state را به‌روز کنید؛ نیازی به return مقدار خاص نیست
        context.user_data['state'] = 'awaiting_buy_price'
        push_state(context, 'awaiting_buy_price')


    # ---------------------------------------------------------------------------
    async def buy_price(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        گام دوم خرید: دریافت قیمت هر توکن، ایجاد BUY-Order و افزودن دکمه «💸 Sell».
        """
        try:
            chat_id = update.effective_chat.id
            txt     = update.message.text.strip()

            # ─── اعتبارسنجی قیمت ───────────────────────────────────────────
            try:
                price_per_token = float(txt)
                if price_per_token <= 0:
                    raise ValueError
            except ValueError:
                await update.message.reply_text(
                    await self.translation_manager.translate_for_user("Please send a valid price.", chat_id)
                )
                return  # همان state می‌مانیم

            amount     = context.user_data.get("buy_amount", 0)
            identifier = await self._get_user_identifier(chat_id)

            # ─── ارسال پیام به کانال ترید ─────────────────────────────────
            text_channel = (
                f"🚨 BUY Request\n"
                f"ID: {identifier}\n"
                f"Amount: {amount} tokens\n"
                f"Price: ${price_per_token:.4f} per token\n\n"
                "First seller to accept will receive USDT from escrow."
            )
            msg = await update.get_bot().send_message(
                chat_id=TRADE_CHANNEL_ID,
                text=text_channel,
                reply_markup=self._support_inline_keyboard(),
            )

            # ─── ایجاد رکورد Order در DB ─────────────────────────────────
            order_id = await self.db.create_buy_order(
                {
                    "buyer_id":      chat_id,
                    "amount":        amount,
                    "price":         price_per_token,
                    "channel_msg_id": msg.message_id,
                }
            )

            # ─── افزودن دکمه «💸 Sell» به پیام کانال ─────────────────────
            sell_kb = InlineKeyboardMarkup(
                [
                    [InlineKeyboardButton("💸 Sell", callback_data=f"sell_order_{order_id}")],
                    [
                        InlineKeyboardButton(
                            "SOS Support", url=f"https://t.me/{SUPPORT_USER_USERNAME}"
                        )
                    ],
                ]
            )
            await msg.edit_reply_markup(sell_kb)

            # ─── تأیید برای خریدار ───────────────────────────────────────
            await update.message.reply_text(
                await self.translation_manager.translate_for_user(
                    "Your buy request has been submitted to the trade channel.", chat_id
                ),
                reply_markup=await self.keyboards.build_back_exit_keyboard(chat_id),
            )

            # ─── پاک‌سازی state ─────────────────────────────────────────
            context.user_data.clear()
            pop_state(context)

        except Exception as e:
            await self.error_handler.handle(update, context, e, context_name="buy_price")

    # ───────────────────────────────────────────────────────────────────
    async def sell_order_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        seller_id = query.from_user.id

        order_id = int(query.data.split("_")[-1])
        order = await self.db.collection_orders.find_one({"order_id": order_id})
        if not order or order["status"] != "open":
            return await query.edit_message_reply_markup(None)   # Order closed / already taken

        if seller_id == order.get("buyer_id"):
            return await query.answer("You cannot sell to yourself.", show_alert=True)

        # ── Check token balance of seller ──────────────────────────────
        balance = await self.db.get_user_balance(seller_id)
        if balance < order["amount"]:
            return await query.answer("Insufficient token balance.", show_alert=True)

        # ── Transfer tokens & close order ──────────────────────────────
        await self.db.transfer_tokens(seller_id, order["buyer_id"], order["amount"])
        await self.db.collection_orders.update_one(
            {"order_id": order_id},
            {"$set": {
                "status":     "completed",
                "seller_id":  seller_id,
                "remaining":  0,
                "updated_at": datetime.utcnow()
            }}
        )

        # ── Notify parties ─────────────────────────────────────────────
        await query.edit_message_text("✅ FILLED by seller.")
        await context.bot.send_message(
            order["buyer_id"], "🎉 Your buy order was filled! Tokens credited."
        )
        await context.bot.send_message(
            seller_id,
            "✅ You sold your tokens. Admin will send USDT to your withdraw balance soon."
        )

        # ── Credit seller’s fiat balance for payout ───────────────────
        await self.db.credit_fiat_balance(seller_id, order["amount"] * order["price"])
    # #---------------------------------------------------------------------------------------------------
    # async def sell_order_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    #     query = update.callback_query
    #     await query.answer()
    #     seller_id = query.from_user.id

    #     order_id = int(query.data.split("_")[-1])
    #     order = await self.db.collection_orders.find_one({"order_id": order_id})
    #     if not order or order["status"] != "open":
    #         return await query.edit_message_reply_markup(None)

    #     if seller_id == order["buyer_id"]:
    #         return await query.answer("You cannot sell to yourself.", show_alert=True)

    #     # check token balance
    #     balance = await self.db.get_user_balance(seller_id)
    #     if balance < order["amount"]:
    #         return await query.answer("Insufficient token balance.", show_alert=True)

    #     # انتقال توکن در DB
    #     await self.db.transfer_tokens(seller_id, order["buyer_id"], order["amount"])
    #     await self.db.collection_orders.update_one(
    #         {"order_id": order_id},
    #         {"$set": {"status": "completed", "seller_id": seller_id, "updated_at": datetime.utcnow()}},
    #     )

    #     # پیام‌ها
    #     await query.edit_message_text("✅ FILLED by seller.")
    #     await context.bot.send_message(
    #         order["buyer_id"], "🎉 Your buy order was filled! Tokens credited."
    #     )
    #     await context.bot.send_message(
    #         seller_id,
    #         "✅ You sold your tokens. Admin will send USDT to your withdraw balance soon.",
    #     )

    #     # اعتبار دلاری برای خریدار کم نمی‌کنیم؛ او از قبل پول نداده است.
    #     await self.db.credit_fiat_balance(seller_id, order["amount"] * order["price"])

    # =========================================================================
    #  ب) دریافت و تأیید TxID خریدار
    # =========================================================================
    
    # ───────────────────────────────────────────────────────────────────
    async def prompt_trade_txid(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Handler برای پیامِ متنیِ TXID که خریدار پس از زدن «💳 I Paid» می‌فرستد.

        گام‌ها
        ------
        1) بررسی وجود سفارشِ در انتظار در user_data
        2) اعتبارسنجی فرمت TXID (64 کاراکتر هگز)
        3) اطمینان از status = pending_payment و تعلق سفارش به همین خریدار
        4) تأیید تراکنش روی بلاک‌چین (از طریق self.blockchain.verify_txid)
        5) انتقال توکن در DB، بستن سفارش، و اعتباردهی موجودی ارزی فروشنده
        6) ویرایش پیام کانال و ارسال اعلان به طرفین
        7) پاک‌سازی state
        """

        # این هندلر با یک Message فراخوانى مى‌شود؛ وجود update.message ضرورى است
        if not update.message or not update.message.text:
            return

        buyer_id  = update.effective_user.id
        order_id  = context.user_data.get("pending_order")      # از مرحله قبل ذخیره کرده‌ایم
        if not order_id:
            return await update.message.reply_text(
                "⚠️ No pending order found. Please start from an order card."
            )

        # ── 1) اعتبارسنجى فرمت TXID ─────────────────────────────────────
        txid = update.message.text.strip()
        if not re.fullmatch(r"[0-9A-Fa-f]{64}", txid):
            return await update.message.reply_text(
                "❗️ Invalid TXID format.\n"
                "It must be a 64-character hexadecimal string."
            )

        # ── 2) دریافت و صحت‌سنجى سفارش ─────────────────────────────────
        order = await self.db.collection_orders.find_one({"order_id": order_id})
        if (
            not order
            or order.get("status") != "pending_payment"
            or order.get("buyer_id") != buyer_id
        ):
            context.user_data.clear()
            return await update.message.reply_text(
                "⛔️ Order is no longer awaiting payment."
            )

        expected_amount = order["amount"] * order["price"]

        # ── 3) تأیید تراکنش روى بلاک‌چین ───────────────────────────────
        try:
            confirmed = await self.blockchain.verify_txid(
                txid=txid,
                destination=TRON_WALLET,
                expected_usdt=expected_amount,
            )
        except Exception as e:
            self.logger.error(f"Blockchain verification failed: {e}", exc_info=True)
            return await update.message.reply_text(
                "Unable to verify payment right now. Please try again later."
            )

        if not confirmed:
            return await update.message.reply_text(
                "Payment not yet confirmed on-chain. Please wait a few minutes and resend the TXID."
            )

        # ── 4) به‌روزرسانى اتمیک دیتابیس ──────────────────────────────
        # اگر از replica set استفاده مى‌کنید، session بهترین گزینه است.
        # در غیر این صورت همین توالى امن است:
        await self.db.transfer_tokens(order["seller_id"], buyer_id, order["amount"])
        await self.db.collection_orders.update_one(
            {"order_id": order_id},
            {"$set": {
                "status":     "completed",
                "txid":       txid,
                "updated_at": datetime.utcnow(),
            }}
        )
        await self.db.credit_fiat_balance(
            order["seller_id"], expected_amount
        )

        # ── 5) ویرایش پیام اولیهٔ کانال ───────────────────────────────
        try:
            await context.bot.edit_message_text(
                chat_id=TRADE_CHANNEL_ID,
                message_id=order["channel_msg_id"],
                text=(
                    f"✅ <b>ORDER {order_id} FILLED</b>\n"
                    f"Buyer: <a href='tg://user?id={buyer_id}'>link</a>\n"
                    f"Amount: {order['amount']} tokens @ ${order['price']}"
                ),
                parse_mode="HTML",
            )
        except Exception as e:
            # اگر پیام پاک یا ادیت شده باشد، فقط لاگ می‌کنیم
            self.logger.warning(f"Could not edit trade message {order_id}: {e}")

        # ── 6) اعلان به دو طرف معامله ─────────────────────────────────
        await context.bot.send_message(
            order["seller_id"],
            "🎉 Your tokens were sold! USDT has been credited to your withdraw balance. ✅"
        )
        await update.message.reply_text(
            "✅ Payment confirmed and tokens credited to your account."
        )

        # ── 7) پاک‌سازى state کاربر ───────────────────────────────────
        context.user_data.clear()    
    
    # async def prompt_trade_txid(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    #     """
    #     پس از زدن «💳 I Paid»:
    #     1) انتظار دریافت TXID
    #     2) تأیید در بلاک‌چین (مثال ساده)
    #     3) انتقال توکن در DB و بستن Order
    #     """
    #     buyer_id  = update.effective_chat.id
    #     order_id  = context.user_data.get("pending_order")
    #     if not order_id:
    #         return  # سفارشی در انتظار نیست

    #     txid = update.message.text.strip()
    #     if not re.fullmatch(r"[0-9A-Fa-f]{64}", txid):
    #         return await update.message.reply_text("Invalid TXID, try again.")

    #     # ─── تأیید تراکنش در بلاک‌چین (Pseudo) ───────────────────
    #     order = await self.db.collection_orders.find_one({"order_id": order_id})
    #     expected_amount = order["amount"] * order["price"]
    #     confirmed = await self.blockchain.verify_txid(txid, TRON_WALLET, expected_amount)

    #     if not confirmed:
    #         return await update.message.reply_text("Payment not confirmed yet.")

    #     # ─── انتقال توکن در DB (اتمیک) ───────────────────────────
    #     await self.db.transfer_tokens(order["seller_id"], buyer_id, order["amount"])
    #     await self.db.collection_orders.update_one(
    #         {"order_id": order_id},
    #         {"$set": {
    #             "status":     "completed",
    #             "buyer_id":   buyer_id,
    #             "txid":       txid,
    #             "updated_at": datetime.utcnow(),
    #         }}
    #     )

    #     # ─── ویرایش پیام کانال ──────────────────────────────────
    #     try:
    #         await update.get_bot().edit_message_text(
    #             chat_id=TRADE_CHANNEL_ID,
    #             message_id=order["channel_msg_id"],
    #             text=(
    #                 f"✅ SOLD\n"
    #                 f"Buyer: <a href='tg://user?id={buyer_id}'>link</a>"
    #             ),
    #             parse_mode="HTML",
    #         )
    #     except Exception:
    #         pass  # اگر پیام حذف یا ویرایش شده بود نادیده بگیر

    #     # ─── اعلان به طرفین ─────────────────────────────────────
    #     await update.get_bot().send_message(
    #         order["seller_id"], "🎉 Your tokens were sold! ✅"
    #     )
    #     await update.message.reply_text("Payment confirmed, tokens credited. ✅")

    #     # پاک‌سازی state
    #     context.user_data.clear()  
##############################################################################################################

    # #------------------------------------------------------------------------------------------------------
    # async def buy_price(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    #     chat_id = update.effective_chat.id
    #     txt = update.message.text.strip()

    #     try:
    #         price_per_token = float(txt)
    #         if price_per_token <= 0:
    #             raise ValueError
    #     except ValueError:
    #         await update.message.reply_text(
    #             await self.translation_manager.translate_for_user("Please send a valid price.", chat_id)
    #         )
    #         return  # همان state می‌ماند

    #     amount = context.user_data.get("buy_amount", 0)
    #     identifier = await self._get_user_identifier(chat_id)

    #     # ارسال به کانال ترید
    #     text_channel = (
    #         f"🚨 BUY Request\n"
    #         f"ID: {identifier}\n"
    #         f"Amount: {amount} tokens\n"
    #         f"Price: ${price_per_token:.4f} per token\n\n"
    #         "Contact support to proceed:"
    #     )
    #     await update.get_bot().send_message(
    #         chat_id=TRADE_CHANNEL_ID,
    #         text=text_channel,
    #         reply_markup=self._support_inline_keyboard(),
    #     )

    #     # تأیید برای کاربر
    #     await update.message.reply_text(
    #         await self.translation_manager.translate_for_user(
    #             "Your buy request has been submitted to support.", chat_id
    #         ),
    #         reply_markup=await self.keyboards.build_back_exit_keyboard(chat_id),
    #     )

    #     # پاک‌سازی state
    #     context.user_data.clear()
    #     pop_state(context)