

# payment_handler.py

from __future__ import annotations
import os
import logging
import asyncio
import httpx
import re

from datetime import datetime
from typing import List, Tuple

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from bot_ui.language_Manager import TranslationManager
from bot_ui.keyboards import TranslatedKeyboards
from error_handler import ErrorHandler
from state_manager import push_state
from myproject_database import Database
from Referral_logic_code import ReferralManager
from core.blockchain_client import BlockchainClient

from datetime import datetime
from decimal import Decimal
import config

TXID_REGEX = re.compile(r"^[0-9A-Fa-f]{64}$")   # 64-char hex
JOIN_FEE_USD        = Decimal("50")
# ───── ثابت‌های تنظیمی ───────────────────────────────────────────────
JOIN_FEE_USDT   = 50
TOKEN_SYMBOL    = "USDT"
DECIMALS        = 6                             # USDT on TRON = 6 decimals
POLL_INTERVAL   = 30                            # ثانیه
MAX_ATTEMPTS    = 15                            # ≈ 7.5 دقیقه

# WALLET_JOIN_POOL: Address where membership fees are collected
WALLET_JOIN_POOL = config.WALLET_JOIN_POOL


TRADE_CHANNEL_ID = config.TRADE_CHANNEL_ID

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
        
        self.wallet_address = WALLET_JOIN_POOL or "TXXYYZZ_PLACEHOLDER_ADDRESS"
        self.logger = logging.getLogger(self.__class__.__name__)
        
    #-----------------------------------------------------------------------------------------
    async def show_payment_instructions(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        chat_id    = update.effective_chat.id
        first_name = update.effective_user.first_name

        try:
            # اطمینان از وجود رکورد کاربر
            await self.db.insert_user_if_not_exists(chat_id, first_name)

            profile = await self.db.get_profile(chat_id)

            lines = ["💳 <b>Payment Instructions</b>\n"]
            if profile:
                lines += [
                    f"• Member No: <b>{profile['member_no']}</b>",
                    f"• Referral Code: <code>{profile['referral_code']}</code>",
                    f"• Current Balance: <b>${profile['commission_usd']:.2f}</b>\n"
                ]
            else:
                lines += [
                    "• Member No: —",
                    "• Referral Code: —",
                    "• Current Balance: —\n"
                ]

            lines += [
                "1️⃣ Send $50 USDT (TRC-20) to:\n\n",
                f"<code>{self.wallet_address}</code>\n\n",
                "2️⃣ After sending, press the button below and select <b>TxID</b>."
            ]
            msg = "\n".join(lines)

            # تنظیم state برای دریافت TxID
            push_state(context, "prompt_txid")
            await update.message.reply_text(
                await self.translation_manager.translate_for_user(msg, chat_id),
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("TxID (transaction hash)", callback_data="prompt_txid")],
                    [InlineKeyboardButton("⬅️ Back", callback_data="main_menu"),
                     InlineKeyboardButton("Exit",   callback_data="exit")]
                ])
            )
        except Exception as e:
            await self.eh.handle(update, context, e)    

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
        دریافت TxID از کاربر، بررسی اعتبار و تکراری نبودن، ثبت در DB،
        و آغاز فرآیند تأیید در بلاک‌چین
        """
        chat_id = update.effective_chat.id
        txid = (update.message.text or "").strip()

        try:
            # ── ۱) ولیدیشن فرمت ───────────────────────────────
            if not TXID_REGEX.fullmatch(txid):
                invalid_msg = (
                    "🚫 <b>Invalid TxID format.</b>\n"
                    "Please send a valid 64-character hash containing only letters and numbers."
                )
                translated = await self.translation_manager.translate_for_user(invalid_msg, chat_id)
                return await update.message.reply_text(
                    translated,
                    parse_mode="HTML",
                    reply_markup=await self.keyboards.build_back_exit_keyboard(chat_id)
                )

            # ── ۲) چک تکراری‌بودن ─────────────────────────────
            if await self.db.is_txid_used(txid):
                duplicate_msg = (
                    "❌ <b>This TxID has already been submitted.</b>\n"
                    "If you think this is an error, please contact support."
                )
                translated = await self.translation_manager.translate_for_user(duplicate_msg, chat_id)
                return await update.message.reply_text(
                    translated,
                    parse_mode="HTML",
                    reply_markup=await self.keyboards.build_back_exit_keyboard(chat_id)
                )

            # ── ۳) درج در DB ─────────────────────────────────
            try:
                await self.db.store_payment_txid(chat_id, txid)
            except Exception as e:
                self.logger.error(f"[handle_txid] DB error: {e}", exc_info=True)
                db_error_msg = (
                    "🚫 <b>Internal error while storing your TxID.</b>\n"
                    "Please try again later."
                )
                translated = await self.translation_manager.translate_for_user(db_error_msg, chat_id)
                return await update.message.reply_text(
                    translated,
                    parse_mode="HTML",
                    reply_markup=await self.keyboards.build_back_exit_keyboard(chat_id)
                )

            # ── ۴) ذخیره state ────────────────────────────────
            push_state(context, "sub_txid_received")
            context.user_data["state"] = "sub_txid_received"

            # ── ۵) پیام تأیید به کاربر ───────────────────────
            confirm_msg = (
                "✅ <b>TxID received!</b>\n"
                "We’ll notify you once your transaction is confirmed on the blockchain."
            )
            translated = await self.translation_manager.translate_for_user(confirm_msg, chat_id)
            await update.message.reply_text(
                translated,
                parse_mode="HTML",
                reply_markup=await self.keyboards.build_back_exit_keyboard(chat_id)
            )

            # ── ۶) آغاز پایش بلاک‌چین ─────────────────────────
            context.application.create_task(
                self.monitor_payment(chat_id=chat_id, txid=txid, bot=context.bot)
            )

        except Exception as e:
            self.logger.error(f"Unexpected error in handle_txid: {e}", exc_info=True)
            error_msg = (
                "⚠️ <b>An unexpected error occurred while processing your TxID.</b>\n"
                "Please try again later or contact support."
            )
            translated = await self.translation_manager.translate_for_user(error_msg, chat_id)
            await update.message.reply_text(
                translated,
                parse_mode="HTML",
                reply_markup=await self.keyboards.build_back_exit_keyboard(chat_id)
            )

    # ─────────────────────────────────────────────────────────────
    # ➋ پایش تراکنش روی بلاک‌چین و تخصیص توکن
    # ─────────────────────────────────────────────────────────────
    async def monitor_payment(
        self,
        chat_id: int,
        txid: str,
        bot,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """
        هر ۳۰ ثانیه وضعیت تراکنش TRC-20 را چک می‌کند تا تأیید شود.
        پس از تأیید:
          1) ثبت وضعیت پرداخت
          2) فراخوانی ReferralManager برای تقسیم کمیسیون و تخصیص airdrop
          3) ایجاد/به‌روزرسانی پروفایل کاربر
          4) ارسال پیام موفقیت
        در غیر این صورت پس از ۱۵ تلاش → وضعیت failed
        """
        # بارگذاری کیف‌پول join-pool به صورت lowercase برای مقایسه
        join_pool_address = self.wallet_address.lower()

        tron_api = f"https://api.trongrid.io/wallet/gettransactionbyid?value={txid}"

        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    data = (await client.get(tron_api)).json()

                # بررسی موفقیت قرارداد و امضا
                status_ok = (
                    data.get("ret")
                    and data["ret"][0].get("contractRet") == "SUCCESS"
                )

                prm = data["raw_data"]["contract"][0]["parameter"]["value"]
                to_addr = prm.get("to_address", "").lower()
                owner_addr = prm.get("owner_address", "").lower()

                # بررسی مقصد و فرستنده
                to_ok = to_addr == join_pool_address
                user_wallet = await self.db.get_wallet_address(chat_id)
                owner_ok = True if not user_wallet else owner_addr == user_wallet.lower()

                # بررسی توکن و مقدار
                token_ok = data.get("tokenInfo", {}).get("symbol") == TOKEN_SYMBOL
                amount = int(data.get("amount_str", "0")) / 10**DECIMALS
                amount_ok = amount >= JOIN_FEE_USD

                if status_ok and to_ok and owner_ok and token_ok and amount_ok:
                    # 1) ذخیره وضعیت پرداخت
                    await self.db.update_payment_status(txid, "confirmed")

                    # 2) تقسیم کمیسیون و تخصیص airdrop
                    # ابتدا پروفایل کاربر را بساز/بروزرسانی کن
                    profile = await self.referral_manager.ensure_user(
                        user_id=chat_id,
                        first_name=bot.get_chat(chat_id).first_name,
                        inviter_id=context.user_data.get("inviter_id")
                    )
                    # سپس گردش 50$ join-fee را در ReferralManager انجام بده
                    await self.referral_manager._distribute_commission(profile)

                    # 3) ارسال پیام موفقیت
                    success_msg = (
                        "✅ پرداخت با موفقیت ثبت شد!\n\n"
                        f"• Member No: <b>{profile['member_no']}</b>\n"
                        f"• Referral Code: <code>{profile['referral_code']}</code>\n"
                        f"• Tokens Allocated: <b>{profile['tokens']:.0f}</b>"
                    )
                    translated = await self.translation_manager.translate_for_user(
                        success_msg, chat_id
                    )
                    await bot.send_message(
                        chat_id,
                        translated,
                        parse_mode="HTML",
                        reply_markup=await self.keyboards.build_main_menu_keyboard_v2(
                            chat_id
                        ),
                    )
                    self.logger.info(f"[monitor_payment] ✅ confirmed for {chat_id}")
                    return

                # تراکنش موجود ولی معیارها برقرار نیست
                if status_ok and (not to_ok or not token_ok or not amount_ok or not owner_ok):
                    await self.db.update_payment_status(txid, "failed")
                    warn_msg = (
                        "❌ TxID is valid but does not match the required criteria "
                        "(destination, amount, or your wallet). Please verify and try again."
                    )
                    translated_warn = await self.translation_manager.translate_for_user(
                        warn_msg, chat_id
                    )
                    await bot.send_message(
                        chat_id,
                        translated_warn,
                        parse_mode="HTML",
                        reply_markup=await self.keyboards.build_back_exit_keyboard(chat_id),
                    )
                    return

            except Exception as e:
                self.logger.warning(f"[monitor_payment] attempt {attempt}: {e}")

            await asyncio.sleep(POLL_INTERVAL)

        # پس از اتمام تلاش‌ها
        await self.db.update_payment_status(txid, "failed")
        error_msg = (
            "❌ <b>Payment was not confirmed within the expected time.</b>\n"
            "If you already paid, please contact support with your TxID."
        )
        translated_error = await self.translation_manager.translate_for_user(
            error_msg, chat_id
        )
        await bot.send_message(
            chat_id,
            translated_error,
            parse_mode="HTML",
            reply_markup=await self.keyboards.build_back_exit_keyboard(chat_id),
        )
        self.logger.warning(f"[monitor_payment] FAILED after {MAX_ATTEMPTS} for {chat_id}")

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
            confirmed = await self.blockchain.verify_txid(
                txid=txid,
                to_address=self.wallet_address,
                expected_usdt_amount=expected_amount,
            )
            
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
    




