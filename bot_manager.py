

# bot_manager.py


import os
import logging
from typing import Optional, Dict, Callable
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from telegram import Bot
from telegram.ext import Application
from telegram import Update, Bot, Update, ReplyKeyboardRemove, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application,
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    MessageHandler,
    filters,
    CallbackQueryHandler
)
from fastapi import FastAPI

from myproject_database import Database
from translation import SimpleTranslator
from language_Manager import TranslationManager
from error_handler import ErrorHandler
from keyboards import TranslatedKeyboards
from Translated_Inline_Keyboards import TranslatedInlineKeyboards
from HelpHandler import HelpHandler
from Referral_logic_code import ReferralManager
from Profile import ProfileHandler
from trade_handler import TradeHandler
from admin_handler import AdminHandler 
from price_provider import PriceProvider          # ← NEW
from trade_handler import TradeHandler            # ← NEW

from token_price_handler import TokenPriceHandler
from convert_token_handler import ConvertTokenHandler
from earn_money_handler import EarnMoneyHandler

from payment_handler import PaymentHandler
from support_handler import SupportHandler

from config import ADMIN_USER_IDS, SUPPORT_USER_USERNAME, PAYMENT_WALLET_ADDRESS

class BotManager:
    def __init__(self, app: FastAPI):
        self.app = app
        self.logger = self.setup_logger()

        # سیستم‌های پایه
        self.db: Optional[Database] = None
        
        self.translator: Optional[SimpleTranslator] = None
        self.keyboards: Optional[TranslatedKeyboards] = None
        self.translation_manager: Optional[TranslationManager] = None
        self.inline_translator: Optional[TranslatedInlineKeyboards] = None
        
        self.error_handler: Optional[ErrorHandler] = None    
            
        self.HelpHandler: Optional[HelpHandler] = None
        
        self.trade_handler: Optional[TradeHandler] = None
        
        self.referral_manager: Optional[ReferralManager] = None
        self.profile_handler: Optional[ProfileHandler] = None
        self.price_provider: Optional[PriceProvider] = None
        self.admin_handler: Optional[AdminHandler] = None
        
        self.convert_token_handler: Optional[ConvertTokenHandler] = None
        self.earn_money_handler: Optional[EarnMoneyHandler] = None
        self.token_price_handler: Optional[TokenPriceHandler] = None        
        
        self.support_handler: Optional[SupportHandler] = None
        self.payment_handler: Optional[PaymentHandler] = None          
        
        self.bot: Optional[Bot] = None
        self.application: Optional[Application] = None

        # وضعیت‌ها و مسیریابی‌ها
        self._state_router: Dict[str, Callable] = {}

    def setup_logger(self):
        logger = logging.getLogger("BotManager")
        logger.setLevel(logging.INFO)
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        ))
        logger.addHandler(handler)
        return logger

    async def initialize_modules(self):
        """
        مقداردهی اولیه‌ی ماژول‌هایی که تا این مرحله ساخته شده‌اند.
        """

        try:
            
            # باید قبل از TradeHandler ساخته شود
            self.price_provider = PriceProvider(self.db)     # ← NEW
            self.logger.info("PriceProvider initialized (manual mode).")
            
            # 1. SimpleTranslator (بدون وابستگی خاص)
            self.translator = SimpleTranslator(model_type="gpt-4o", db=self.db)
            self.logger.info("SimpleTranslator initialized successfully.")

            # 2. TranslationManager (وابسته به translator)
            self.translation_manager = TranslationManager(self.db, self.translator)
            self.logger.info("TranslationManager initialized successfully.")

            # 3. TranslatedKeyboards (سیستم دکمه‌ها با ترجمه خودکار)
            self.keyboards = TranslatedKeyboards(db=self.db, translator=self.translator)
            self.logger.info("TranslatedKeyboards initialized successfully.")

            # 4. TranslatedInlineKeyboards (وابسته به translator)
            self.inline_translator = TranslatedInlineKeyboards(db=self.db, translator=self.translator)
            self.logger.info("TranslatedInlineKeyboards initialized successfully.")

            # 9. HelpHandler (وابسته به error_handler و translation_manager)
            self.help_handler = HelpHandler(
                logger=self.logger,
                db=self.db,
                error_handler=self.error_handler,
                inline_translator=self.inline_translator,
                keyboards=self.keyboards,
                translation_manager=self.translation_manager
            )
            self.logger.info("HelpHandler initialized successfully.")

            # 5. ErrorHandler (وابسته به translation_manager و keyboards)
            self.error_handler = ErrorHandler(
                translation_manager=self.translation_manager,
                keyboards=self.keyboards
            )
            self.logger.info("ErrorHandler initialized successfully.")

            # 1️⃣ ReferralManager
            pool_wallet = os.getenv("POOL_WALLET_ADDRESS")
            self.referral_manager = ReferralManager(self.db, pool_wallet=pool_wallet)
            self.logger.info("ReferralManager initialized (pool_wallet=%s)", pool_wallet)

            # 2️⃣ ProfileHandler
            self.profile_handler = ProfileHandler(
                db=self.db,
                referral_manager=self.referral_manager,
                keyboards=self.keyboards,
                translation_manager=self.translation_manager,
                error_handler=self.error_handler,
            )
            self.logger.info( "ProfileHandler initialized with ReferralManager and dependencies")

            self.trade_handler = TradeHandler(
                keyboards=self.keyboards,
                translation_manager=self.translation_manager,
                db=self.db,
                price_provider=self.price_provider,  # باید متد async def get_price() داشته باشد
                referral_manager=self.referral_manager,
                error_handler=self.error_handler,
            )
            # لاگِ راه‌اندازی TradeHandler
            self.logger.info(
                "TradeHandler initialized (price_provider=%s, referral_manager=%s)",
                type(self.price_provider).__name__,
                type(self.referral_manager).__name__
            )

            #######################
            
            self.token_price_handler = TokenPriceHandler(
                price_provider=self.price_provider,
                keyboards=self.keyboards,
                translation_manager=self.translation_manager,
                error_handler=self.error_handler,
            )
            self.logger.info("TokenPriceHandler initialized.")

            self.convert_token_handler = ConvertTokenHandler(
                keyboards=self.keyboards,
                translation_manager=self.translation_manager,
            )
            self.logger.info("ConvertTokenHandler initialized.")

            self.earn_money_handler = EarnMoneyHandler(
                keyboards=self.keyboards,
                translation_manager=self.translation_manager,
            )
            self.logger.info("EarnMoneyHandler initialized.")
            
            #######################
            
            self.payment_handler = PaymentHandler(
                keyboards=self.keyboards,
                translation_manager=self.translation_manager,
                error_handler=self.error_handler,
            )
            self.logger.info("PaymentHandler initialized (wallet=%s)", PAYMENT_WALLET_ADDRESS)

            self.support_handler = SupportHandler(
                keyboards=self.keyboards,
                translation_manager=self.translation_manager,
                error_handler=self.error_handler,
            )
            self.logger.info("SupportHandler initialized (username=%s)", SUPPORT_USER_USERNAME)            
            
            self.admin_handler = AdminHandler(
                        price_provider=self.price_provider,
                        translation_manager=self.translation_manager
                    )            
            
            # # فرض: admin_ids را از env یا config خوانده‌اید
            # self.admin_handler = AdminHandler(
            #     price_provider=self.price_provider,
            #     translation_manager=self.translation_manager,
            #     admin_ids=ADMIN_USER_IDS  # یا هر لیست عددی
            # )
            # self.logger.info("AdminHandler initialized (admins=%s)", ADMIN_USER_IDS)


            self.logger.info("✅ Translation & Keyboard modules initialized.")

        except Exception as e:
            self.logger.error(f"❌ Failed to initialize translation modules: {e}", exc_info=True)

    # --------------------------------------------------------------------------------------------------
    async def handle_language_button(
        self,
        update : Update,
        context: ContextTypes.DEFAULT_TYPE
    ):
        """
        وقتی کاربر روی دکمهٔ «Change Language» می‌زند (CallbackQuery)
        یا مستقیم /language را تایپ می‌کند (MessageUpdate)،
        از او می‌خواهیم یک جمله به زبان مادری‌اش بفرستد.
        """
        try:
            # ---------- داده‌های عمومی ----------
            chat_id        = update.effective_chat.id
            user_firstname = update.effective_user.first_name

            # ---------- زبان فعلی کاربر ----------
            user_lang = await self.db.get_user_language(chat_id) or "en"

            # ---------- وضعیت انتظار برای ارسال جمله ----------
            context.user_data["state"] = "awaiting_language_detection"

            # ---------- چپ‌به‌راست / راست‌به‌چپ ----------
            rtl_langs   = {"fa", "ar", "he", "ur"}
            rlm         = "\u200F"
            display_name = (
                f"{rlm}{user_firstname}{rlm}"
                if user_lang.lower() in rtl_langs else user_firstname
            )

            # ---------- متن پیام ----------
            template = (
                "Hey <b>{name}</b>! 👋\n"
                "Just send me a sentence in your native language — "
                "so we can continue in your language from now on. 🌍"
            )
            if user_lang != "en":
                template = await self.translator.translate_text(template, user_lang)

            final_msg = template.format(name=display_name)

            # ---------- انتخاب Sender ----------
            if update.message:                                      # حالت MessageUpdate
                await update.message.reply_text(
                    final_msg,
                    parse_mode="HTML",
                    reply_markup=await self.keyboards.build_back_exit_keyboard(chat_id)
                )
            else:                                                   # حالت CallbackQueryUpdate
                # همان پیام قبلی Bot را ریپلای می‌کنیم
                await update.callback_query.message.reply_text(
                    final_msg,
                    parse_mode="HTML",
                    reply_markup=await self.keyboards.build_back_exit_keyboard(chat_id)
                )

        except Exception as e:
            await self.error_handler.handle(update, context, e, context_name="handle_language_button")
    
