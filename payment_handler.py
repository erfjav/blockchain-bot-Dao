

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
from Referral_logic_code import ReferralManager, TokensDepletedError
from core.blockchain_client import BlockchainClient

from datetime import datetime

import config

TXID_REGEX = re.compile(r"^[0-9A-Fa-f]{64}$")   # 64-char hex

# ───── ثابت‌های تنظیمی ───────────────────────────────────────────────
JOIN_FEE_USDT   = 50
TOKEN_SYMBOL    = "USDT"
DECIMALS        = 6                             # USDT on TRON = 6 decimals
POLL_INTERVAL   = 30                            # ثانیه
MAX_ATTEMPTS    = 15                            # ≈ 7.5 دقیقه

TREASURY_WALLET      = config.TREASURY_WALLET.lower()
TREASURY_PRIVATE_KEY = config.TREASURY_PRIVATE_KEY
USDT_CONTRACT        = config.USDT_CONTRACT

SPLIT_WALLETS = [
    (config.SPLIT_WALLET_A, 0.70),
    (config.SPLIT_WALLET_B, 0.25),
    (config.SPLIT_WALLET_C, 0.05),
]

PAYMENT_WALLET_ADDRESS = config.PAYMENT_WALLET_ADDRESS
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
                "1️⃣ Send $50 USDT (TRC-20) to:\n\n",
                f"<code>{self.wallet_address}</code>\n\n",
                "2️⃣ When done, press the button below and select <b>TxID (transaction hash)</b>."
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
    # ➊ متد جدید: تقسیم وجه بین سه کیف‌پول
    # ─────────────────────────────────────────────────────────────
    async def _split_funds(self, amount_usdt: float) -> None:
        """
        انتقال خودکار USDT به سه کیف‌پول طبق نسبت تعریف‌شده.
        """
        if not TREASURY_PRIVATE_KEY:
            self.logger.error("[_split_funds] TREASURY_PRIVATE_KEY not set – aborting split.")
            return

        for addr, ratio in SPLIT_WALLETS:
            if not addr:
                continue  # این کیف‌پول تعریف نشده است
            share = round(amount_usdt * ratio, DECIMALS)
            if share <= 0:
                continue

            try:
                txid = await self.blockchain.transfer_trc20(
                    from_private_key=TREASURY_PRIVATE_KEY,
                    to_address=addr,
                    amount=share,
                    token_contract=USDT_CONTRACT,
                    decimals=DECIMALS,
                    memo="membership split",
                )
                self.logger.info(f"[split] → {addr[-6:]}  {share} USDT  txid={txid}")
            except Exception as e:
                # در صورت خطا، فقط لاگ کنید؛ می‌توانید هشدار تلگرام/ایمیل اضافه کنید
                self.logger.error(f"[split] transfer to {addr} failed: {e}", exc_info=True)



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
          1) تقسیم مبلغ بین سه کیف‌پول
          2) ثبت/فعال‌سازی پروفایل کاربر
          3) ارسال پیام موفق
        در غیر این صورت پس از ۱۵ تلاش → failed
        """
        user_wallet = await self.db.get_wallet_address(chat_id)  # ممکن است None باشد
        tron_api = f"https://api.trongrid.io/wallet/gettransactionbyid?value={txid}"

        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    data = (await client.get(tron_api)).json()

                # ───── بررسی وضعیت و شروط ───────────────────────────
                status_ok = (
                    data.get("ret")
                    and data["ret"][0].get("contractRet") == "SUCCESS"
                )

                prm_value = data["raw_data"]["contract"][0]["parameter"]["value"]
                to_addr   = prm_value.get("to_address", "").lower()
                owner_addr = prm_value.get("owner_address", "").lower()

                to_ok    = to_addr == TREASURY_WALLET
                owner_ok = True if user_wallet is None else owner_addr == user_wallet.lower()

                token_ok = data.get("tokenInfo", {}).get("symbol") == TOKEN_SYMBOL
                amount   = int(data.get("amount_str", "0")) / 10**DECIMALS
                amount_ok = amount >= JOIN_FEE_USDT

                if status_ok and to_ok and owner_ok and token_ok and amount_ok:
                    # ➊ ذخیره وضعیت پرداخت
                    await self.db.update_payment_status(txid, "confirmed")

                    # ➋ تقسیم مبلغ بین سه کیف‌پول
                    await self._split_funds(amount)

                    # ➌ ایجاد/به‌روزرسانی پروفایل و تخصیص توکن
                    profile = await self.referral_manager.ensure_user(
                        chat_id,
                        inviter_code=context.user_data.get("inviter_code"),
                        first_name=bot.get_chat(chat_id).first_name,
                    )

                    # ➍ پیام موفقیت
                    success_msg = (
                        "✅ Payment confirmed!\n\n"
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

                # اگر تراکنش یافت شد ولی شروط کامل نبود
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

        # ───── پس از بی‌نتیجه ماندن تلاش‌ها ─────────────────────────
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
                to_address=TREASURY_WALLET,
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
    
   

###################################################################################################################




    # # ─────────────────────────────────────────────────────────────────────
    # async def monitor_payment(self,
    #                         chat_id: int,
    #                         txid: str,
    #                         context: ContextTypes.DEFAULT_TYPE) -> None:
    #     """
    #     پایش تراکنش در TronGrid و تأیید همهٔ شروط امنیتی:
    #     • وضعیت SUCCESS
    #     • to_address == TREASURY_WALLET
    #     • symbol == USDT
    #     • amount >= JOIN_FEE_USDT
    #     • owner_address == wallet ثبت‌شدهٔ کاربر (در صورت وجود)
    #     در صورت موفقیت: status = confirmed  → تخصیص توکن  → پیام موفق
    #     در غیر این صورت: پس از MAX_ATTEMPTS → status = failed → پیام خطا
    #     """
    #     bot = context.bot
    #     user_wallet = await self.db.get_wallet_address(chat_id)      # ممکن است None باشد

    #     tron_api = f"https://api.trongrid.io/wallet/gettransactionbyid?value={txid}"

    #     for attempt in range(1, MAX_ATTEMPTS + 1):
    #         try:
    #             async with httpx.AsyncClient(timeout=10) as client:
    #                 resp = await client.get(tron_api)
    #                 data = resp.json()

    #             # ───── وضعیت تراکنش ─────────────────────────────────────
    #             status_ok = (
    #                 data.get("ret") and
    #                 data["ret"][0].get("contractRet") == "SUCCESS"
    #             )

    #             # ───── آدرس‌های مقصد / مبدا ─────────────────────────────
    #             prm_value  = data["raw_data"]["contract"][0]["parameter"]["value"]
    #             to_addr    = prm_value.get("to_address", "").lower()
    #             owner_addr = prm_value.get("owner_address", "").lower()

    #             # اگر TREASURY_WALLET در base58 آمده، به hex تبدیل کنید یا برعکس
    #             to_ok    = to_addr == TREASURY_WALLET
    #             owner_ok = True if user_wallet is None else owner_addr == user_wallet.lower()

    #             # ───── توکن و مبلغ ──────────────────────────────────────
    #             token_ok  = data.get("tokenInfo", {}).get("symbol") == TOKEN_SYMBOL
    #             amount    = int(data.get("amount_str", "0")) / 10**DECIMALS
    #             amount_ok = amount >= JOIN_FEE_USDT

    #             # ───── سناریوی موفقیت کامل ─────────────────────────────
    #             if status_ok and to_ok and owner_ok and token_ok and amount_ok:
    #                 await self.db.update_payment_status(txid, "confirmed")

    #                 profile = await self.referral_manager.ensure_user(
    #                     chat_id,
    #                     inviter_code=context.user_data.get("inviter_code"),
    #                     first_name=bot.get_chat(chat_id).first_name
    #                 )

    #                 success_msg = (
    #                     f"✅ Payment confirmed!\n\n"
    #                     f"• Member No: <b>{profile['member_no']}</b>\n"
    #                     f"• Referral Code: <code>{profile['referral_code']}</code>\n"
    #                     f"• Tokens Allocated: <b>{profile['tokens']:.0f}</b>"
    #                 )
    #                 translated = await self.translation_manager.translate_for_user(
    #                     success_msg, chat_id
    #                 )
    #                 await bot.send_message(
    #                     chat_id,
    #                     translated,
    #                     parse_mode="HTML",
    #                     reply_markup=await self.keyboards.build_main_menu_keyboard_v2(chat_id)
    #                 )
    #                 self.logger.info(f"[monitor_payment] ✅ confirmed for {chat_id}")
    #                 return

    #             # ───── تراکنش یافت شد ولی شرایط کافی نیست ───────────────
    #             if status_ok and (not to_ok or not token_ok or not amount_ok or not owner_ok):
    #                 await self.db.update_payment_status(txid, "failed")
    #                 fail_reason = "destination / amount / owner mismatch"
    #                 self.logger.warning(f"[monitor_payment] {fail_reason} for {chat_id}")

    #                 warn_msg = (
    #                     "❌ TxID is valid but does not match the required criteria "
    #                     "(destination, amount, or your wallet). Please verify and try again."
    #                 )
    #                 translated_warn = await self.translation_manager.translate_for_user(
    #                     warn_msg, chat_id
    #                 )
    #                 await bot.send_message(
    #                     chat_id,
    #                     translated_warn,
    #                     parse_mode="HTML",
    #                     reply_markup=await self.keyboards.build_back_exit_keyboard(chat_id)
    #                 )
    #                 return

    #         except Exception as e:
    #             self.logger.warning(f"[monitor_payment] attempt {attempt}: {e}")

    #         # ───── صبر و تلاش مجدد ──────────────────────────────────────
    #         await asyncio.sleep(POLL_INTERVAL)

    #     # ───── پس از تلاش‌های بی‌نتیجه ─────────────────────────────────
    #     await self.db.update_payment_status(txid, "failed")
    #     error_msg = (
    #         "❌ <b>Payment was not confirmed within the expected time.</b>\n"
    #         "If you already paid, please contact support with your TxID."
    #     )
    #     translated_error = await self.translation_manager.translate_for_user(
    #         error_msg, chat_id
    #     )
    #     await bot.send_message(
    #         chat_id,
    #         translated_error,
    #         parse_mode="HTML",
    #         reply_markup=await self.keyboards.build_back_exit_keyboard(chat_id)
    #     )
    #     self.logger.warning(f"[monitor_payment] FAILED after {MAX_ATTEMPTS} for {chat_id}")   