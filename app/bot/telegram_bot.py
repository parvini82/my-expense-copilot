import html
import logging
from typing import Optional
from telegram import Update
from telegram.constants import ChatAction, ParseMode
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from app.agent.audio import transcribe_voice_bytes
from app.agent.budget import check_and_send_budget_alert
from app.agent.llm_parser import extract_amount_from_notification, parse_expense_with_llm
from app.agent.qa_agent import ask_expenses_agent, fetch_expenses_dataframe
from app.agent.reporting import generate_monthly_expense_chart
from app.config import get_settings
from app.database.google_sheets import google_sheets_db
from app.database.mock_db import mock_db
from app.state import PendingTransaction, state_manager

logger = logging.getLogger("expense_agent.bot")

# Global reference to initialized Telegram application
_bot_application: Optional[Application] = None


def is_authorized(chat_id: int) -> bool:
    """Verify if the incoming chat ID is in the ALLOWED_CHAT_IDS list."""
    settings = get_settings()
    if not settings.ALLOWED_CHAT_IDS:
        logger.warning("ALLOWED_CHAT_IDS is not configured. Rejecting all requests.")
        return False
    return chat_id in settings.ALLOWED_CHAT_IDS


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command."""
    if not update.effective_chat or not is_authorized(update.effective_chat.id):
        if update.effective_message:
            await update.effective_message.reply_text(
                "⛔ *Access Denied*: You are not authorized to use this bot.",
                parse_mode=ParseMode.MARKDOWN,
            )
        return

    welcome_text = (
        "👋 *Welcome to your AI Expense Tracker!*\n\n"
        "I automatically listen for bank notifications and help you log, analyze, and visualize your expenses.\n\n"
        "✨ *How it works:*\n"
        "1. When your bank sends a notification, I'll alert you with the detected amount.\n"
        "2. Simply reply to my alert with a *text message* or *voice note* explaining the purchase.\n"
        "3. I'll use AI to categorize and record it in your Google Sheets database!\n\n"
        "🛠 *Commands:*\n"
        "• `/ask [question]` - Ask any question about your expenses (e.g. `/ask چقدر این ماه خرج کافه کردم؟`)\n"
        "• `/report [YYYY-MM]` - Generate visual pie chart & expense breakdown\n"
        "• `/budget` - View category budget limits and status\n"
        "• `/expenses` - View recently saved expenses\n"
        "• `/pending` - View any active pending transaction\n"
        "• `/cancel` - Cancel active pending transaction\n"
        "• `/help` - Display this help guide"
    )
    await update.effective_message.reply_text(welcome_text, parse_mode=ParseMode.MARKDOWN)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /help command."""
    if not update.effective_chat or not is_authorized(update.effective_chat.id):
        return

    help_text = (
        "💡 *Expense Agent Commands & Features*\n\n"
        "• *Replying to Alerts*: When asked about a transaction, send text or a voice note.\n"
        "• *Manual Expense Logging*: You can also log directly, e.g. `25000 تومان برای ناهار`.\n"
        "• `/ask [query]`: Ask smart natural language questions (e.g. `/ask Highest expense this month?`).\n"
        "• `/report [month]`: Generate a pie chart diagram (e.g. `/report` or `/report 2026-08`).\n"
        "• `/budget`: View monthly category limits and spending progress.\n"
        "• `/expenses`: List your 5 most recent logged expenses.\n"
        "• `/pending`: Check if there is a pending transaction waiting for your response.\n"
        "• `/cancel`: Clear any active pending transaction."
    )
    await update.effective_message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)