#############################################################################################################
    def is_valid_text(self, text: str) -> bool:
        """
        بررسی می‌کند که ورودی شامل محتوای متنی معنی‌دار از زبان‌های پشتیبانی‌شده باشد.
        
        شرایط:
        - طول متن پس از حذف فاصله‌های اضافی باید حداقل ۵ کاراکتر باشد.
        - حداقل یکی از کاراکترها باید حرف الفبایی (برای هر زبان) باشد.
        - نسبت کاراکترهای الفبایی به کل کاراکترها باید حداقل ۳۰ درصد باشد.
        """
        cleaned_text = text.strip()
        if len(cleaned_text) < 5:
            return False

        # استخراج کاراکترهای الفبایی از متن (isalpha، به صورت یونی‌کد کار می‌کند)
        alpha_chars = [c for c in cleaned_text if c.isalpha()]
        if not alpha_chars:
            return False

        # محاسبه نسبت کاراکترهای الفبایی نسبت به کل کاراکترها
        alpha_ratio = len(alpha_chars) / len(cleaned_text)
        if alpha_ratio < 0.3:
            return False

        return True
    
    #-----------------------------------------------------------------------------------------------------
    async def handle_language_detection(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            chat_id = update.effective_chat.id
            text = update.message.text.strip()

            # بررسی اولیه صحت متن با استفاده از is_valid_text
            if not self.is_valid_text(text):
                await update.message.reply_text(
                    "The text you sent does not appear to be a valid, meaningful sentence. Please send a complete and clear sentence."
                )
                context.user_data['state'] = 'awaiting_language_detection'
                return

            # گام ۱: زبان کاربر را از دیتابیس یا از context.user_data دریافت کنید
            user_lang = await self.db.get_user_language(chat_id)
            if not user_lang:
                user_lang = 'en' 
                
            original_text = await self.db.get_original_text_by_translation(text, user_lang)
            if original_text:
                text = original_text

            if text == "🗣 Language":
                await update.message.reply_text("Please send me a sentence in your native language so I can detect it.")
                return

            detected_lang = await self.translator.detect_language(text)
            if detected_lang == "invalid":
                await update.message.reply_text(
                    "The text you sent does not appear to be a valid, meaningful sentence. Please send a complete and clear sentence."
                )
                # حالت کاربر را دست نخورده می‌گذاریم یا به وضعیت انتظار تشخیص برمی‌گردانیم:
                context.user_data['state'] = 'awaiting_language_detection'
                return

            await self.db.update_user_language(chat_id, detected_lang)

            confirm_msg_en = f"Your language is set to '{detected_lang}'."
            await update.message.reply_text(confirm_msg_en)

            context.user_data['state'] = 'main_menu'
            await self.show_main_menu(update, context)

        except Exception as e:
            await self.error_handler.handle(update, context, e, context_name="handle_language_detection")
#------------------------------------------------------------------------------------------------------------
    
    ###########################################  start_command  ####################################################
    
    
    ###########################################  start_command  #########################################################
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        /start برای MessageUpdate یا CallbackQueryUpdate.  
        - بارِ اول: دکمهٔ Change/Skip زبان  
        - بعد از آن: منوی اصلی همراه پیام مناسب
        """
        try:
            chat_id    = update.effective_chat.id
            first_name = update.effective_user.first_name

            # ➊ مطمئن شو رکورد کاربر وجود دارد
            await self.db.insert_user_if_not_exists(chat_id, first_name)

            # ➋ اگر هنوز پرسش زبان نمایش داده نشده، فقط همان را بفرست
            if not await self.db.is_language_prompt_done(chat_id):
                keyboard = [[
                    InlineKeyboardButton("🌐 Change Language", callback_data="choose_language"),
                    InlineKeyboardButton("⏭️ Skip",           callback_data="skip_language"),
                ]]
                msg = (
                    "🛠️ <b>The default language of this bot is English.</b>\n\n"
                    "If you'd like to use the bot in another language, tap <b>🌐 Change Language</b>.\n"
                    "Otherwise, tap <b>⏭️ Skip</b> to continue in English.\n\n"
                    "You can always change later with /language."
                )
                markup = InlineKeyboardMarkup(keyboard)

                if update.message:
                    await update.message.reply_text(msg, parse_mode="HTML", reply_markup=markup)
                else:
                    await context.bot.send_message(chat_id, msg, parse_mode="HTML", reply_markup=markup)
                return

            # ➌ نمایش منوی اصلی
            context.user_data['state'] = 'main_menu'
            main_kb = await self.keyboards.build_main_menu_keyboard_v2(chat_id)

            tpl = (
                "Hello <b>{name}</b>!! Welcome to <b>Bot</b>. "
                "I'm here to assist you — just choose an option from the menu below to begin. 👇"
            )
            msg = (await self.translation_manager.translate_for_user(tpl, chat_id)).format(name=first_name)

            if update.message:
                await update.message.reply_text(msg, parse_mode="HTML", reply_markup=main_kb)
            else:
                await context.bot.send_message(chat_id, msg, parse_mode="HTML", reply_markup=main_kb)

        except Exception as e:
            await self.error_handler.handle(update, context, e, context_name="start_command")
    
    
    # async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    #     """
    #     /start برای MessageUpdate یا CallbackQueryUpdate.  
    #     - بارِ اول: دکمهٔ Change/Skip زبان  
    #     - بعد از آن: منوی اصلی همراه پیام مناسب
    #     """
    #     try:
    #         chat_id    = update.effective_chat.id
    #         first_name = update.effective_user.first_name

    #         # ➊ مطمئن شو رکورد کاربر وجود دارد
    #         await self.db.insert_user_if_not_exists(chat_id, first_name)

    #         # ➋ اگر هنوز پرسش زبان نمایش داده نشده، فقط همان را بفرست
    #         if not await self.db.is_language_prompt_done(chat_id):
    #             keyboard = [[
    #                 InlineKeyboardButton("🌐 Change Language", callback_data="choose_language"),
    #                 InlineKeyboardButton("⏭️ Skip",           callback_data="skip_language"),
    #             ]]
    #             msg = (
    #                 "🛠️ <b>The default language of this bot is English.</b>\n\n"
    #                 "If you'd like to use the bot in another language, tap <b>🌐 Change Language</b>.\n"
    #                 "Otherwise, tap <b>⏭️ Skip</b> to continue in English.\n\n"
    #                 "You can always change later with /language."
    #             )
    #             markup = InlineKeyboardMarkup(keyboard)

    #             if update.message:
    #                 await update.message.reply_text(msg, parse_mode="HTML", reply_markup=markup)
    #             else:
    #                 await context.bot.send_message(chat_id, msg, parse_mode="HTML", reply_markup=markup)
    #             return

    #         # ➌ در ادامه منطق معمول: بررسی اشتراک
    #         context.user_data['state'] = 'checking_subscription'
    #         subscribed = await self.subscription_db.is_user_subscribed_any_plan(chat_id)

    #         # --- کیبورد اصلی برای هر دو حالت ---
    #         main_kb = await self.keyboards.build_main_menu_keyboard(chat_id)

    #         if subscribed:
    #             context.user_data['state'] = 'main_menu'

    #             tpl = (
    #                 "Hello <b>{name}</b>!! Welcome to <b>Bot</b>. "
    #                 "I'm here to assist you — just choose an option from the menu below to begin. 👇"
    #             )
    #             msg = (await self.translation_manager.translate_for_user(tpl, chat_id)).format(name=first_name)

    #             if update.message:
    #                 await update.message.reply_text(msg, parse_mode="HTML", reply_markup=main_kb)
    #             else:
    #                 await context.bot.send_message(chat_id, msg, parse_mode="HTML", reply_markup=main_kb)

    #         else:
    #             context.user_data['state'] = 'awaiting_access_request'

    #             tpl = (
    #                 "🚀 <b>Welcome {name} to your bot"
    #             )
    #             msg = (await self.translation_manager.translate_for_user(tpl, chat_id)).format(name=first_name)

    #             if update.message:
    #                 await update.message.reply_text(msg, parse_mode="HTML", reply_markup=main_kb)
    #             else:
    #                 await context.bot.send_message(chat_id, msg, parse_mode="HTML", reply_markup=main_kb)

    #     except Exception as e:
    #         await self.error_handler.handle(update, context, e, context_name="start_command")
    
    
    ####################################  language_choice_callback  ####################################################
    async def language_choice_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Handles presses on “Change Language” and “Skip”.
        """
        query = update.callback_query
        await query.answer()

        chat_id    = query.message.chat_id
        first_name = query.from_user.first_name
        data       = query.data

        # --- گزینهٔ «Change Language» ---
        if data == "choose_language":
            
            await self.handle_language_button(update, context)   # همان فلو قدیمی تشخیص زبان
            
            await self.db.mark_language_prompt_done(chat_id)     # بعد از انتخاب، فلگ را True کن
            
            return

        # --- گزینهٔ «Skip» ---
        if data == "skip_language":
            # ➊ مطمئن شو رکورد هست (اگر کاربر بسیار تازه باشد)
            await self.db.insert_user_if_not_exists(chat_id, first_name)

            # ➋ زبان را 'en' نگه دار
            await self.db.update_user_language(chat_id, "en")

            # ➌ فلگ «پرسش زبان» را یک‌بار برای همیشه ببند
            await self.db.mark_language_prompt_done(chat_id)
            self.logger.info(f"{first_name} skipped language selection → set to 'en'.")

            # ➍ پیام دکمه‌ها را پاک کن
            await query.message.delete()

            # ➎ ادامهٔ فلو عادی (/start) با همین Update دوباره
            await self.start_command(update, context)
            
#######################################################################################################         
    async def setup_telegram_handlers(self):
        """Setup and add Telegram handlers to the application."""
        try:
            if not self.application:
                self.logger.error("Telegram application is not initialized.")
                return

            # 1️⃣ Command Handlers
            self.application.add_handler(CommandHandler('start', self.start_command), group=0)
            self.application.add_handler(CommandHandler('guide', self.help_handler.show_Guide), group=0)
            self.application.add_handler(CommandHandler('language', self.handle_language_button), group=0)
            self.application.add_handler(CommandHandler("set_price", self.admin_handler.set_price_cmd), group=0)

            # پیام /profile یا دکمه 👤
            self.application.add_handler(CommandHandler('profile', self.profile_handler.show_profile), group=0)

            # درون متد setup_telegram_handlers، در بخشی که سایر CallbackQueryHandler ها را اضافه کرده‌اید:
            self.application.add_handler(
                CallbackQueryHandler(
                    self.language_choice_callback,
                    pattern=r"^(choose_language|skip_language)$"
                ),
                group=0
            )

            # صفحه‌بندی (pattern = profile_page_⟨n⟩)
            self.application.add_handler(CallbackQueryHandler(
                self.profile_handler.show_profile,
                pattern=r'^profile_page_\\d+$'
            ), group=0)

            self.application.add_handler(
                CommandHandler("set_price", self.admin_handler.set_price_cmd),
                group=0
            )

            # … سایر هندلرها
            self.application.add_handler(
                self.trade_handler.get_conversation_handler(),
                group=1   # یا هر گروهی که منطقی است
            )


            # 3️⃣ Message Handler for private text
            private_text_filter = filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND
            self.application.add_handler(
                MessageHandler(private_text_filter, self.handle_private_message),
                group=1
            )

            # 4️⃣ Global error handler
            self.application.add_error_handler(
                lambda update, context: self.error_handler.handle(
                    update, context, context.error, context_name="setup_telegram_handlers"
                )
            )

            self.logger.info("Telegram handlers setup completed.")
        except Exception as e:
            self.logger.error(f"Failed to setup telegram handlers: {e}")
            raise
#########################################################################################################

    async def handle_private_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Route private text messages based on user input and current state, building keyboards."""
        try:
            chat_id = update.effective_chat.id
            text = (update.message.text or "").strip()
            text_lower = text.lower()
            self.logger.info(f"Received private text from {chat_id}: '{text}'")

            # Retrieve and restore language & history
            user_lang = await self.db.get_user_language(chat_id) or 'en'
            original = await self.db.get_original_text_by_translation(text, user_lang)
            if original:
                text_lower = original.lower()

            current_state = context.user_data.get('state', 'main_menu')

            # # ─── Global Exit ─────────────────────────
            # if text_lower in {'exit', '➡️ exit'}:
            #     context.user_data.clear()
            #     msg = await self.translation_manager.translate_for_user("Goodbye!", chat_id)
            #     return await update.message.reply_text(msg)

            # ─── Global Exit ─────────────────────────
            if text_lower in {'exit', '➡️ exit'}:
               # Delegate to the exit_bot handler (clears state, builds and sends farewell)
                return await self.exit_bot(update, context)
            
            # ─── Global Back ─────────────────────────
            if text_lower in {'back', '⬅️ back'}:
                # revert to main menu
                context.user_data['state'] = 'main_menu'
                kb = await self.keyboards.build_main_menu_keyboard_v2(chat_id)
                msg = await self.translation_manager.translate_for_user(
                    "Main menu:", chat_id
                )
                return await update.message.reply_text(msg, reply_markup=kb)

            if text_lower == '🚀 start':
                context.user_data['state'] = 'starting'
                await self.start_command(update, context)

            elif text_lower == '📘 guide':
                await self.help_handler.show_Guide(update, context)
                
            # دکمه جدید: Chain-of-Thought (CoT)
            elif text_lower == '💰 trade':
                await self.trade_handler.trade_menu(update, context)
                
            elif text_lower == '💳 payment':
                await self.payment_handler.show_payment_instructions(update, context)

            elif text_lower == '🎧 support':
                await self.support_handler.show_support_info(update, context)

            elif text_lower == '🌐 language':   
                await self.handle_language_button(update, context)   
                
            elif text_lower == '👤 profile':   
                await self.profile_handler.show_profile(update, context)   
                
            elif text_lower == '📊 token price':
                await self.token_price_handler.show_price(update, context)

            elif text_lower == '🔄 convert token':
                await self.convert_token_handler.coming_soon(update, context)

            elif text_lower == '💼 earn money':
                await self.earn_money_handler.coming_soon(update, context)


                #--------------------------------------------------------------------------------
            else:
                msg_en = "You're in the <b>main menu</b> now! I'm here to assist you — just <b>pick an option</b> below to begin. 👇"
                msg_final = await self.translation_manager.translate_for_user(msg_en, chat_id)
                                             
                await update.message.reply_text(
                    msg_final,
                    reply_markup=await self.keyboards.build_main_menu_keyboard_v2(chat_id), parse_mode="HTML")
                self.logger.warning(f"User {chat_id} sent an unexpected message: {text} in state: {current_state}")
        except Exception as e:
            await self.error_handler.handle(update, context, e, context_name="handle_private_message")            
            
    async def exit_bot(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Handle the 'Exit' button: clear state and send a farewell message.
        """
        try:
            chat_id = update.effective_chat.id
            first_name = update.effective_user.first_name

            # پاک‌کردن همه‌ی داده‌های جلسۀ کاربر
            context.user_data.clear()
            self.logger.info(f"User {chat_id} exited the bot.")

            # تعیین زبان و چیدمان نام برای RTL
            user_lang = await self.db.get_user_language(chat_id)
            rtl = {"fa","ar","he","ur"}
            if user_lang.lower() in rtl:
                rlm = "\u200F"
                display_name = f"{rlm}{first_name}{rlm}"
            else:
                display_name = first_name

            # پیام خداحافظی
            template = (
                "👋 Goodbye, <b>{name}</b>!\n\n"
                "Thank you for using <b>AskGenieAI</b>. "
                "Feel free to come back anytime. 😊"
            )
            # ترجمهٔ قالب به زبان کاربر
            translated = await self.translation_manager.translate_for_user(template, chat_id)
            # جایگذاری نام
            text = translated.format(name=display_name)

            # ارسال پیام با منوی اصلی (دکمه‌های Back و Exit مجدداً ظاهر می‌شوند)
            await update.message.reply_text(
                text,
                parse_mode="HTML",
                reply_markup=await self.keyboards.build_main_menu_keyboard_v2(chat_id)
            )

        except Exception as e:
            await self.error_handler.handle(update, context, e, context_name="exit_bot")
            
########################################### show_main_menu ##########################################################
    async def show_main_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show the main menu to the user."""
        try:
            chat_id = update.effective_chat.id      
            context.user_data['state'] = 'main_menu'
                     
            msg_en = "You're in the <b>Main Menu</b> now! I'm here to assist you — just pick an <b>option</b> below to begin. 👇"
            msg_final = await self.translation_manager.translate_for_user(msg_en, chat_id)     
            await update.message.reply_text(
                msg_final,
                reply_markup=await self.keyboards.build_main_menu_keyboard_v2(chat_id),
                parse_mode="HTML"
            )
            self.logger.info(f"User {chat_id} is returning to the main menu.")
        except Exception as e:
            await self.error_handler.handle(update, context, e, context_name="show_main_menu")          
            
           
############################################## fastapi #########################################################
    async def startup(self):
        """
        راه‌اندازی نهایی بات و انجام تنظیمات مورد نیاز
        """
        try:
            # 1) ساخت Application تلگرام
            self.application = ApplicationBuilder().token(os.getenv('TELEGRAM_BOT_TOKEN')).build()
            self.bot = self.application.bot
            
            # 2) مقداردهی و استارت بات
            await self.application.initialize()
            await self.application.start()
            self.logger.info("Telegram application started successfully.")
            
            #-------------------------------------------------------------------------------
            # 3) مقداردهی دیتابیس عمومی
            self.db = Database()
            await self.db.initialize_all_connections()
            self.logger.info("Main Database initialized successfully.")
            
            # (در صورت نیاز) قرار دادن در bot_data:
            self.application.bot_data['db'] = self.db
        
            #---------------------------------------------------------------------------       
            await self.initialize_modules()
            self.logger.info("All modules initialized successfully.")    
            #-------------------------------------------------------------------------------
            # 6) ثبت سایر هندلرهای تلگرام (دستور /start، /help و ...)
            await self.setup_telegram_handlers()
            self.logger.info("Telegram handlers added successfully.")

            # 7) در نهایت تنظیم وبهوک
            await self.set_webhook()
            self.logger.info("Webhook set successfully.")

            # 8) علامت‌گذاری وضعیت running
            self.is_running = True
            self.logger.info("BotManager startup completed successfully.")

        except Exception as e:
            self.logger.error(f"Failed during BotManager startup: {e}", exc_info=True)
            raise

#---------------------------------------------------------------------------------------------------------
    async def shutdown(self):
        """پاکسازی منابع هنگام shutdown."""
        try:
            # توقف برنامه تلگرام
            if self.application:
                self.logger.info("Shutting down Telegram application...")
                await self.application.stop()
                await self.application.shutdown()
                self.logger.info("Telegram application stopped successfully.")

            # بستن اتصال به دیتابیس
            if self.db:
                self.logger.info("Closing database connection...")
                await self.db.close()
                self.logger.info("Database connection closed.")

            # به‌روزرسانی وضعیت برنامه
            self.is_running = False
            self.logger.info("BotManager shutdown completed successfully.")

        except Exception as e:
            self.logger.error(f"Error during shutdown: {e}", exc_info=True)
            raise
        
    #---------------------------------------------------------------------------------------------------------        
    async def process_update(self, update: Update):
            """Process incoming update from Telegram."""
            try:
                if not self.application:
                    raise ValueError("Telegram application is not initialized.")

                # Handle the update
                await self.application.process_update(update)
            except Exception as e:
                logging.error(f"Error processing update: {e}", exc_info=True)
                raise
            
    #---------------------------------------------------------------------------------------------------------
    async def set_webhook(self):
        """تنظیم وبهوک تلگرام."""
        try:
            webhook_url = os.environ.get('WEBHOOK_URL')
            if not webhook_url:
                raise ValueError("WEBHOOK_URL environment variable is not set.")

            if not self.application or not self.application.bot:
                raise ValueError("Telegram application or bot is not initialized.")

            await self.application.bot.set_webhook(url=webhook_url)
            self.logger.info(f"Webhook set to {webhook_url}")
        except Exception as e:
            self.logger.error(f"Failed to set webhook: {e}", exc_info=True)
            raise

#---------------------------------------------------------------------------------------------------------
    async def cleanup(self):
        """پاکسازی منابع."""
        try:
            # توقف و آزادسازی منابع برنامه تلگرام
            if self.application:
                await self.application.shutdown()
                await self.application.stop()
                self.logger.info("Telegram application shutdown successfully.")

            # بستن اتصال به دیتابیس عمومی
            if self.db:
                await self.db.close()
                self.logger.info("Database connection closed.")

        except Exception as e:
            self.logger.error(f"Error during cleanup: {e}", exc_info=True)
            raise
              