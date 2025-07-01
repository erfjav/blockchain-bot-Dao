

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
        self.keyboards = keyboards
        self.t = translation_manager
        self.eh = error_handler
        self.db = db
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
                await self.t.translate_for_user(msg, chat_id),
                parse_mode="HTML",
                reply_markup=reply_kb,
            )

        except Exception as e:
            await self.eh.handle(update, context, e, context_name="show_payment_instructions")


    async def prompt_for_txid(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        وقتی کاربر دکمه‌ی “TxID (transaction hash)” را می‌زند:
        1) ست‌کردن state = awaiting_sub_txid
        2) درخواست ارسال هش
        """
        chat_id = update.effective_chat.id

        # ➊ رفتن به فاز دریافت TxID
        # push_state(context, "awaiting_txid")
        context.user_data["state"] = "awaiting_sub_txid"

        await update.message.reply_text(
            "🔔 لطفاً TxID (transaction hash) خود را ارسال کنید:",
            reply_markup=await self.keyboards.build_back_exit_keyboard(chat_id)
        )


    def is_valid_txid(self, txid: str) -> bool:
        """
        اعتبارسنجی TxID:
        - فرض: 64 کاراکتر هگز [0-9A-Fa-f]
        """
        return bool(re.fullmatch(r"[0-9A-Fa-f]{64}", txid))

    async def handle_txid(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        دریافت TxID از کاربر، درج آن در DB و آغاز مانیتور پرداخت.
        به‌جای تخصیص توکن اینجا، تسکی می‌سازیم که خودکار پرداخت را تأیید و
        سپس پروفایل کاربر را نهایی کند.
        """
        chat_id = update.effective_chat.id
        txid    = update.message.text.strip()

        # ➊ ست کردن state جدید
        push_state(context, "sub_txid_received")
        context.user_data["state"] = "txid_received"

        # ➋ ذخیره TxID در DB
        await self.db.store_payment_txid(chat_id, txid)

        # ➌ پیام اولیه به کاربر
        await update.message.reply_text(
            "✅ TxID received! We will notify you once your payment is confirmed.",
            reply_markup=await self.keyboards.build_back_exit_keyboard(chat_id)
        )

        # ➍ ساخت تسک پس‌زمینه برای مانیتور پرداخت
        #    از context.application برای ایجاد task استفاده می‌کنیم
        context.application.create_task(
            self.monitor_payment(chat_id, txid, context.bot)
        )
        
########################################################################################################
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
                    await bot.send_message(
                        chat_id,
                        msg,
                        parse_mode="HTML",
                        reply_markup=await self.keyboards.build_main_menu_keyboard_v2(chat_id)
                    )
                    return

            except Exception:
                # نادیده می‌گیریم و بعداً دوباره تلاش می‌کنیم
                pass

            await asyncio.sleep(30)  # ۳۰ ثانیه تا تلاش بعدی

        # اگر بعد از max_attempts تأیید نشد → شکست
        await self.db.update_payment_status(txid, "failed")
        await bot.send_message(
            chat_id,
            "❌ Payment could not be confirmed automatically. "
            "Please contact support.",
            reply_markup=await self.keyboards.build_back_exit_keyboard(chat_id)
        )


    # =========================================================================
    #  ب) دریافت و تأیید TxID خریدار
    # =========================================================================
    async def prompt_trade_txid(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        پس از زدن «💳 I Paid»:
        1) انتظار دریافت TXID
        2) تأیید در بلاک‌چین (مثال ساده)
        3) انتقال توکن در DB و بستن Order
        """
        buyer_id  = update.effective_chat.id
        order_id  = context.user_data.get("pending_order")
        if not order_id:
            return  # سفارشی در انتظار نیست

        txid = update.message.text.strip()
        if not re.fullmatch(r"[0-9A-Fa-f]{64}", txid):
            return await update.message.reply_text("Invalid TXID, try again.")

        # ─── تأیید تراکنش در بلاک‌چین (Pseudo) ───────────────────
        order = await self.db.collection_orders.find_one({"order_id": order_id})
        expected_amount = order["amount"] * order["price"]
        confirmed = await self.blockchain.verify_txid(txid, TRON_WALLET, expected_amount)

        if not confirmed:
            return await update.message.reply_text("Payment not confirmed yet.")

        # ─── انتقال توکن در DB (اتمیک) ───────────────────────────
        await self.db.transfer_tokens(order["seller_id"], buyer_id, order["amount"])
        await self.db.collection_orders.update_one(
            {"order_id": order_id},
            {"$set": {
                "status":     "completed",
                "buyer_id":   buyer_id,
                "txid":       txid,
                "updated_at": datetime.utcnow(),
            }}
        )

        # ─── ویرایش پیام کانال ──────────────────────────────────
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
        except Exception:
            pass  # اگر پیام حذف یا ویرایش شده بود نادیده بگیر

        # ─── اعلان به طرفین ─────────────────────────────────────
        await update.get_bot().send_message(
            order["seller_id"], "🎉 Your tokens were sold! ✅"
        )
        await update.message.reply_text("Payment confirmed, tokens credited. ✅")

        # پاک‌سازی state
        context.user_data.clear()

