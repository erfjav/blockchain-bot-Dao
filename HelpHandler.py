

import logging
from telegram import Update
from telegram.ext import ContextTypes
from error_handler import ErrorHandler
from language_Manager import TranslationManager
from Translated_Inline_Keyboards import TranslatedInlineKeyboards
from keyboards import TranslatedKeyboards
from myproject_database import Database
from state_manager import pop_state, push_state, reset_state

from telegram import InlineKeyboardButton

class HelpHandler:
    """
    A class to handle help messages for the bot, including sending a short help message
    and detailed help for various features with inline buttons.
    """
    def __init__(
        self,
        logger: logging.Logger,
        db: Database,
        keyboards: TranslatedKeyboards,
        translation_manager: TranslationManager,
        inline_translator: TranslatedInlineKeyboards,
        error_handler: ErrorHandler,
    ): 
        self.db = db
        self.logger = logger
        self.inline_translator = inline_translator
        self.translation_manager = translation_manager
        self.keyboards = keyboards
        self.error_handler = error_handler

            
    # ✅ Main Help Entry
    async def show_help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            
            # ───➤ ست‌کردن state برای این مرحله
            push_state(context, "showing_guide")
            # (اختیاری برای backward-compatibility)
            context.user_data['state'] = "showing_guide"                  
            
            chat_id = update.effective_chat.id
            user_first = update.effective_user.first_name

            help_intro = (
                f"<b>👋 Welcome, {user_first}!</b>\n\n"
                "This is the Help Center where you can learn how to use each feature of the bot.\n\n"
                "Whether you’re here to trade, withdraw, earn, or manage your account — we’ve got you covered.\n\n"
                "Tap 'More Details' to explore guides for each button."
            )

            keyboard = [
                [InlineKeyboardButton("📖 More Details", callback_data="show_details_help"),
                InlineKeyboardButton("➡️ Exit", callback_data="exit_help")]
            ]

            reply_markup = await self.inline_translator.build_inline_keyboard_for_user(keyboard, chat_id)
            translated = await self.translation_manager.translate_for_user(help_intro, chat_id)

            await update.message.reply_text(
                translated,
                reply_markup=reply_markup,
                parse_mode="HTML"
            )
        except Exception as e:
            await self.error_handler.handle(update, context, e, context_name="show_help_command")            
        

    # ✅ Help Details Menu
    async def help_details_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            query = update.callback_query
            await query.answer()
            chat_id = query.message.chat.id

            text = (
                "<b>📘 Feature Overview – Let’s dive deeper!</b>\n\n"
                "Here you’ll find detailed help on each of the bot’s features.\n"
                "Choose any option below to learn more about how it works and how to use it effectively:\n\n"
                "• 💳 <b>Payment</b> – Deposit funds securely\n"
                "• 💵 <b>Withdraw</b> – Transfer your balance to your wallet\n"
                "• 💰 <b>Trade</b> – Buy or sell tokens\n"
                "• 🔄 <b>Convert Token</b> – Swap between token types\n"
                "• 📊 <b>Token Price</b> – See the latest rates\n"
                "• 🪙 <b>Earn Money</b> – Referral rewards and commissions\n"
                "• 👤 <b>Profile</b> – Wallet and earnings info\n"
                "• 🌐 <b>Language</b> – Change your preferred interface\n"
                "• 🧭 <b>Help & Support</b> – Still confused? Get assistance\n\n"
                "👇 Tap a button below to learn more."
            )

            raw_keyboard = [
                [InlineKeyboardButton("💳 Payment", callback_data="help_payment"),
                InlineKeyboardButton("💵 Withdraw", callback_data="help_withdraw")],
                [InlineKeyboardButton("💰 Trade", callback_data="help_trade"),
                InlineKeyboardButton("🔄 Convert", callback_data="help_convert")],
                [InlineKeyboardButton("📊 Token Price", callback_data="help_token_price"),
                InlineKeyboardButton("🪙 Earn Money", callback_data="help_earn")],
                [InlineKeyboardButton("👤 Profile", callback_data="help_profile"),
                InlineKeyboardButton("🌐 Language", callback_data="help_language")],
                [InlineKeyboardButton("🧭 Help & Support", callback_data="help_support"),
                InlineKeyboardButton("➡️ Exit", callback_data="exit_help")],
                [InlineKeyboardButton("⬅️ Back", callback_data="hide_details_help")]
            ]

            reply_markup = await self.inline_translator.build_inline_keyboard_for_user(raw_keyboard, chat_id)
            msg_final = await self.translation_manager.translate_for_user(text, chat_id)

            await query.edit_message_text(text=msg_final, reply_markup=reply_markup, parse_mode="HTML")
        except Exception as e:
            await self.error_handler.handle(update, context, e, context_name="help_details_callback")

    async def hide_details_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Handle the Back button in the detailed Help menu:
        1) Pop the current state
        2) Edit the message back to the main Help menu
        """
        try:
            query = update.callback_query
            await query.answer()
            # ۱) Pop current help-details state
            pop_state(context)

            # ۲) آماده‌سازی متن و کیبورد منوی اصلی Help
            chat_id    = query.message.chat.id
            user_first = update.effective_user.first_name or ""
            help_intro = (
                f"<b>👋 Welcome, {user_first}!</b>\n\n"
                "This is the Help Center where you can learn how to use each feature of the bot.\n\n"
                "Whether you’re here to trade, withdraw, earn, or manage your account — we’ve got you covered.\n\n"
                "Tap 'More Details' to explore guides for each button."
            )
            keyboard = [
                [
                    InlineKeyboardButton("📖 More Details", callback_data="show_details_help"),
                    InlineKeyboardButton("➡️ Exit",        callback_data="exit_help")
                ]
            ]
            reply_markup = await self.inline_translator.build_inline_keyboard_for_user(keyboard, chat_id)
            translated   = await self.translation_manager.translate_for_user(help_intro, chat_id)

            # ۳) ویرایش پیام جاری به منوی اصلی Help
            await query.edit_message_text(
                translated,
                reply_markup=reply_markup,
                parse_mode="HTML"
            )

        except Exception as e:
            await self.error_handler.handle(
                update, context, e, context_name="hide_details_callback"
            )


#--------------------------------- exit_help_callback ------------------------------------------------------------------------
    async def exit_help_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Handle 'Exit' action from the help sections.
        This method should close the help session (for example, clear the help message or return a goodbye message).
        """
        try:
            
            chat_id = update.effective_chat.id
            user_first_name = update.effective_user.first_name
            query = update.callback_query
            
            await query.answer()
            
            user_language = await self.db.get_user_language(chat_id)
            rtl_languages = ["fa", "ar", "he", "ur"]
            if user_language.lower() in rtl_languages:
                rlm = "\u200F"
                display_name = f"{rlm}{user_first_name}{rlm}"
            else:
                display_name = user_first_name   

            msg_en = "Thank you {name}! If you need further assistance, feel free to ask."
            translated_template = await self.translation_manager.translate_for_user(msg_en, chat_id)
            # جایگذاری نام واقعی کاربر در متن ترجمه شده
            final_msg = translated_template.format(name=display_name)            
            await query.edit_message_text(final_msg)
        except Exception as e:
            await self.error_handler.handle(update, context, e, context_name="exit_help_callback")

    #----------------------------------------------------------------------------------------------------------
    async def handle_invalid_help_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        وقتی کاربر در حالت help پیام نامعتبر بده.
        """
        try:
            chat_id = update.effective_chat.id
            state = context.user_data.get("state")

            if state == "showing_guide":
                msg = (
                    "❗ You're currently in the Help section.\n"
                    "Please use the menu buttons below or press 'Back' to return."
                )
                translated = await self.translation_manager.translate_for_user(msg, chat_id)

                await update.message.reply_text(
                    translated,
                    parse_mode="HTML",
                    reply_markup=await self.keyboards.build_back_exit_keyboard(chat_id)
                )
                return True
            return False

        except Exception as e:
            await self.error_handler.handle(update, context, e, context_name="handle_invalid_help_input")
            return False
    #----------------------------------------------------------------------------------------------------------

    # ✅ Withdraw
    async def help_withdraw_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            query = update.callback_query
            await query.answer()
            chat_id = query.message.chat.id

            text = (
                "<b>💵 Withdraw</b>\n\n"
                "Use this option to request withdrawal of your token balance.\n\n"
                "<b>Steps:</b>\n"
                "1. Choose withdrawal amount.\n"
                "2. Enter your wallet address.\n"
                "3. Confirm your request.\n\n"
                "Once confirmed, your request will be processed and you’ll receive tokens in your wallet.\n\n"
                "⚠️ <b>Common Mistakes to Watch Out For:</b>\n"
                "• Make sure you’ve completed the $50 membership payment and have at least 2 direct referrals — otherwise you won’t be eligible.\n\n"
                "• **Double-check your wallet address** before confirming. Sending to the wrong address results in permanent loss.\n\n"
                "• Don’t close the bot or navigate away while your withdrawal is in progress — that can interrupt processing.\n\n"
                "• If the blockchain network is congested, withdrawals can be delayed. **Wait a few minutes** before retrying.\n\n"
                "⏳ Processing time depends on network congestion, but usually takes a few minutes."
            )
            keyboard = [
                [InlineKeyboardButton("⬅️ Back", callback_data="help_details"),
                InlineKeyboardButton("➡️ Exit", callback_data="exit_help")]
            ]
            reply_markup = await self.inline_translator.build_inline_keyboard_for_user(keyboard, chat_id)
            
            msg_final = await self.translation_manager.translate_for_user(text, chat_id)
            await query.edit_message_text(msg_final, reply_markup=reply_markup, parse_mode="HTML")
            
        except Exception as e:
            await self.error_handler.handle(update, context, e, context_name="help_withdraw_callback")

#########-------------------------------------------------------------------------------------------------------

    # ✅ Trade
    async def help_trade_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            query = update.callback_query
            await query.answer()
            chat_id = query.message.chat.id

            text = (
                "<b>💰 Trade</b>\n\n"
                "Use this to <b>buy or sell tokens</b> securely through the bot.\n\n"
                "<b>Features:</b>\n"
                "• Set custom prices or use market rates\n"
                "• Bot shows real-time confirmations\n"
                "• Your trades are logged and trackable in your history\n\n"
                "Ensure your wallet is set and you have sufficient balance before using this feature."
            )
            
            raw_keyboard = [
                [InlineKeyboardButton("🛒 Buy", callback_data="help_trade_buy"),
                 InlineKeyboardButton("💸 Sell", callback_data="help_trade_sell")],
                [InlineKeyboardButton("⬅️ Back", callback_data="help_details"),
                 InlineKeyboardButton("➡️ Exit", callback_data="exit_help")]
            ]
            
            reply_markup = await self.inline_translator.build_inline_keyboard_for_user(raw_keyboard, chat_id)
            
            msg_final = await self.translation_manager.translate_for_user(text, chat_id)
            
            await query.edit_message_text(msg_final, reply_markup=reply_markup, parse_mode="HTML")
        except Exception as e:
            await self.error_handler.handle(update, context, e, context_name="help_trade_callback")


    # 🛒 Trade: Buy Explanation
    async def help_trade_buy_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            query = update.callback_query
            await query.answer()
            chat_id = query.message.chat.id

            text = (
                "<b>🛒 Buy Tokens</b>\n\n"
                "Use this option to purchase tokens using your balance or linked payment method.\n\n"
                "<b>Steps:</b>\n"
                "1. Enter the amount of tokens you wish to buy.\n"
                "2. Review the total cost at current rate.\n"
                "3. Confirm your purchase.\n\n"
                "Once confirmed, tokens will be credited to your wallet instantly."
            )

            raw_keyboard = [
                [InlineKeyboardButton("⬅️ Back", callback_data="help_trade"),
                 InlineKeyboardButton("➡️ Exit", callback_data="exit_help")]
            ]

            reply_markup = await self.inline_translator.build_inline_keyboard_for_user(raw_keyboard, chat_id)
            msg = await self.translation_manager.translate_for_user(text, chat_id)
            await query.edit_message_text(text=msg, reply_markup=reply_markup, parse_mode="HTML")
        except Exception as e:
            await self.error_handler.handle(update, context, e, context_name="help_trade_buy_callback")

    # 💸 Trade: Sell Explanation
    async def help_trade_sell_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            query = update.callback_query
            await query.answer()
            chat_id = query.message.chat.id

            text = (
                "<b>💸 Sell Tokens</b>\n\n"
                "Use this option to sell your tokens back into your balance or preferred payout method.\n\n"
                "<b>Steps:</b>\n"
                "1. Enter the amount of tokens you wish to sell.\n\n"
                "2. Review the total you will receive after fees.\n\n"
                "3. Confirm your sale.\n\n"
                "Once confirmed, proceeds will be added to your balance immediately."
            )

            raw_keyboard = [
                [InlineKeyboardButton("⬅️ Back", callback_data="help_trade"),
                 InlineKeyboardButton("➡️ Exit", callback_data="exit_help")]
            ]

            reply_markup = await self.inline_translator.build_inline_keyboard_for_user(raw_keyboard, chat_id)
            msg = await self.translation_manager.translate_for_user(text, chat_id)
            await query.edit_message_text(text=msg, reply_markup=reply_markup, parse_mode="HTML")
        except Exception as e:
            await self.error_handler.handle(update, context, e, context_name="help_trade_sell_callback")

#########-------------------------------------------------------------------------------------------------------

    # ✅ Token Price
    async def help_token_price_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            query = update.callback_query
            await query.answer()
            chat_id = query.message.chat.id

            text = (
                "<b>📊 Token Price</b>\n\n"
                "This feature lets you check the <b>live price</b> of our token based on recent trades and market rates.\n\n"
                "It includes:\n"
                "• Real-time token value in IRT and USD\n"
                "• 24-hour price change\n"
                "• Last updated timestamp\n\n"
                "Prices are updated every few seconds for accuracy."
            )
            keyboard = [
                [InlineKeyboardButton("⬅️ Back", callback_data="help_details"),
                InlineKeyboardButton("➡️ Exit", callback_data="exit_help")]
            ]
            reply_markup = await self.inline_translator.build_inline_keyboard_for_user(keyboard, chat_id)
            msg_final = await self.translation_manager.translate_for_user(text, chat_id)
            await query.edit_message_text(msg_final, reply_markup=reply_markup, parse_mode="HTML")
        except Exception as e:
            await self.error_handler.handle(update, context, e, context_name="help_token_price_callback")


    # ✅ Convert Token
    async def help_convert_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            query = update.callback_query
            await query.answer()
            chat_id = query.message.chat.id

            text = (
                "<b>🔄 Convert Token</b>\n\n"
                "Convert your tokens to other supported assets.\n\n"
                "<b>Options:</b>\n"
                "• Convert between different token types (e.g., Main ↔ Bonus)\n"
                "• View exchange rate before confirming\n"
                "• Instant conversion once approved\n\n"
                "Your conversion history will be saved and shown in the history section."
            )
            keyboard = [
                [InlineKeyboardButton("⬅️ Back", callback_data="help_details"),
                InlineKeyboardButton("➡️ Exit", callback_data="exit_help")]
            ]
            reply_markup = await self.inline_translator.build_inline_keyboard_for_user(keyboard, chat_id)
            msg_final = await self.translation_manager.translate_for_user(text, chat_id)
            await query.edit_message_text(msg_final, reply_markup=reply_markup, parse_mode="HTML")
        except Exception as e:
            await self.error_handler.handle(update, context, e, context_name="help_convert_callback")

#########-------------------------------------------------------------------------------------------------------

    # ✅ Payment
    async def help_payment_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            query = update.callback_query
            await query.answer()
            chat_id = query.message.chat.id

            text = (
                "<b>💳 Payment</b>\n\n"
                "Use this section to deposit funds for membership, services, or purchases.\n\n"
                "• Choose payment method (TRX, USDT, or others)\n"
                "• Get payment address and instructions\n"
                "• Send transaction and submit TxID\n\n"
                "Your membership or service access will activate automatically after confirmation."
            )
            raw_kb = [
                [InlineKeyboardButton("#️⃣ TxID (transaction hash)", callback_data="help_payment_txid")],
                [InlineKeyboardButton("⬅️ Back", callback_data="help_details"),
                 InlineKeyboardButton("➡️ Exit", callback_data="exit_help")]
            ]
            reply_markup = await self.inline_translator.build_inline_keyboard_for_user(raw_kb, chat_id)
            msg_final = await self.translation_manager.translate_for_user(text, chat_id)
            await query.edit_message_text(msg_final, reply_markup=reply_markup, parse_mode="HTML")
        except Exception as e:
            await self.error_handler.handle(update, context, e, context_name="help_payment_callback")

    # 🔗 Help: TxID Details
    async def help_payment_txid_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            query = update.callback_query
            await query.answer()
            chat_id = query.message.chat.id

            text = (
                "<b>#️⃣ TxID (transaction hash)</b>\n\n"
                "After sending your $50 USDT payment, you’ll receive a unique 64-character TxID in your wallet transaction history.\n\n"
                "<b>Steps:</b>\n"
                "1. Copy the full TxID from your wallet.\n"
                "2. Paste it here to confirm your payment.\n"
                "3. The bot will verify the transaction on-chain and activate your profile.\n\n"
                "Use Back to return or Exit to cancel."
            )
            raw_kb = [
                [InlineKeyboardButton("⬅️ Back", callback_data="help_payment")],
                [InlineKeyboardButton("➡️ Exit", callback_data="exit_help")]
            ]
            kb = await self.inline_translator.build_inline_keyboard_for_user(raw_kb, chat_id)
            msg = await self.translation_manager.translate_for_user(text, chat_id)
            await query.edit_message_text(text=msg, reply_markup=kb, parse_mode="HTML")
        except Exception as e:
            await self.error_handler.handle(update, context, e, context_name="help_payment_txid_callback")

#########-------------------------------------------------------------------------------------------------------

    # ✅ Earn Money
    async def help_earn_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            query = update.callback_query
            await query.answer()
            chat_id = query.message.chat.id

            text = (
                "<b>🪙 Earn Money</b>\n\n"
                "Earn passive income through referrals!\n\n"
                "• Share your referral link with friends\n"
                "• Earn token rewards when they sign up or pay\n"
                "• Monitor your referrals and commission stats in your profile\n\n"
                "Grow your community and earn more each time others join."
            )
            keyboard = [
                [InlineKeyboardButton("⬅️ Back", callback_data="help_details"),
                InlineKeyboardButton("➡️ Exit", callback_data="exit_help")]
            ]
            reply_markup = await self.inline_translator.build_inline_keyboard_for_user(keyboard, chat_id)
            msg_final = await self.translation_manager.translate_for_user(text, chat_id)
            await query.edit_message_text(msg_final, reply_markup=reply_markup, parse_mode="HTML")
        except Exception as e:
            await self.error_handler.handle(update, context, e, context_name="help_earn_callback")

#########-------------------------------------------------------------------------------------------------------

    # ✅ Profile
    async def help_profile_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            query = update.callback_query
            await query.answer()
            chat_id = query.message.chat.id

            text = (
                "<b>👤 Profile</b>\n\n"
                "Your personal dashboard for wallet, balance, and referral info.\n\n"
                "• View wallet address\n"
                "• Set or update your wallet\n"
                "• Check balance and earnings\n"
                "• See your referral link and invite count\n\n"
                "Manage your account details from one place."
            )
            raw_keyboard = [
                [InlineKeyboardButton("🕵️‍♂️ See Profile", callback_data="help_profile_see"),
                 InlineKeyboardButton("🏦 Wallet", callback_data="help_profile_wallet")],
                [InlineKeyboardButton("⬅️ Back", callback_data="help_details"),
                 InlineKeyboardButton("➡️ Exit", callback_data="exit_help")]
            ]
            reply_markup = await self.inline_translator.build_inline_keyboard_for_user(raw_keyboard, chat_id)
            msg_final = await self.translation_manager.translate_for_user(text, chat_id)
            await query.edit_message_text(msg_final, reply_markup=reply_markup, parse_mode="HTML")
        except Exception as e:
            await self.error_handler.handle(update, context, e, context_name="help_profile_callback")


    # 🕵️‍♂️ Help: See Profile Details
    async def help_profile_see_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            query = update.callback_query
            await query.answer()
            chat_id = query.message.chat.id

            text = (
                "<b>🕵️‍♂️ See Profile</b>\n\n"
                "This section shows your:"
                "• Member Number and Referral Code \n"
                "• Registered Wallet Address\n"
                "• Token Balance, Pending Commissions, and Down‑line Count\n\n"
                "Use this information to share your referral link and track your earnings."
            )
            raw_keyboard = [
                [InlineKeyboardButton("⬅️ Back", callback_data="help_profile"),
                 InlineKeyboardButton("➡️ Exit", callback_data="exit_help")]
            ]
            kb = await self.inline_translator.build_inline_keyboard_for_user(raw_keyboard, chat_id)
            msg = await self.translation_manager.translate_for_user(text, chat_id)
            await query.edit_message_text(text=msg, reply_markup=kb, parse_mode="HTML")
        except Exception as e:
            await self.error_handler.handle(update, context, e, context_name="help_profile_see_callback")

    # 🏦 Help: Wallet Menu Details
    async def help_profile_wallet_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            query = update.callback_query
            await query.answer()
            chat_id = query.message.chat.id

            text = (
                "<b>🏦 Wallet Menu</b>\n\n"
                "Manage your crypto wallet and perform key operations:\n\n"
                "• Set Wallet: Register your wallet address.\n"
                "• Edit Wallet: Update your existing address.\n"
                "• Transfer Tokens: Send tokens to another address.\n"
                "• View Balance: Check your current token balance.\n"
                "• View History: See your recent wallet transactions.\n\n"
                "Select any option from your profile menu to use these features."
            )
            raw_keyboard = [
                [InlineKeyboardButton("⬅️ Back", callback_data="help_profile"),
                 InlineKeyboardButton("➡️ Exit", callback_data="exit_help")]
            ]
            kb = await self.inline_translator.build_inline_keyboard_for_user(raw_keyboard, chat_id)
            msg = await self.translation_manager.translate_for_user(text, chat_id)
            await query.edit_message_text(text=msg, reply_markup=kb, parse_mode="HTML")
        except Exception as e:
            await self.error_handler.handle(update, context, e, context_name="help_profile_wallet_callback")

#########-------------------------------------------------------------------------------------------------------

    # ✅ Language
    async def help_language_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            query = update.callback_query
            await query.answer()
            chat_id = query.message.chat.id

            text = (
                "<b>🌐 Language</b>\n\n"
                "Change the interface language of the bot.\n\n"
                "• Available in Persian, English, Arabic, and more\n"
                "• Choose your preferred language\n"
                "• The bot will remember your choice for future sessions\n\n"
                "Multilingual support ensures a smooth experience for everyone."
            )
            keyboard = [
                [InlineKeyboardButton("⬅️ Back", callback_data="help_details"),
                InlineKeyboardButton("➡️ Exit", callback_data="exit_help")]
            ]
            reply_markup = await self.inline_translator.build_inline_keyboard_for_user(keyboard, chat_id)
            msg_final = await self.translation_manager.translate_for_user(text, chat_id)
            await query.edit_message_text(msg_final, reply_markup=reply_markup, parse_mode="HTML")
        except Exception as e:
            await self.error_handler.handle(update, context, e, context_name="help_language_callback")


    # ✅ Help & Support
    async def help_support_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            query = update.callback_query
            await query.answer()
            chat_id = query.message.chat.id

            text = (
                "<b>🧭 Help & Support</b>\n\n"
                "Need help? We're here to assist you.\n\n"
                "• For questions about features, use this help section\n"
                "• For payment or technical issues, contact support\n"
                "• Use the 'Back' button below to return to the help menu\n\n"
                "Our team responds to issues as quickly as possible."
            )
            keyboard = [
                [InlineKeyboardButton("⬅️ Back", callback_data="help_details"),
                InlineKeyboardButton("➡️ Exit", callback_data="exit_help")]
            ]
            reply_markup = await self.inline_translator.build_inline_keyboard_for_user(keyboard, chat_id)
            msg_final = await self.translation_manager.translate_for_user(text, chat_id)
            await query.edit_message_text(msg_final, reply_markup=reply_markup, parse_mode="HTML")
        except Exception as e:
            await self.error_handler.handle(update, context, e, context_name="help_support_callback")






############################################################################################################

    # async def show_Guide(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    #     try:
            
            # # ───➤ ست‌کردن state برای این مرحله
            # push_state(context, "showing_guide")
            # # (اختیاری برای backward-compatibility)
            # context.user_data['state'] = "showing_guide"            
            
    #         chat_id = update.effective_chat.id

    #         help_text = (
    #             "👋 <b>Welcome to your Blockchain Assistant!</b>\n\n"
    #             "Here’s what each option in the menu does:\n\n"
    #             "• 📊 <b>Token Price</b>: View live price of our token\n"
    #             "• 💵 <b>Withdraw</b>: Request withdrawal of your balance\n"
    #             "• 💳 <b>Payment</b>: Pay membership fee or deposit funds\n"
    #             "• 💰 <b>Trade</b>: Buy or sell tokens with market prices\n"
    #             "• 🔄 <b>Convert Token</b>: Convert between token types\n"
    #             "• 🪙 <b>Earn Money</b>: Invite others and earn commission\n"
    #             "• 🧭 <b>Help & Support</b>: Get assistance and tutorials\n"
    #             "• 👤 <b>Profile</b>: View or update your wallet and info\n"
    #             "• 🌐 <b>Language</b>: Change the bot interface language\n\n"
    #             "Use the buttons below or go back to main menu."
    #         )

    #         translated_text = await self.translation_manager.translate_for_user(help_text, chat_id)

    #         await update.message.reply_text(
    #             translated_text,
    #             parse_mode="HTML",
    #             reply_markup=await self.keyboards.build_back_exit_keyboard(chat_id)
    #         )

    #     except Exception as e:
    #         await self.error_handler.handle(update, context, e, context_name="show_help")