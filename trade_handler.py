

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
import asyncio
from telegram import (
    Update,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    Bot
)

            
from datetime import datetime, timedelta   # اگر بالای فایل ندارید، اضافه کنید

from telegram.ext import ContextTypes
from telegram.error import BadRequest
from keyboards import TranslatedKeyboards
from language_Manager import TranslationManager
from error_handler import ErrorHandler
from Referral_logic_code import ReferralManager
from price_provider import PriceProvider          # ← NEW

from myproject_database import Database  # Async wrapper
from state_manager import push_state, pop_state
from blockchain_client import BlockchainClient

from config import TRADE_WALLET_ADDRESS as TRON_WALLET

BUY_PAYMENT_WINDOW = timedelta(minutes=15)
SELL_CONFIRM_WINDOW = timedelta(minutes=5)

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
        bot: Bot,       
        keyboards: TranslatedKeyboards,
        translation_manager: TranslationManager,
        price_provider: PriceProvider,
        referral_manager: ReferralManager,
        blockchain : BlockchainClient,
        error_handler: ErrorHandler,
        
    ) -> None:
        
        self.db = db
        self.bot = bot      
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
                "You are now in the <b>Trading Section</b> of the bot. Here you can:\n\n"
                "• <b>🛒 Buy</b> tokens at the current market price\n\n"
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

    # ──────────────────────────────────────────────────────────────────────#
    #            -------- SELL FLOW --------                                #
    # ──────────────────────────────────────────────────────────────────────#
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
                f"Current token price: <b>${price_now:.4f}</b>\n"
                f"Your balance: <b>{balance} tokens</b>\n\n"
                "<b>How many tokens do you want to sell?</b>"
            )
            await update.message.reply_text(
                await self.translation_manager.translate_for_user(msg_en, chat_id),
                parse_mode="HTML",
                reply_markup=await self.keyboards.build_back_exit_keyboard(chat_id),
            )
        except Exception as e:
            await self.error_handler.handle(update, context, e, context_name="sell_start")
            
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
                text = (
                    "⚠️ <b>Invalid input!</b>\n\n"
                    "Please enter a <b>positive number</b> (e.g. 5, 10, 25).\n\n"
                    "Only whole numbers are accepted for the amount of tokens to sell."
                )                 
                await update.message.reply_text(
                    await self.translation_manager.translate_for_user(text, chat_id),
                    parse_mode="HTML"
                )
                return  # در همان state `awaiting_sell_amount` می‌مانیم

            amount = int(txt)
            context.user_data["sell_amount"] = amount

            # ── انتقال state → awaiting_sell_price ─────────────────────
            pop_state(context)                               # خارج از awaiting_sell_amount
            push_state(context, "awaiting_sell_price")
            context.user_data["state"] = "awaiting_sell_price"


            # ── ساخت پیام راهنما برای وارد کردن قیمت ─────────────────
            text = (
                f"✅ You entered: <b>{amount} tokens</b>\n\n"
                "Now, please enter the <b>price per token</b> (in USD) you want to sell at.\n\n"
                "💡 Example: If you enter <b>0.35</b>, it means you're offering each token for <b>$0.35</b>."
            )
            await update.message.reply_text(
                await self.translation_manager.translate_for_user(text, chat_id),
                parse_mode="HTML",
                reply_markup=await self.keyboards.build_back_exit_keyboard(chat_id),
            )

        except Exception as e:
            await self.error_handler.handle(update, context, e, context_name="sell_amount")
            
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
                text_invalid = (
                    "⚠️ <b>Invalid price!</b>\n\n"
                    "Please enter a <b>positive number</b> for the price per token.\n\n"
                    "💡 Example: <b>0.25</b> means $0.25 per token."
                )                 
                await update.message.reply_text(
                    await self.translation_manager.translate_for_user( text_invalid, chat_id),
                    parse_mode="HTML"
                )
                return  # در همان state می‌مانیم

            amount     = context.user_data.get("sell_amount", 0)
            identifier = await self._get_user_identifier(chat_id)

            # ── پیام کانال + دکمهٔ Buy ────────────────────────────────
            text_channel = (
                f"🔥 <b>New Sell Offer Available!</b>\n\n"
                f"👤 <b>Seller:</b> {identifier}\n"
                f"📦 <b>Amount:</b> {amount} tokens\n"
                f"💵 <b>Price:</b> ${price_per_token:.4f} per token\n\n"
                "🛒 <b>Want to buy?</b> Click the <b>Buy</b> button below to place your order.\n\n"
                "🆘 <i>Need help? Use the Support button.</i>"
            )
            msg = await update.get_bot().send_message(      # ← msg برای message_id
                chat_id=TRADE_CHANNEL_ID,
                text=text_channel,
                parse_mode="HTML",
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
            confirmation_text = (
                "✅ <b>Your sell offer was submitted successfully!</b>\n\n"
                "📢 Your offer has been posted in the trade channel and is now visible to potential buyers.\n\n"
                "🛒 Interested users can click 'Buy' to proceed with the purchase.\n\n"
                "🕒 Please wait — our support team will contact you if any follow-up is required."
            )
            
            await update.message.reply_text(
                await self.translation_manager.translate_for_user(confirmation_text , chat_id),
                parse_mode="HTML",
                reply_markup=await self.keyboards.build_back_exit_keyboard(chat_id),
            )

            # ── پاک‌سازی state ───────────────────────────────────────
            pop_state(context)
            context.user_data.clear()

        except Exception as e:
            await self.error_handler.handle(update, context, e, context_name="sell_price")

    #####-------------------------------------------------------------------------------------##########
    async def buy_order_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            query = update.callback_query
            await query.answer()
            buyer_id = query.from_user.id

            order_id = int(query.data.split("_")[-1])
            order = await self.db.collection_orders.find_one({"order_id": order_id})

            # ── بررسی وضعیت سفارش ─────────────────────────────
            if not order or order["status"] != "open":
                await query.answer("⚠️ This order is no longer available.", show_alert=True)
                return await query.edit_message_reply_markup(None)

            # ── جلوگیری از خرید سفارش خود ─────────────────────
            if buyer_id == order.get("seller_id"):
                return await query.answer("🚫 You cannot buy your own order.", show_alert=True)

            total = order["amount"] * order["price"]
            context.user_data["pending_order"] = order_id
            context.user_data["state"] = "awaiting_trade_txid"

            # ── ارسال دستورالعمل پرداخت به خریدار ─────────────
            text_en = (
                f"🧾 <b>Order Summary</b>\n"
                f"💰 <b>Total to Pay:</b> ${total:.2f}\n"
                f"📥 <b>Payment Wallet (USDT-TRC20):</b>\n<code>{TRON_WALLET}</code>\n\n"
                "After sending the payment, please press <b>I Paid</b> and submit your <b>TXID (Transaction Hash)</b>."
            )
            
            # kb = InlineKeyboardMarkup(
            #     [[InlineKeyboardButton("💳 I Paid", callback_data=f"paid_{order_id}")]]
            # )
            
            kb = InlineKeyboardMarkup(
                [
                    [InlineKeyboardButton("💳 I Paid",  callback_data=f"paid_{order_id}")],
                    [InlineKeyboardButton("❌ Cancel", callback_data=f"cancel_{order_id}")]
                ]
            )            
                        
            await context.bot.send_message(
                chat_id=buyer_id,
                text=text_en,
                reply_markup=kb,
                parse_mode="HTML",
            )

            self.logger.info(f"Sent payment instructions for order {order_id} to user {buyer_id}")
            
            # ── به‌روزرسانی وضعیت سفارش در دیتابیس ─────────────
            expire_after = timedelta(minutes=15)          # مدت رزرو
            now          = datetime.utcnow()

            result = await self.db.collection_orders.update_one(
                {"order_id": order_id, "status": "open"},   # قفل اتمیک
                {"$set": {
                    "status":     "pending_payment",
                    "buyer_id":   buyer_id,
                    "expires_at": now + expire_after,
                    "updated_at": now
                }}
            )

            if result.modified_count == 0:                 # اگر کسی زودتر قفل کرد
                await query.answer("⚠️ This order is no longer available.", show_alert=True)
                return await query.edit_message_reply_markup(None)

        except Exception as e:
            await self.error_handler.handle(update, context, e, context_name="buy_order_callback")
            
    #######-------------------------------------------------------------------------------------------########
    async def cancel_order_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Buyer-initiated cancellation of a pending_payment order."""
        query = update.callback_query
        await query.answer()
        buyer_id = query.from_user.id
        order_id = int(query.data.split("_")[-1])

        # پیدا کردن سفارشی که خریدار خودش آن را قفل کرده
        order = await self.db.collection_orders.find_one({
            "order_id": order_id,
            "status":   "pending_payment",
            "buyer_id": buyer_id
        })
        if not order:
            return await query.answer("⛔️ You have no rights to cancel this order.", show_alert=True)

        # آزادسازی سفارش با همان متد کمکی
        await self._revert_order(order)

        # پاک‌سازی state کاربر
        context.user_data.clear()

        # پیام نهایی به خریدار
        await query.edit_message_text(
            "❌ Your reservation for this order is cancelled. The order is open again."
        )
            
    #######-------------------------------------------------------------------------------------------------
    def _buy_button_markup(self, order_id: int) -> InlineKeyboardMarkup:
        """Inline keyboard with single ‘Buy’ button for a given order."""
        return InlineKeyboardMarkup(
            [[InlineKeyboardButton("🛒 Buy", callback_data=f"buy_order_{order_id}")]]
        )
    #-----------------------------------------------------------------------------------------
    async def expire_pending_orders(self):
        """Background task: unlock orders whose 15-minute window expired."""
        while True:
            now = datetime.utcnow()
            cursor = self.db.collection_orders.find({
                "status": "pending_payment",
                "expires_at": {"$lt": now}
            })

            async for order in cursor:
                await self._revert_order(order)

            await asyncio.sleep(30)      # هر ۳۰ ثانیه چک کن
            
    #-----------------------------------------------------------------------------------------
    async def _revert_order(self, order: dict):
        """Return an expired order to 'open' status and notify parties."""
        
        await self.db.collection_orders.update_one(
            {"order_id": order["order_id"], "status": "pending_payment"},
            {"$set": {
                "status":    "open",
                "buyer_id":  None,
                "updated_at": datetime.utcnow()
            },
             "$unset": {"expires_at": ""}}
        )


        # ۲) ویرایش پیام کانال: عنوان جدید + دکمه Buy
        try:
            await self.bot.edit_message_text(
                chat_id=TRADE_CHANNEL_ID,
                message_id=order["channel_msg_id"],
                text=(
                    f"🔓 <b>ORDER #{order['order_id']} OPEN AGAIN</b>\n"
                    f"{order['amount']} tokens @ ${order['price']}"
                ),
                parse_mode="HTML",
                reply_markup=self._buy_button_markup(order["order_id"])
            )
        except Exception as e:
            self.logger.warning(
                f"Cannot unlock order {order['order_id']} in channel: {e}"
            )

        # ۲) اطلاع به خریدار
        if order.get("buyer_id"):
            txt = (f"⏳ Your 15-minute window for order #{order['order_id']} expired.\n"
                   "The order is now open again.")
            await self.bot.send_message(order["buyer_id"], txt)

        self.logger.info(f"Order {order['order_id']} reverted to OPEN")

    # =========================================================================
    #  ب) دریافت و تأیید TxID خریدار
    # =========================================================================
    
    async def prompt_trade_txid(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        دو مرحله را در یک متد پشتیبانی می‌کند:

        ▸ فاز ①  (CallbackQuery) – کاربر روی «💳 I Paid» می‌زند
            ◦ سفارشِ pending را پیدا می‌کنیم
            ◦ state ← awaiting_txid
            ◦ به کاربر می‌گوییم TXID را بفرستد

        ▸ فاز ②  (Message) – کاربر TXID را می‌فرستد
            ◦ اعتبارسنجی فرمت و تأیید روی بلاک‌چین
            ◦ انتقال توکن، تکمیل سفارش، آپدیت پیام کانال
            ◦ پاک‌سازی state
        """
        # ─── فاز ① : کاربر روی دکمه «I Paid» کلیک کرده است ──────────────
        if update.callback_query:
            query     = update.callback_query
            await query.answer()

            buyer_id  = query.from_user.id
            order_id  = int(query.data.split("_")[-1])

            order = await self.db.collection_orders.find_one({
                "order_id": order_id,
                "buyer_id": buyer_id,
                "status":   "pending_payment"
            })
            if not order:
                
                # پیام خطا هنگام کلیک روی "I Paid" ولی سفارش پیدا نشد
                msg = await self.translation_manager.translate_for_user(
                    "⛔️ Order not found or already completed.\n"
                    "Please make sure you selected a valid order card.", buyer_id
                )                
                return await query.answer(msg, show_alert=True)

            # ذخیرهٔ state برای فاز بعدی
            context.user_data["pending_order"] = order_id
            context.user_data["state"]        = "awaiting_txid"
            msg_en = (
                "✅ Payment process started.\n"
                "📨 <b>Please send the TXID (transaction hash) here in this chat.</b>\n\n"
                "💡 It must be a 64-character code from your wallet or exchange.\n\n"
                "🔙 If you changed your mind, just press <b>Back</b> or <b>Exit</b> below."
            )
            msg = await self.translation_manager.translate_for_user(msg_en, buyer_id)

            await context.bot.send_message(
                chat_id=buyer_id,
                text=msg,
                parse_mode="HTML",
                reply_markup=await self.keyboards.build_back_exit_keyboard(buyer_id)  # فقط همین کیبورد
            )
            
        # ─── فاز ② : پیام متنی حاوی TXID ───────────────────────────────
        if not update.message or not update.message.text:
            return  # پیام نامعتبر؛ نادیده می‌گیریم

        buyer_id  = update.effective_user.id
        order_id  = context.user_data.get("pending_order")
        if not order_id:
            # پیام عدم وجود سفارش در context
            msg = await self.translation_manager.translate_for_user(
                "⚠️ No active order found.\n"
                "Please click on a valid trade card and try again.",
                buyer_id
            )
            return await update.message.reply_text(msg)

        txid = update.message.text.strip()
        if not re.fullmatch(r"[0-9A-Fa-f]{64}", txid):
            
            # پیام TXID نامعتبر
            msg = await self.translation_manager.translate_for_user(
                "❗️ <b>The TXID format is invalid.</b>\n\n"
                "It must be a 64-character code containing only numbers and letters <b>A–F</b>.",
                buyer_id
            )
            return await update.message.reply_text(msg, parse_mode="HTML")

        # اطمینان از اینکه سفارش همچنان در انتظار پرداخت است
        order = await self.db.collection_orders.find_one({
            "order_id": order_id,
            "buyer_id": buyer_id,
            "status":   "pending_payment"
        })
        if not order:
            context.user_data.clear()   
            
            # پیام وقتی سفارش دیگر در انتظار پرداخت نیست  
            msg = await self.translation_manager.translate_for_user(
                "⛔️ <b>This order is no longer pending payment.</b>\n\n"
                "Please make sure you're submitting a valid and active order.",
                buyer_id
            )
            return await update.message.reply_text(msg, parse_mode="HTML")

        expected_amount = order["amount"] * order["price"]

        # ── تأیید TXID روی بلاک‌چین ───────────────────────────────────
        try:
            confirmed = await self.blockchain.verify_txid(
                txid=txid,
                to_address=TRON_WALLET,
                expected_usdt=expected_amount
            )
        except Exception as e:
            self.logger.error(f"Blockchain verification failed: {e}", exc_info=True)
            err = await self.translation_manager.translate_for_user(
                "⚠️ <b>We're unable to verify your payment on the blockchain right now.</b>\n\n"
                "Please wait a moment and try again shortly.",
                buyer_id
            )
            return await update.message.reply_text(err, parse_mode="HTML")

        if not confirmed:
            warn = await self.translation_manager.translate_for_user(
                "⛔️ <b>Payment not found or amount mismatch on blockchain.</b>\n\n"
                "Please double-check your TXID and try again.",
                buyer_id
            )
            self.logger.warning(f"TXID {txid} not confirmed for order {order_id}")
            return await update.message.reply_text(warn, parse_mode="HTML")

        # ── انتقال توکن و بستن سفارش ───────────────────────────────────
        await self.db.transfer_tokens(order["seller_id"], buyer_id, order["amount"])
        
        await self.db.collection_orders.update_one(
            {"order_id": order_id},
            {"$set": {
                "status":     "completed",
                "txid":       txid,
                "updated_at": datetime.utcnow()
            }}
        )
        await self.db.credit_fiat_balance(order["seller_id"], expected_amount)

        # ── ویرایش پیام کانال ────────────────────────────────────────
        try:
            await context.bot.edit_message_text(
                chat_id=TRADE_CHANNEL_ID,
                message_id=order["channel_msg_id"],
                text=(
                    f"✅ <b>ORDER {order_id} FILLED</b>\n"
                    f"Buyer: <a href='tg://user?id={buyer_id}'>link</a>\n"
                    f"Amount: {order['amount']} tokens @ ${order['price']}"
                ),
                parse_mode="HTML"
            )
        except Exception as e:
            self.logger.warning(f"Could not edit trade message {order_id}: {e}")

        # ── اعلان به فروشنده ───────────────────────────────────────────
        msg_seller = await self.translation_manager.translate_for_user(
            "🎉 <b>Your tokens have been sold successfully!</b>\n"
            "💵 <b>The USDT amount has been credited</b> to your withdrawal balance.",
            order["seller_id"]
        )        
        await context.bot.send_message(     
            chat_id=order["seller_id"],
            text=msg_seller,
            parse_mode="HTML"
        )
        
        # ── اعلان به خریدار ───────────────────────────────────────────
        msg_buyer = await self.translation_manager.translate_for_user(
            "✅ <b>Your payment has been confirmed.</b>\n"
            "🎯 <b>The purchased tokens are now in your account.</b>\n\n"
            "Thank you for using our platform!",
            update.effective_user.id
        )
        await update.message.reply_text(
            msg_buyer,
            parse_mode="HTML"
        )
        # ── پاک‌سازی state ──────────────────────────────────────────
        context.user_data.clear()

    # ──────────────────────────────────────────────────────────────────────#
    #            -------- BUY FLOW --------                                 #
    # ──────────────────────────────────────────────────────────────────────#
    async def buy_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        گام اول خرید: ست‌کردن state و درخواست تعداد توکن مورد نیاز از کاربر.
        """
        try:
            # ───➤ ست‌کردن state برای انتظار مقدار خرید
            push_state(context, "awaiting_buy_amount")
            context.user_data['state'] = "awaiting_buy_amount"

            chat_id = update.effective_chat.id
            price = await self.price_provider.get_price()

            msg_en = (
                f"💸 <b>Current token price:</b> ${price:.4f}\n\n"
                "🛒 <b>How many tokens do you want to buy?</b>\n"
                "Please enter a <b>positive number</b> (e.g. 10, 25, 100)."
            )

            await update.message.reply_text(
                await self.translation_manager.translate_for_user(msg_en, chat_id),
                parse_mode="HTML",
                reply_markup=await self.keyboards.build_back_exit_keyboard(chat_id),
            )

            return BUY_AMOUNT

        except Exception as e:
            await self.error_handler.handle(update, context, e, context_name="buy_start")
    
    #------------------------------------------------------------------------------------------------------
    async def buy_amount(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        گام دوم خرید: دریافت تعداد توکن از خریدار و رفتن به مرحله تعیین قیمت پیشنهادی.
        """
        try:
            chat_id = update.effective_chat.id
            txt = update.message.text.strip()

            # ── اعتبارسنجی عدد ───────────────────────────────
            if not txt.isdigit() or int(txt) <= 0:
                text_invalid = (
                    "⚠️ <b>Invalid amount!</b>\n"
                    "Please enter a <b>positive number</b> of tokens to buy (e.g. 10, 50, 100)."
                )
                await update.message.reply_text(
                    await self.translation_manager.translate_for_user(text_invalid, chat_id),
                    parse_mode="HTML"
                )
                return  # در همان state می‌ماند

            amount = int(txt)
            context.user_data["buy_amount"] = amount

            # ── انتقال به مرحله قیمت پیشنهادی ───────────────
            context.user_data['state'] = 'awaiting_buy_price'
            push_state(context, 'awaiting_buy_price')

            text_price = (
                f"🧮 <b>You want to buy:</b> {amount} tokens\n\n"
                "💵 <b>At what price (USD) per token are you willing to buy?</b>\n\n"
                "Please enter your offer (e.g. <b>0.25</b>)"
            )

            await update.message.reply_text(
                await self.translation_manager.translate_for_user(text_price, chat_id),
                parse_mode="HTML"
            )

        except Exception as e:
            await self.error_handler.handle(update, context, e, context_name="buy_amount")
    
    
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
                error_msg = (
                    "⚠️ <b>Invalid price!</b>\n"
                    "Please enter a <b>positive number</b> for price per token (e.g. 0.25)."
                )                
                
                await update.message.reply_text(
                    await self.translation_manager.translate_for_user(error_msg, chat_id),
                    parse_mode="HTML"
                )
                return  # همان state می‌مانیم

            amount     = context.user_data.get("buy_amount", 0)
            identifier = await self._get_user_identifier(chat_id)

            # ─── ارسال پیام به کانال ترید ─────────────────────────────────
            text_channel = (
                f"📢 <b>New Buy Request</b>\n\n"
                f"🧑‍💼 <b>Buyer:</b> {identifier}\n"
                f"📦 <b>Amount:</b> {amount} tokens\n"
                f"💰 <b>Price:</b> ${price_per_token:.4f} per token\n\n"
                "💸 <b>First seller to accept will receive USDT from escrow.</b>\n\n"
                "Tap the <b>Sell</b> button below if you want to fulfill this order."
            )
            msg = await update.get_bot().send_message(
                chat_id=TRADE_CHANNEL_ID,
                text=text_channel,
                parse_mode="HTML",
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
            confirmation_msg = (
                "✅ <b>Your buy order has been submitted!</b>\n\n"
                "📡 It is now visible in the trade channel for potential sellers.\n\n"
                "💬 If someone accepts your offer, they will proceed with the transaction."
            )            
            await update.message.reply_text(
                await self.translation_manager.translate_for_user(confirmation_msg, chat_id),
                parse_mode="HTML",
                reply_markup=await self.keyboards.build_back_exit_keyboard(chat_id),
            )

            # ─── پاک‌سازی state ─────────────────────────────────────────
            context.user_data.clear()
            pop_state(context)

        except Exception as e:
            await self.error_handler.handle(update, context, e, context_name="buy_price")

    # ───────────────────────────── فروشنده روی «Sell» می‌زند ──────────────────────────
    async def sell_order_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        مرحله ❶ – فروشنده روی دکمۀ Sell می‌زند → از او تأیید نهایی می‌گیریم.
        """
        try:
            query = update.callback_query
            await query.answer()

            seller_id = query.from_user.id
            order_id  = int(query.data.split("_")[-1])

            order = await self.db.collection_orders.find_one({"order_id": order_id})
            if not order or order["status"] != "open":
                return await query.answer("⛔️ This order is no longer available.", show_alert=True)

            if seller_id == order["buyer_id"]:
                return await query.answer("🚫 You cannot sell to yourself.", show_alert=True)

            balance = await self.db.get_user_balance(seller_id)
            if balance < order["amount"]:
                return await query.answer("🚫 Insufficient token balance.", show_alert=True)

            # ➊ قفل سفارش موقتاً در حالت pending_seller_confirm
            await self.db.collection_orders.update_one(
                {"order_id": order_id, "status": "open"},
                {"$set": {
                    "status": "pending_seller_confirm",
                    "seller_id": seller_id,
                    "expires_at": datetime.utcnow() + SELL_CONFIRM_WINDOW
                }}
            )
            # ➋ پیام تأیید به فروشنده
            txt = (
                f"🧾 <b>Order #{order_id}</b>\n"
                f"🔹 {order['amount']} tokens  ×  ${order['price']:.4f}\n\n"
                "Are you sure you want to sell this amount at this price?"
            )
            kb = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton("✅ Confirm", callback_data=f"confirm_sell_{order_id}"),
                        InlineKeyboardButton("❌ Cancel",  callback_data=f"cancel_sell_{order_id}")
                    ]
                ]
            )
            await context.bot.send_message(
                chat_id=seller_id,
                text=await self.translation_manager.translate_for_user(txt, seller_id),
                parse_mode="HTML",
                reply_markup=kb
            )

            await query.answer("✅ Please confirm in PM.", show_alert=True)

        except Exception as e:
            await self.error_handler.handle(update, context, e, "sell_order_callback")

    # ───────────────────────── فروشنده «Confirm» یا «Cancel» ─────────────────────────
    async def seller_confirm_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        مرحله ❷ – فروشنده تأیید می‌کند؛ حالا از خریدار پول می‌خواهیم.
        """
        query = update.callback_query
        await query.answer()
        seller_id = query.from_user.id
        order_id  = int(query.data.split("_")[-1])

        order = await self.db.collection_orders.find_one({
            "order_id": order_id,
            "status": "pending_seller_confirm",
            "seller_id": seller_id
        })
        if not order:
            return await query.answer("⛔️ Order not found or timed-out.", show_alert=True)

        # ➊ تغییر status → pending_payment
        await self.db.collection_orders.update_one(
            {"order_id": order_id},
            {"$set": {
                "status": "pending_payment",
                "expires_at": datetime.utcnow() + BUY_PAYMENT_WINDOW
            }}
        )

        # ➋ پیام به خریدار برای پرداخت
        buyer_id = order["buyer_id"]
        total    = order["amount"] * order["price"]
        pay_msg = (
            f"✅ <b>A seller accepted your order #{order_id}!</b>\n\n"
            f"💰 <b>Total:</b> ${total:.2f}\n"
            f"📥 <b>USDT-TRC20 Wallet:</b>\n<code>{TRON_WALLET}</code>\n\n"
            "After paying, press <b>I Paid</b> and send your TXID."
        )
        pay_kb = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("💳 I Paid",  callback_data=f"paid_{order_id}")],
                [InlineKeyboardButton("❌ Cancel", callback_data=f"cancel_payment_{order_id}")]
            ]
        )
        await context.bot.send_message(
            chat_id=buyer_id,
            text=await self.translation_manager.translate_for_user(pay_msg, buyer_id),
            parse_mode="HTML",
            reply_markup=pay_kb
        )

        # ➌ اطلاع به فروشنده
        await query.edit_message_text("⏳ Waiting for buyer payment…")

    async def seller_cancel_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        فروشنده پشیمان می‌شود؛ سفارش را به حالت open برمی‌گردانیم.
        """
        query = update.callback_query
        await query.answer()
        seller_id = query.from_user.id
        order_id  = int(query.data.split("_")[-1])

        result = await self.db.collection_orders.update_one(
            {"order_id": order_id, "seller_id": seller_id, "status": "pending_seller_confirm"},
            {"$set": {"status": "open"}, "$unset": {"seller_id": "", "expires_at": ""}}
        )
        if result.modified_count:
            await query.edit_message_text("❌ Cancelled. Order is open again.")
        else:
            await query.answer("⛔️ Too late.", show_alert=True)

    # ───────────────────── خریدار «I Paid» و ارسال TXID ─────────────────────
    async def prompt_buy_payment(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        ❸ دو فاز:   (الف) کلیک «I Paid»   (ب) ارسال TXID
        مثل منطق فروش قبلی.
        """
        # (الف) کلیک
        if update.callback_query:
            query = update.callback_query
            await query.answer()
            buyer_id = query.from_user.id
            order_id = int(query.data.split("_")[-1])

            order = await self.db.collection_orders.find_one({
                "order_id": order_id,
                "buyer_id": buyer_id,
                "status":  "pending_payment"
            })
            if not order:
                return await query.answer("⛔️ Order not found or expired.", show_alert=True)

            context.user_data["pending_payment_order"] = order_id
            context.user_data["state"] = "awaiting_txid"

            ask_txid = (
                "✅ Payment process started.\n"
                "📨 <b>Send the 64-char TXID here.</b>"
            )
            await context.bot.send_message(
                chat_id=buyer_id,
                text=await self.translation_manager.translate_for_user(ask_txid, buyer_id),
                parse_mode="HTML"
            )
            return

        # (ب) دریافت TXID
        if not update.message or not update.message.text:
            return
        buyer_id = update.effective_user.id
        txid = update.message.text.strip()
        if not re.fullmatch(r"[0-9A-Fa-f]{64}", txid):
            warn = "❗️ Invalid TXID format."
            return await update.message.reply_text(
                await self.translation_manager.translate_for_user(warn, buyer_id),
                parse_mode="HTML"
            )

        order_id = context.user_data.get("pending_payment_order")
        order = await self.db.collection_orders.find_one({
            "order_id": order_id,
            "buyer_id": buyer_id,
            "status":  "pending_payment"
        })
        if not order:
            return

        # تأیید روی بلاک‌چین
        expected = order["amount"] * order["price"]
        confirmed = await self.blockchain.verify_txid(
            txid=txid,
            to_address=TRON_WALLET,
            expected_usdt=expected
        )
        if not confirmed:
            err = "⛔️ Payment not found or amount mismatch."
            return await update.message.reply_text(
                await self.translation_manager.translate_for_user(err, buyer_id),
                parse_mode="HTML"
            )

        # ── انتقال توکن + بستن سفارش
        await self.db.transfer_tokens(
            from_user_id=order["seller_id"],
            to_user_id=buyer_id,
            amount=order["amount"]
        )
        await self.db.credit_fiat_balance(order["seller_id"], expected)

        await self.db.collection_orders.update_one(
            {"order_id": order_id},
            {"$set": {"status": "completed", "txid": txid, "updated_at": datetime.utcnow()}}
        )

        # پیام کانال
        await self.bot.edit_message_text(
            chat_id=TRADE_CHANNEL_ID,
            message_id=order["channel_msg_id"],
            text=f"✅ <b>BUY ORDER #{order_id} COMPLETED</b>",
            parse_mode="HTML"
        )

        # اطلاع‌ها
        txt_buyer = "🎉 Tokens are now in your account."
        await self.bot.send_message(
            buyer_id, await self.translation_manager.translate_for_user(txt_buyer, buyer_id),
            parse_mode="HTML"
        )
        txt_seller = "💵 USDT credited to your balance."
        await self.bot.send_message(
            order["seller_id"],
            await self.translation_manager.translate_for_user(txt_seller, order["seller_id"]),
            parse_mode="HTML"
        )
        context.user_data.clear()

    # ────────────────────────── Helper keyboards ─────────────────────────────
    def _sell_button_markup(self, order_id: int) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("💸 Sell", callback_data=f"sell_order_{order_id}")],
                [InlineKeyboardButton("SOS Support", url=f"https://t.me/{SUPPORT_USER_USERNAME}")]
            ]
        )

    def _no_button_markup(self) -> InlineKeyboardMarkup:
        """برای پیام‌های منقضی‌شده که نباید دکمه داشته باشند."""
        return InlineKeyboardMarkup([])

    # ───────────────────────── Background Tasks ──────────────────────────────
    async def monitor_buy_orders(self):
        """
        یک حلقهٔ واحد که هر ۳۰ ثانیه سه نوع سفارش را بررسی می‌کند:
        ① Seller-confirm expired   ② Buyer-payment expired   ③ Open expired
        """
        while True:
            now = datetime.utcnow()

            # ① فروشنده تأیید نکرد (۵ دقیقه گذشت)
            async for order in self.db.collection_orders.find({
                "status": "pending_seller_confirm",
                "expires_at": {"$lt": now}
            }):
                await self._reopen_order(order, reason="seller_timeout")

            # ② خریدار پول نداد (۱۵ دقیقه گذشت)
            async for order in self.db.collection_orders.find({
                "status": "pending_payment",
                "expires_at": {"$lt": now}
            }):
                await self._reopen_order(order, reason="buyer_timeout")

            # ③ هیچ فروشنده‌ای پیدا نشد (۹۰ دقیقه)
            async for order in self.db.collection_orders.find({
                "status": "open",
                "expires_at": {"$lt": now}
            }):
                await self._expire_order(order)

            await asyncio.sleep(30)

    # ───────────────────────── Helper actions ────────────────────────────────
    async def _reopen_order(self, order: dict, *, reason: str):
        """
        سفارش را دوباره به حالت open برمی‌گرداند
        reason = 'seller_timeout' | 'buyer_timeout'
        """
        await self.db.collection_orders.update_one(
            {"order_id": order["order_id"]},
            {"$set": {
                "status":   "open",
                "seller_id": None,
                "expires_at": datetime.utcnow() + timedelta(minutes=90)  # ریست شمارش
            }}
        )

        # پیام کانال: Unlock + دکمه Sell
        await self._safe_edit_channel(
            order,
            text=(
                f"🔓 <b>BUY ORDER #{order['order_id']} OPEN AGAIN</b>\n"
                f"{order['amount']} tokens @ ${order['price']}"
            ),
            markup=self._sell_button_markup(order["order_id"])
        )

        # اطلاع به طرف مقصر
        if reason == "seller_timeout" and order.get("seller_id"):
            msg = "⏳ You didn’t confirm in time; order reopened."
            await self.bot.send_message(
                order["seller_id"],
                await self.translation_manager.translate_for_user(msg, order["seller_id"])
            )
        if reason == "buyer_timeout":
            txt = (
                f"⏳ 15-minute window expired for order #{order['order_id']}.\n"
                "Order reopened; pay only after a seller confirms again."
            )
            await self.bot.send_message(
                order["buyer_id"],
                await self.translation_manager.translate_for_user(txt, order["buyer_id"])
            )

        self.logger.info(f"Buy-order {order['order_id']} reopened ({reason}).")

    async def _expire_order(self, order: dict):
        """پس از ۹۰ دقیقه هیچ فروشنده‌ای پیدا نشد → status=expired"""
        await self.db.collection_orders.update_one(
            {"order_id": order["order_id"]},
            {"$set": {"status": "expired"}}
        )

        # پیام کانال: Expired بدون دکمه
        await self._safe_edit_channel(
            order,
            text=(
                f"❌ <b>BUY ORDER #{order['order_id']} EXPIRED</b>\n"
                f"No seller within allotted time."
            ),
            markup=self._no_button_markup()
        )

        # اطلاع به خریدار
        txt = (
            "⌛️ No seller accepted your order in time.\n"
            "Support will refund your USDT shortly."
        )
        await self.bot.send_message(
            order["buyer_id"],
            await self.translation_manager.translate_for_user(txt, order["buyer_id"])
        )
        self.logger.info(f"Buy-order {order['order_id']} expired (no seller).")

    # ─────────────────────── Safe channel edit helper ───────────────────────
    async def _safe_edit_channel(self, order: dict, *, text: str, markup: InlineKeyboardMarkup):
        """ویرایش پیام کانال با لاگ خطا در صورت عدم دسترسی."""
        try:
            await self.bot.edit_message_text(
                chat_id=TRADE_CHANNEL_ID,
                message_id=order["channel_msg_id"],
                text=text,
                parse_mode="HTML",
                reply_markup=markup
            )
        except Exception as e:
            self.logger.warning(f"Cannot edit buy-order {order['order_id']}: {e}")