async def ask_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /ask command to run Pandas DataFrame AI Agent over expense records."""
    chat_id = update.effective_chat.id
    if not is_authorized(chat_id):
        return

    # Extract query
    query = " ".join(context.args).strip() if context.args else ""
    if not query:
        # Check if full text after /ask
        full_text = update.effective_message.text or ""
        if len(full_text.split(maxsplit=1)) > 1:
            query = full_text.split(maxsplit=1)[1].strip()

    if not query:
        await update.effective_message.reply_text(
            "❓ لطفاً سوال خود را بعد از دستور وارد کنید.\nمثال: `/ask چقدر این ماه خرج غذا کردم؟`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    status_msg = await update.effective_message.reply_text("🤖 _در حال تحلیل داده‌های مالی..._", parse_mode=ParseMode.MARKDOWN)

    try:
        answer = await ask_expenses_agent(query)
        await status_msg.edit_text(answer, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logger.error("QA agent command failed: %s", e, exc_info=True)
        await status_msg.edit_text(f"⚠️ خطا در پردازش پاسخ: `{str(e)}`")


async def report_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /report command to generate visual pie chart and statistical summary."""
    chat_id = update.effective_chat.id
    if not is_authorized(chat_id):
        return

    # Optional month parameter (e.g., /report 2026-08)
    target_month = context.args[0].strip() if context.args else None

    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_PHOTO)
    status_msg = await update.effective_message.reply_text("📊 _در حال ساخت نمودار مخارج..._", parse_mode=ParseMode.MARKDOWN)

    try:
        photo_buf, caption = await generate_monthly_expense_chart(month=target_month)

        if photo_buf is not None:
            await update.effective_message.reply_photo(
                photo=photo_buf,
                caption=caption,
                parse_mode=ParseMode.MARKDOWN,
            )
            await status_msg.delete()
        else:
            await status_msg.edit_text(caption, parse_mode=ParseMode.MARKDOWN)

    except Exception as e:
        logger.error("Report generation command failed: %s", e, exc_info=True)
        await status_msg.edit_text(f"⚠️ خطا در ساخت گزارش: `{str(e)}`")


async def budget_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /budget command to inspect current category budgets and monthly spending."""
    chat_id = update.effective_chat.id
    if not is_authorized(chat_id):
        return

    settings = get_settings()
    budgets = settings.CATEGORY_BUDGETS or {}

    if not budgets:
        await update.effective_message.reply_text("ℹ️ سقف بودجه‌ای در تنظیمات پیکربندی نشده است.")
        return

    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    try:
        df = await fetch_expenses_dataframe()
        current_month = datetime.date.today().strftime("%Y-%m")
        currency = settings.DEFAULT_CURRENCY or "Toman"

        lines = [f"🎯 *وضعیت بودجه ماه جاری ({current_month}):*\n"]

        month_df = df[df["Date"].astype(str).str.startswith(current_month)] if not df.empty else df

        for cat, limit in budgets.items():
            spent = 0.0
            if not month_df.empty:
                cat_df = month_df[month_df["Category"].str.lower() == cat.lower()]
                spent = float(cat_df["Amount"].sum())

            pct = (spent / limit) * 100 if limit > 0 else 0
            status_icon = "🟢" if pct < 80 else ("🟡" if pct <= 100 else "🔴")

            lines.append(
                f"{status_icon} *{cat}:*\n"
                f"   مخارج: `{spent:,.0f}` / سقف: `{limit:,.0f}` {currency} (*{pct:.1f}%*)"
            )

        await update.effective_message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)

    except Exception as e:
        logger.error("Budget command failed: %s", e, exc_info=True)
        await update.effective_message.reply_text(f"⚠️ خطا در محاسبه وضعیت بودجه: `{str(e)}`")


async def pending_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /pending command to display active pending transaction."""
    chat_id = update.effective_chat.id
    if not is_authorized(chat_id):
        return

    pending = await state_manager.get_pending(chat_id)
    if not pending:
        await update.effective_message.reply_text("✅ No pending transactions waiting for explanation.")
        return

    msg = (
        "⏳ *Pending Transaction Waiting for Input:*\n\n"
        f"💰 *Amount:* `${pending.amount:.2f}`\n"
        f"📱 *Source:* `{html.escape(pending.app_name)}`\n"
        f"📝 *Notification:* `{html.escape(pending.raw_text)}`\n\n"
        "👉 *Reply directly with text or a voice note to categorize it!*"
    )
    await update.effective_message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /cancel command to dismiss pending transaction."""
    chat_id = update.effective_chat.id
    if not is_authorized(chat_id):
        return

    removed = await state_manager.clear_pending(chat_id)
    if removed:
        await update.effective_message.reply_text("🚫 Pending transaction cancelled.")
    else:
        await update.effective_message.reply_text("ℹ️ No active pending transaction to cancel.")


async def expenses_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /expenses command to list recent expenses from Google Sheets or mock DB."""
    chat_id = update.effective_chat.id
    if not is_authorized(chat_id):
        return

    recent = []
    source = "Local DB"
    if google_sheets_db.is_configured():
        try:
            recent = await google_sheets_db.get_recent_expenses(limit=5)
            source = "Google Sheets"
        except Exception as e:
            logger.warning("Could not fetch from Google Sheets, falling back to local DB: %s", e)
            recent = await mock_db.get_recent_expenses(limit=5)
    else:
        recent = await mock_db.get_recent_expenses(limit=5)

    if not recent:
        await update.effective_message.reply_text(f"📂 No expenses recorded yet in {source}.")
        return

    lines = [f"📊 *Recent Expenses ({source}):*\n"]
    for i, exp in enumerate(reversed(recent), 1):
        # Support both Google Sheets column names (Date, Amount, Category...) and dict keys
        amt = exp.get("Amount", exp.get("amount", 0))
        cat = exp.get("Category", exp.get("category", "Other"))
        desc = exp.get("Description", exp.get("description", ""))
        date_str = exp.get("Date", exp.get("date", ""))
        curr = exp.get("Currency", exp.get("currency", "Toman"))
        bank_name = exp.get("Bank", exp.get("bank", "Bank"))

        try:
            amt_num = float(amt)
            amt_formatted = f"{amt_num:,.2f}"
        except (ValueError, TypeError):
            amt_formatted = str(amt)

        lines.append(
            f"{i}. *{amt_formatted} {html.escape(str(curr))}* — *{html.escape(str(cat))}*\n"
            f"   _{html.escape(str(desc))}_ ({html.escape(str(date_str))}) [{html.escape(str(bank_name))}]"
        )

    await update.effective_message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


