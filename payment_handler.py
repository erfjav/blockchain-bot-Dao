

# payment_handler.py

from __future__ import annotations
import os
import logging
import asyncio
import httpx
import re

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from language_Manager import TranslationManager
from keyboards import TranslatedKeyboards
from error_handler import ErrorHandler
from state_manager import push_state
from myproject_database import Database
from Referral_logic_code import ReferralManager, TokensDepletedError
from blockchain_client import BlockchainClient

from config import PAYMENT_WALLET_ADDRESS, TRADE_CHANNEL_ID
from datetime import datetime

logger = logging.getLogger(__name__)


class PaymentHandler:
    """
    هندلر «💳 Payment»
    • نمایش اطلاعات پایه کاربر (در صورت وجود)
    • نمایش دستورالعمل پرداخت ۵۰ دلار
    • دریافت TxID و فعال‌سازی پروفایل (اختصاص توکن)
    """

    def __init__(
        self,
        db: Database,        
        keyboards: TranslatedKeyboards,
        translation_manager: TranslationManager,
        error_handler: ErrorHandler,
        blockchain: BlockchainClient,
        referral_manager: ReferralManager,
    ) -> None:
        self.db = db
        self.keyboards = keyboards
        self.translation_manager = translation_manager
        self.eh = error_handler
        self.referral_manager = referral_manager
        self.blockchain = blockchain
        
        self.wallet_address = PAYMENT_WALLET_ADDRESS or "TXXYYZZ_PLACEHOLDER_ADDRESS"
        self.logger = logging.getLogger(self.__class__.__name__)

    async def show_payment_instructions(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        1) نمایش اطلاعات پایه (Member No, Referral Code) اگر موجود باشد
        2) نمایش دستورالعمل پرداخت + دکمه‌های:
           • TxID (transaction hash)
           • ⬅️ Back    ➡️ Exit
        3) ست‌کردن state = prompt_txid
        """
        chat_id    = update.effective_chat.id
        first_name = update.effective_user.first_name

        try:
            # ensure user record exists (بدون تخصیص توکن)
            await self.db.insert_user_if_not_exists(chat_id, first_name)

            profile = await self.db.get_profile(chat_id)

            # ساخت پیام
            lines = ["💳 <b>Payment Instructions</b>\n"]
            if profile:
                lines += [
                    f"• Member No: <b>{profile['member_no']}</b>",
                    f"• Referral Code: <code>{profile['referral_code']}</code>\n"
                ]
            else:
                lines += [
                    "• Member No: —",
                    "• Referral Code: —\n"
                ]
            lines += [
                "1️⃣ Send $50 USDT (TRC-20) to:",
                f"<code>{self.wallet_address}</code>",
                "2️⃣ When done, press the button below and select “TxID (transaction hash)”."
            ]
            msg = "\n".join(lines)

            # ست‌کردن state برای prompt فاز TxID
            push_state(context, "prompt_txid")
            context.user_data["state"] = "prompt_txid"

            # کیبورد مخصوص شامل دکمه‌ی TxID و Back/Exit
            reply_kb = await self.keyboards.build_show_payment_keyboard(chat_id)

            await update.message.reply_text(
                await self.translation_manager.translate_for_user(msg, chat_id),
                parse_mode="HTML",
                reply_markup=reply_kb,
            )

        except Exception as e:
            await self.eh.handle(update, context, e, context_name="show_payment_instructions")

    #-------------------------------------------------------------------------------------   
    async def prompt_for_txid(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        When the user taps the “TxID (transaction hash)” button:
        1) set state = awaiting_sub_txid
        2) prompt the user to send the hash, with translated and formatted messaging
        """
        chat_id = update.effective_chat.id

        try:
            # ➊ Set state to wait for transaction hash
            push_state(context, "awaiting_sub_txid")
            context.user_data["state"] = "awaiting_sub_txid"

            # ➋ Build prompt message
            prompt_text = (
                "🔔 Please send your transaction TxID (hash) now.\n\n"
                "⚠️ The TxID is a mix of letters and numbers — please copy it exactly\n\n"
                "to ensure your payment is confirmed promptly.\n\n"
                "🔙 Use Back to return or Exit to cancel."
            )

            translated = await self.translation_manager.translate_for_user(prompt_text, chat_id)

            await update.message.reply_text(
                translated,
                parse_mode="HTML",
                reply_markup=await self.keyboards.build_back_exit_keyboard(chat_id)
            )

        except Exception as e:
            self.logger.error(f"Error in prompt_for_txid: {e}", exc_info=True)

            error_text = (
                "🚫 Sorry, something went wrong while requesting your TxID.\n"
                "Please try again or contact support."
            )
            translated_error = await self.translation_manager.translate_for_user(error_text, chat_id)

            await update.message.reply_text(
                translated_error,
                parse_mode="HTML",
                reply_markup=await self.keyboards.build_back_exit_keyboard(chat_id)
            )

    
    # async def prompt_for_txid(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    #     """
    #     وقتی کاربر دکمه‌ی “TxID (transaction hash)” را می‌زند:
    #     1) ست‌کردن state = awaiting_sub_txid
    #     2) درخواست ارسال هش
    #     """
    #     chat_id = update.effective_chat.id

    #     # ➊ رفتن به فاز دریافت TxID
    #     # push_state(context, "awaiting_txid")
    #     context.user_data["state"] = "awaiting_sub_txid"

    #     await update.message.reply_text(
    #         "🔔 لطفاً TxID (transaction hash) خود را ارسال کنید:",
    #         reply_markup=await self.keyboards.build_back_exit_keyboard(chat_id)
    #     )

    #-------------------------------------------------------------------------------------   
    def is_valid_txid(self, txid: str) -> bool:
        """
        اعتبارسنجی TxID:
        - فرض: 64 کاراکتر هگز [0-9A-Fa-f]
        """
        return bool(re.fullmatch(r"[0-9A-Fa-f]{64}", txid))
    
    #-------------------------------------------------------------------------------------  
    
    async def handle_txid(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        دریافت TxID از کاربر، ثبت در دیتابیس، ارسال پیام تأیید، و آغاز مانیتور پرداخت.
        """
        chat_id = update.effective_chat.id
        txid = update.message.text.strip()

        try:
            # ➊ ثبت وضعیت
            push_state(context, "sub_txid_received")
            context.user_data["state"] = "txid_received"

            # ➋ ذخیره TxID در دیتابیس
            await self.db.store_payment_txid(chat_id, txid)

            # ➌ پیام تأیید برای کاربر
            confirm_text = (
                "✅ <b>TxID received!</b>\n"
                "We’ll notify you as soon as your payment is confirmed on the blockchain."
            )
            translated = await self.translation_manager.translate_for_user(confirm_text, chat_id)

            await update.message.reply_text(
                translated,
                parse_mode="HTML",
                reply_markup=await self.keyboards.build_back_exit_keyboard(chat_id)
            )

            # ➍ آغاز تسک پس‌زمینه برای مانیتور پرداخت
            context.application.create_task(
                self.monitor_payment(chat_id, txid, context.bot)
            )

        except Exception as e:
            self.logger.error(f"Error in handle_txid: {e}", exc_info=True)

            error_text = (
                "🚫 <b>Something went wrong while processing your TxID.</b>\n"
                "Please try again later or contact support."
            )
            translated_error = await self.translation_manager.translate_for_user(error_text, chat_id)

            await update.message.reply_text(
                translated_error,
                parse_mode="HTML",
                reply_markup=await self.keyboards.build_back_exit_keyboard(chat_id)
            )
    
     
    # async def handle_txid(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    #     """
    #     دریافت TxID از کاربر، درج آن در DB و آغاز مانیتور پرداخت.
    #     به‌جای تخصیص توکن اینجا، تسکی می‌سازیم که خودکار پرداخت را تأیید و
    #     سپس پروفایل کاربر را نهایی کند.
    #     """
    #     chat_id = update.effective_chat.id
    #     txid    = update.message.text.strip()

    #     # ➊ ست کردن state جدید
    #     push_state(context, "sub_txid_received")
    #     context.user_data["state"] = "txid_received"

    #     # ➋ ذخیره TxID در DB
    #     await self.db.store_payment_txid(chat_id, txid)

    #     # ➌ پیام اولیه به کاربر
    #     await update.message.reply_text(
    #         "✅ TxID received! We will notify you once your payment is confirmed.",
    #         reply_markup=await self.keyboards.build_back_exit_keyboard(chat_id)
    #     )

    #     # ➍ ساخت تسک پس‌زمینه برای مانیتور پرداخت
    #     #    از context.application برای ایجاد task استفاده می‌کنیم
    #     context.application.create_task(
    #         self.monitor_payment(chat_id, txid, context.bot)
    #     )
        
    #-------------------------------------------------------------------------------------   
    async def monitor_payment(self, chat_id: int, txid: str, bot, context: ContextTypes.DEFAULT_TYPE):
        """
        هر ۳۰ ثانیه وضعیت تراکنش TRC-20 را در ترون‌گرید چک می‌کند
        تا ۱۰ بار؛ اگر تأیید شود:
          1) status → 'confirmed'
          2) ensure_user → ثبت‌نام و تخصیص توکن
          3) ارسال پیام تأیید به کاربر
        در غیر این صورت بعد از ۱۰ تلاش:
          status → 'failed'
          پیام خطا به کاربر
        """
        tron_api = f"https://api.trongrid.io/wallet/gettransactionbyid?value={txid}"
        max_attempts = 10
        for attempt in range(max_attempts):
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    resp = await client.get(tron_api)
                    data = resp.json()
                # بررسی ret[0].contractRet == 'SUCCESS'
                if data.get("ret") and data["ret"][0].get("contractRet") == "SUCCESS":
                    # ➊ به‌روزرسانی وضعیت در DB
                    await self.db.update_payment_status(txid, "confirmed")

                    # ➋ ثبت نهایی کاربر و تخصیص توکن
                    profile = await self.referral_manager.ensure_user(
                        chat_id,
                        # فرض: inviter_code قبلاً در context.user_data ذخیره شده
                        inviter_code=context.user_data.get("inviter_code"),
                        first_name=bot.get_chat(chat_id).first_name
                    )

                    # ➌ پیام تأیید به کاربر
                    msg = (
                        f"✅ Payment confirmed!\n\n"
                        f"Your profile is now active:\n"
                        f"• Member No: <b>{profile['member_no']}</b>\n"
                        f"• Referral Code: <code>{profile['referral_code']}</code>\n"
                        f"• Tokens Allocated: <b>{profile['tokens']:.0f}</b>"
                    )
                    
                    translated = await self.translation_manager.translate_for_user(msg, chat_id)
                    await bot.send_message(
                        chat_id,
                        translated,
                        parse_mode="HTML",
                        reply_markup=await self.keyboards.build_main_menu_keyboard_v2(chat_id)
                    )
                    
                    self.logger.info(f"✅ Payment confirmed for user {chat_id}")
                    return

            except Exception as e:
                self.logger.warning(f"Attempt {attempt + 1} failed for txid {txid}: {e}")

            await asyncio.sleep(30)

        # پس از شکست در تمام تلاش‌ها
        await self.db.update_payment_status(txid, "failed")
        fail_text = (
            "❌ <b>Payment could not be confirmed automatically.</b>\n"
            "Please contact support to resolve the issue."
        )
        translated_error = await self.translation_manager.translate_for_user(fail_text, chat_id)
        await bot.send_message(
            chat_id,
            translated_error,
            parse_mode="HTML",
            reply_markup=await self.keyboards.build_back_exit_keyboard(chat_id)
        )
        self.logger.warning(f"❌ Payment confirmation failed after {max_attempts} tries for txid {txid}")

    # =========================================================================
    #  ب) دریافت و تأیید TxID خریدار
    # =========================================================================
    
    
    async def prompt_trade_txid(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        پس از زدن «💳 I Paid»:
        1) دریافت TxID از کاربر
        2) بررسی تأیید تراکنش روی بلاک‌چین
        3) انتقال توکن در دیتابیس و بستن سفارش
        """
        buyer_id = update.effective_chat.id
        chat_id = buyer_id  # برای ارسال ترجمه
        txid = (update.message.text or "").strip()

        try:
            # ➊ بررسی وجود سفارش در انتظار
            order_id = context.user_data.get("pending_order")
            if not order_id:
                return  # سفارشی در انتظار نیست

            # ➋ اعتبارسنجی فرمت TxID
            if not re.fullmatch(r"[0-9A-Fa-f]{64}", txid):
                msg = "❌ <b>Invalid TxID format.</b>\nPlease send a valid 64-character hash."
                translated = await self.translation_manager.translate_for_user(msg, chat_id)
                return await update.message.reply_text(translated, parse_mode="HTML")

            # ➌ بازیابی سفارش از دیتابیس
            order = await self.db.collection_orders.find_one({"order_id": order_id})
            if not order:
                msg = "❌ <b>Order not found or expired.</b>\nPlease start a new trade."
                translated = await self.translation_manager.translate_for_user(msg, chat_id)
                return await update.message.reply_text(translated, parse_mode="HTML")

            expected_amount = order["amount"] * order["price"]

            # ➍ تأیید تراکنش در بلاک‌چین (Pseudo)
            confirmed = await self.blockchain.verify_txid(txid, TRON_WALLET, expected_amount)
            if not confirmed:
                msg = "⏳ <b>Payment not confirmed yet.</b>\nPlease wait a few moments and try again."
                translated = await self.translation_manager.translate_for_user(msg, chat_id)
                return await update.message.reply_text(translated, parse_mode="HTML")

            # ➎ انتقال توکن و بستن سفارش
            await self.db.transfer_tokens(order["seller_id"], buyer_id, order["amount"])
            await self.db.collection_orders.update_one(
                {"order_id": order_id},
                {"$set": {
                    "status": "completed",
                    "buyer_id": buyer_id,
                    "txid": txid,
                    "updated_at": datetime.utcnow(),
                }}
            )

            # ➏ ویرایش پیام کانال (در صورت امکان)
            try:
                await update.get_bot().edit_message_text(
                    chat_id=TRADE_CHANNEL_ID,
                    message_id=order["channel_msg_id"],
                    text=(
                        f"✅ SOLD\n"
                        f"Buyer: <a href='tg://user?id={buyer_id}'>link</a>"
                    ),
                    parse_mode="HTML",
                )
            except Exception as edit_error:
                self.logger.warning(f"Could not edit channel message for order {order_id}: {edit_error}")

            # ➐ اعلان به فروشنده
            await update.get_bot().send_message(
                order["seller_id"],
                await self.translation_manager.translate_for_user(
                    "🎉 <b>Your tokens were sold!</b> ✅", order["seller_id"]
                ),
                parse_mode="HTML"
            )

            # ➑ اعلان به خریدار
            msg = "✅ <b>Payment confirmed.</b>\nTokens have been credited to your balance."
            translated = await self.translation_manager.translate_for_user(msg, chat_id)
            await update.message.reply_text(translated, parse_mode="HTML")

        except Exception as e:
            self.logger.error(f"Error in prompt_trade_txid: {e}", exc_info=True)
            error_text = (
                "🚫 <b>An error occurred while processing your transaction.</b>\n"
                "Please try again or contact support."
            )
            translated = await self.translation_manager.translate_for_user(error_text, chat_id)
            await update.message.reply_text(translated, parse_mode="HTML")

        finally:
            # 🧼 پاک‌سازی state
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