##############################################################################################################    
    

    # # # ───────────────────────────────────────────────────────────────────
    # async def sell_order_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    #     """
    #     Called when a seller clicks the 'Sell' button for a buy order.
    #     Verifies order validity, seller's token balance, transfers tokens, and notifies both parties.
    #     """
    #     try:
    #         query = update.callback_query
    #         self.logger.info(f"🔔 CALLBACK sell_order: {query.data}")

    #         # 1️⃣ Show spinner/loading message
    #         await query.answer(
    #             text="⏳ Processing your sell request...",
    #             show_alert=False
    #         )

    #         seller_id = query.from_user.id
    #         order_id = int(query.data.split("_")[-1])

    #         # 2️⃣ Fetch order from DB
    #         order = await self.db.collection_orders.find_one({"order_id": order_id})
    #         if not order or order["status"] != "open":
    #             self.logger.warning(f"Order {order_id} not open or not found")
    #             return await query.edit_message_reply_markup(None)

    #         # 3️⃣ Prevent self-trade
    #         if seller_id == order.get("buyer_id"):
    #             msg = await self.translation_manager.translate_for_user(
    #                 "🚫 You cannot fulfill your own buy order.", seller_id
    #             )                
    #             return await query.answer(msg,show_alert=True)

    #         # 4️⃣ Check seller token balance
    #         balance = await self.db.get_user_balance(seller_id)
    #         if balance < order["amount"]:
    #             msg = await self.translation_manager.translate_for_user(
    #                 "🚫 Insufficient token balance!\n"
    #                 "Please make sure your balance is at least equal to the requested amount.",
    #                 seller_id
    #             )
    #             return await query.answer(msg, show_alert=True)


    #         # 5️⃣ Transfer tokens and close the order
    #         await self.db.transfer_tokens(seller_id, order["buyer_id"], order["amount"])
    #         await self.db.collection_orders.update_one(
    #             {"order_id": order_id},
    #             {"$set": {
    #                 "status":     "completed",
    #                 "seller_id":  seller_id,
    #                 "remaining":  0,
    #                 "updated_at": datetime.utcnow()
    #             }}
    #         )
    #         self.logger.info(
    #             f"Transferred {order['amount']} tokens from seller {seller_id} to buyer {order['buyer_id']} for order {order_id}"
    #         )

    #         # 6️⃣ Edit channel message to mark order completed
    #         await query.edit_message_text(
    #             "✅ <b>This buy order has been fulfilled by a seller.</b>\n\n"
    #             "The tokens have been transferred securely via escrow.",
    #             parse_mode="HTML"
    #         )

    #         # 7️⃣ Notify the buyer privately
    #         buyer_id = order["buyer_id"]
            
    #         text_buyer = (
    #             "🎉 <b>Your buy order has been successfully fulfilled!</b>\n\n"
    #             "💰 The tokens have been securely transferred to your account.\n\n"
    #             "Thank you for using the marketplace!"
    #         )
    #         await context.bot.send_message(
    #             chat_id=buyer_id,
    #             text=await self.translation_manager.translate_for_user(text_buyer, buyer_id),
    #             parse_mode="HTML"
    #         )

    #         # 8️⃣ Notify the seller privately
    #         text_seller = (
    #             "✅ <b>Your tokens have been sold successfully!</b>\n\n"
    #             "💵 The equivalent USDT amount will be credited to your account shortly.\n\n"
    #             "Thank you for completing the transaction."
    #         )
    #         await context.bot.send_message(
    #             chat_id=seller_id,
    #             text=await self.translation_manager.translate_for_user(text_seller, seller_id),
    #             parse_mode="HTML"
    #         )
    #         self.logger.info(f"Notified buyer {buyer_id} and seller {seller_id} about completion of order {order_id}")

    #         # 9️⃣ Credit seller’s fiat balance
    #         payout = order["amount"] * order["price"]
    #         await self.db.credit_fiat_balance(seller_id, payout)
    #         self.logger.info(f"Credited fiat balance of seller {seller_id} by ${payout:.2f}")

    #     except Exception as e:
    #         await self.error_handler.handle(update, context, e, context_name="sell_order_callback")
    


    # def _sell_button_markup(self, order_id:int):
    #     return InlineKeyboardMarkup(
    #         [[InlineKeyboardButton("💸 Sell", callback_data=f"sell_order_{order_id}")]]
    #     )
