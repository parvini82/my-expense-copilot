import asyncio
from contextlib import asynccontextmanager
import logging
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, Header, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
import uvicorn

from app.agent.llm_parser import extract_amount_from_notification
from app.bot.telegram_bot import (
    create_bot_application,
    get_bot_application,
    send_transaction_alert,
)
from app.config import get_settings
from app.database.google_sheets import google_sheets_db
from app.database.mock_db import mock_db
from app.state import state_manager

# Configure logging format
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s : %(message)s",
)
logger = logging.getLogger("expense_agent.main")


class MobileNotificationPayload(BaseModel):
    """Payload sent by mobile automation / bank notification webhook."""

    text: str = Field(
        ...,
        description="Raw notification text from bank or payment app",
        examples=["You made a purchase of $42.50 at WHOLE FOODS with card 1234."],
    )
    app_name: str = Field(
        default="Bank Notification",
        description="Name of the notification app source",
        examples=["Chase Mobile", "Revolut", "Apple Pay"],
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application startup and shutdown lifecycle, including the Telegram bot."""
    settings = get_settings()
    settings.validate_runtime_keys()

    bot_task = None
    bot_app = None

    if settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_BOT_TOKEN != "your_telegram_bot_token_here":
        try:
            logger.info("Initializing Telegram Bot...")
            bot_app = create_bot_application()
            await bot_app.initialize()
            await bot_app.start()
            if bot_app.updater:
                await bot_app.updater.start_polling(drop_pending_updates=True)
            logger.info("Telegram Bot is active and polling for updates.")
        except Exception as e:
            logger.error("Failed to start Telegram Bot polling: %s", e, exc_info=True)
    else:
        logger.warning(
            "TELEGRAM_BOT_TOKEN not configured or using placeholder. Bot polling is disabled."
        )

    logger.info("🚀 Expense Tracking Agent Service started on %s:%d", settings.HOST, settings.PORT)

    yield

    # Graceful shutdown
    logger.info("Initiating graceful shutdown...")
    if bot_app and bot_app.updater and bot_app.updater.running:
        try:
            logger.info("Stopping Telegram Bot polling...")
            await bot_app.updater.stop()
            await bot_app.stop()
            await bot_app.shutdown()
            logger.info("Telegram Bot shut down cleanly.")
        except Exception as e:
            logger.error("Error during Telegram Bot shutdown: %s", e)


# Initialize FastAPI app
app = FastAPI(
    title="Event-Driven Personal Expense Tracking AI Agent",
    description="Asynchronous backend for mobile bank notification webhooks and AI expense categorization via Telegram.",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/", tags=["General"])
async def root():
    """Service status and quick info."""
    return {
        "service": "Event-Driven Personal Expense Tracking AI Agent",
        "status": "online",
        "docs": "/docs",
    }


@app.get("/health", tags=["Monitoring"])
async def health_check():
    """Health check endpoint for service monitoring."""
    settings = get_settings()
    bot_app = get_bot_application()
    bot_running = bool(bot_app and bot_app.updater and bot_app.updater.running)

    return {
        "status": "healthy",
        "bot_polling": bot_running,
        "allowed_chat_id_configured": bool(settings.ALLOWED_CHAT_ID),
        "openrouter_configured": bool(settings.OPENROUTER_API_KEY),
        "google_sheets_configured": google_sheets_db.is_configured(),
        "google_sheet_id": settings.GOOGLE_SHEET_ID or None,
    }


@app.post(
    "/webhook/mobile",
    status_code=status.HTTP_200_OK,
    tags=["Webhooks"],
    summary="Receive mobile bank notification",
)
async def mobile_webhook(
    payload: MobileNotificationPayload,
    x_secret_key: Optional[str] = Header(None, alias="x-secret-key"),
):
    """Receive bank notifications from mobile devices (e.g., via iOS Shortcuts or Tasker / Macrodroid).

    1. Validates the `x-secret-key` header.
    2. Extracts the transaction amount via regex.
    3. Triggers a Telegram prompt to the user and tracks pending state.
    """
    settings = get_settings()

    # 1. Header Authentication Check
    if not x_secret_key or x_secret_key != settings.WEBHOOK_SECRET:
        logger.warning("Unauthorized webhook request. Provided key: %s", x_secret_key)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized: Invalid or missing x-secret-key header.",
        )

    logger.info(
        "Received mobile bank notification from [%s]: '%s'",
        payload.app_name,
        payload.text,
    )

    # 2. Extract transaction amount
    detected_amount = extract_amount_from_notification(payload.text)
    amount = detected_amount if detected_amount is not None else 0.0

    if detected_amount is not None:
        logger.info("Extracted amount from notification: %s", amount)
    else:
        logger.warning("Could not automatically extract amount from text: '%s'", payload.text)

    # If deposit detected (amount explicitly 0.0 from deposit keyword), skip expense alert
    if detected_amount == 0.0:
        logger.info("Deposit/income notification detected. Skipping Telegram alert.")
        return {
            "status": "ignored",
            "message": "Deposit notification detected. No expense alert triggered.",
            "detected_amount": 0.0,
            "app_name": payload.app_name,
        }

    # 3. Trigger asynchronous Telegram alert to user
    try:
        await send_transaction_alert(
            amount=amount,
            raw_text=payload.text,
            app_name=payload.app_name,
        )
    except Exception as e:
        logger.error("Failed to send Telegram alert: %s", e)

    return {
        "status": "success",
        "message": "Bank notification processed and Telegram alert dispatched.",
        "detected_amount": amount,
        "app_name": payload.app_name,
    }


@app.get("/expenses", tags=["Database"], response_model=List[Dict[str, Any]])
async def list_expenses(limit: int = 50):
    """Retrieve logged expenses from Google Sheets (or fallback JSON database)."""
    if google_sheets_db.is_configured():
        try:
            return await google_sheets_db.get_recent_expenses(limit=limit)
        except Exception as e:
            logger.warning("Could not fetch from Google Sheets: %s. Reading from mock DB.", e)

    expenses = await mock_db.get_all_expenses()
    return expenses[-limit:] if expenses else []


@app.get("/pending", tags=["State"])
async def get_pending_transactions():
    """Inspect active pending transactions in memory."""
    all_pending = await state_manager.get_all_pending()
    return {"pending_count": len(all_pending), "transactions": all_pending}


@app.delete("/pending", tags=["State"])
async def clear_pending_transactions():
    """Clear all pending transactions from memory."""
    settings = get_settings()
    removed = await state_manager.clear_pending(settings.ALLOWED_CHAT_ID)
    return {"status": "cleared" if removed else "no_pending_found"}


def main():
    """CLI entrypoint to run the server."""
    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
    )


if __name__ == "__main__":
    main()