async def process_user_expense_input(
    chat_id: int,
    user_text: str,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Core logic to process user's expense text (from typed text or transcribed voice)."""
    logger.info("[TELEGRAM PIPELINE] Processing user input from chat_id=%d: '%s'", chat_id, user_text)

    # Check if there is a pending transaction from a bank alert
    pending: Optional[PendingTransaction] = await state_manager.get_pending(chat_id)
    bank_name = "Manual Telegram"

    if pending:
        amount = pending.amount
        raw_ctx = pending.raw_text
        bank_name = pending.app_name or "Bank"
        logger.info(
            "[TELEGRAM PIPELINE] Found pending transaction (ID: %s, Amount: %s, Source: %s)",
            pending.id,
            pending.amount,
            pending.app_name,
        )
        # Pop pending transaction from state
        await state_manager.pop_pending(chat_id)

        # If pending amount was 0.0, attempt to extract from user text
        if amount <= 0:
            extracted_user_amount = extract_amount_from_notification(user_text)
            if extracted_user_amount and extracted_user_amount > 0:
                amount = extracted_user_amount
                logger.info("[TELEGRAM PIPELINE] Extracted amount from user explanation: %s", amount)
    else:
        # Check if user provided manual expense with amount in text
        extracted = extract_amount_from_notification(user_text)
        if extracted and extracted > 0:
            amount = extracted
            raw_ctx = "Manual Telegram Entry"
            logger.info("[TELEGRAM PIPELINE] No pending transaction, but extracted amount %s from manual text.", amount)
        else:
            logger.info("[TELEGRAM PIPELINE] No pending transaction and no amount found in text: '%s'", user_text)
            await update.effective_message.reply_text(
                "ℹ️ No pending bank transaction found, and no amount was detected in your message.\n\n"
                "To log manually, include the amount (e.g. `25000 تومان برای ناهار` or `$18 for lunch`).",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

    # Indicate typing state
    if update.effective_chat:
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    # Call AI categorization via OpenRouter LangChain agent
    try:
        logger.info(
            "[TELEGRAM PIPELINE] Step 1: Calling LLM parser (amount=%s, user_text='%s', raw_ctx='%s')...",
            amount,
            user_text,
            raw_ctx,
        )
        record = await parse_expense_with_llm(
            amount=amount,
            user_explanation=user_text,
            raw_notification=raw_ctx,
        )
        # Attach bank metadata
        record.bank = bank_name
        logger.info("[TELEGRAM PIPELINE] Step 1 Complete: LLM returned ExpenseRecord: %s", record)

        storage_destination = "Local DB"
        # Save to Google Sheets if configured
        if google_sheets_db.is_configured():
            try:
                logger.info("[TELEGRAM PIPELINE] Step 2: Appending expense to Google Sheets...")
                saved_sheets = await google_sheets_db.append_expense(
                    record,
                    bank=bank_name,
                    currency=record.currency,
                )
                storage_destination = "📊 Google Sheets"
                logger.info("[TELEGRAM PIPELINE] Step 2 Complete: Google Sheets append returned: %s", saved_sheets)
            except Exception as e:
                logger.error("[TELEGRAM PIPELINE] Google Sheets append failed: %s. Falling back to local DB.", e, exc_info=True)
                storage_destination = "⚠️ Local DB (Google Sheets Error)"
                await mock_db.save_expense(record)
        else:
            logger.info("[TELEGRAM PIPELINE] Step 2: Google Sheets not configured. Saving to local mock_db...")
            await mock_db.save_expense(record)
            storage_destination = "📂 Local DB"

        # Also always write a backup to mock_db for redundancy
        try:
            await mock_db.save_expense(record)
        except Exception:
            pass

        # Format pleasant receipt confirmation with sub-category and refund indicator
        refund_indicator = " 🔄 *(Refund / Dong)*" if record.is_refund else ""
        sub_cat_display = f" › `{html.escape(record.sub_category)}`" if record.sub_category else ""

        receipt_msg = (
            f"✅ *Expense Logged Successfully!*{refund_indicator}\n\n"
            f"💵 *Amount:* `{record.amount:,.2f}` *{html.escape(record.currency or 'Toman')}*\n"
            f"🏷 *Category:* `{html.escape(record.category)}`{sub_cat_display}\n"
            f"📝 *Description:* {html.escape(record.description)}\n"
            f"🏦 *Bank:* `{html.escape(bank_name)}`\n"
            f"📅 *Date:* `{record.date}`\n"
            f"💾 *Saved to:* {storage_destination}"
        )
        await update.effective_message.reply_text(receipt_msg, parse_mode=ParseMode.MARKDOWN)

        # Step 3: Check monthly budget alerts asynchronously
        try:
            await check_and_send_budget_alert(
                category=record.category,
                new_expense_amount=record.amount,
                bot=context.bot,
                chat_id=chat_id,
                currency=record.currency or "Toman",
            )
        except Exception as e:
            logger.warning("Budget alert check error: %s", e)

    except Exception as e:
        logger.error("[TELEGRAM PIPELINE] ❌ Error in expense pipeline: %s", e, exc_info=True)
        await update.effective_message.reply_text(
            f"⚠️ An error occurred while saving your expense: `{str(e)}`",
            parse_mode=ParseMode.MARKDOWN,
        )


async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle incoming text messages from Telegram."""
    if not update.effective_chat or not is_authorized(update.effective_chat.id):
        return

    user_text = update.effective_message.text.strip() if update.effective_message else ""
    if not user_text:
        return

    await process_user_expense_input(
        chat_id=update.effective_chat.id,
        user_text=user_text,
        update=update,
        context=context,
    )


async def handle_voice_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle incoming voice notes from Telegram using Whisper."""
    if not update.effective_chat or not is_authorized(update.effective_chat.id):
        return

    voice = update.effective_message.voice if update.effective_message else None
    if not voice:
        return

    chat_id = update.effective_chat.id

    # Send typing/recording feedback
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.RECORD_VOICE)

    try:
        status_msg = await update.effective_message.reply_text("🎙️ _Transcribing voice note..._", parse_mode=ParseMode.MARKDOWN)

        # Download voice file directly to memory buffer
        voice_file = await voice.get_file()
        voice_bytes = await voice_file.download_as_bytearray()

        # Transcribe with Whisper API
        transcribed_text = await transcribe_voice_bytes(bytes(voice_bytes), filename="voice.oga")

        # Edit status message to show transcription
        await status_msg.edit_text(
            f"🎙️ *Transcribed:* \"{html.escape(transcribed_text)}\"",
            parse_mode=ParseMode.MARKDOWN,
        )

        # Process transcribed explanation
        await process_user_expense_input(
            chat_id=chat_id,
            user_text=transcribed_text,
            update=update,
            context=context,
        )

    except Exception as e:
        logger.error("Voice message handling failed: %s", e, exc_info=True)
        await update.effective_message.reply_text(
            f"❌ Failed to process voice note: `{str(e)}`",
            parse_mode=ParseMode.MARKDOWN,
        )


async def send_transaction_alert(amount: float, raw_text: str, app_name: str) -> None:
    """Send alert to all allowed Telegram users regarding a newly detected transaction.

    Called by the FastAPI webhook endpoint.
    """
    settings = get_settings()
    global _bot_application

    if not _bot_application or not _bot_application.bot:
        logger.error("Telegram bot application is not initialized. Cannot send alert.")
        return

    if not settings.ALLOWED_CHAT_IDS:
        logger.error("ALLOWED_CHAT_IDS is empty or not configured. Cannot send alert.")
        return

    formatted_text = (
        "🔔 *New Transaction Detected!*\n\n"
        f"💰 *Amount:* `${amount:.2f}`\n"
        f"📱 *Source:* `{html.escape(app_name)}`\n"
        f"📝 *Details:* `{html.escape(raw_text)}`\n\n"
        "👉 *What was this for?* (Reply with a text message or voice note)"
    )

    for target_chat_id in settings.ALLOWED_CHAT_IDS:
        # Store in state manager for each chat ID
        pending = PendingTransaction(
            amount=amount,
            raw_text=raw_text,
            app_name=app_name,
            chat_id=target_chat_id,
        )
        await state_manager.set_pending(target_chat_id, pending)

        try:
            await _bot_application.bot.send_message(
                chat_id=target_chat_id,
                text=formatted_text,
                parse_mode=ParseMode.MARKDOWN,
            )
            logger.info(
                "Transaction alert sent to Telegram chat %d for amount $%.2f",
                target_chat_id,
                amount,
            )
        except Exception as e:
            logger.error("Failed to send Telegram transaction alert to chat %d: %s", target_chat_id, e, exc_info=True)


def create_bot_application() -> Application:
    """Build and configure the Telegram bot application instance."""
    global _bot_application
    settings = get_settings()

    if not settings.TELEGRAM_BOT_TOKEN:
        logger.warning("TELEGRAM_BOT_TOKEN is empty. Telegram bot will not start.")

    app = ApplicationBuilder().token(settings.TELEGRAM_BOT_TOKEN or "dummy_token").build()

    # Register command handlers
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("ask", ask_command))
    app.add_handler(CommandHandler("report", report_command))
    app.add_handler(CommandHandler("budget", budget_command))
    app.add_handler(CommandHandler("pending", pending_command))
    app.add_handler(CommandHandler("cancel", cancel_command))
    app.add_handler(CommandHandler("expenses", expenses_command))
    app.add_handler(CommandHandler("status", help_command))

    # Register message handlers
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice_message))

    _bot_application = app
    return app


def get_bot_application() -> Optional[Application]:
    """Retrieve global reference to initialized Telegram bot application."""
    return _bot_application
