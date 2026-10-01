import logging
import os
from functools import lru_cache
from typing import Optional
from dotenv import load_dotenv
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Load environment variables from .env file if present
load_dotenv()

logger = logging.getLogger("expense_agent.config")


class Settings(BaseSettings):
    """Application configuration loaded from environment variables."""

    # Telegram Configuration
    TELEGRAM_BOT_TOKEN: str = Field(
        default="",
        description="Bot token from @BotFather",
    )
    ALLOWED_CHAT_ID: int = Field(
        default=0,
        description="Telegram chat ID allowed to interact with the bot",
    )

    # OpenRouter / LLM Configuration
    OPENROUTER_API_KEY: str = Field(
        default="",
        description="API key for OpenRouter service",
    )
    OPENROUTER_BASE_URL: str = Field(
        default="https://openrouter.ai/api/v1",
        description="Base URL for OpenRouter API endpoints",
    )
    OPENROUTER_MODEL: str = Field(
        default="google/gemini-2.5-flash-exp:free",
        description="Model identifier to use via OpenRouter",
    )

    # OpenAI Configuration (Whisper)
    OPENAI_API_KEY: Optional[str] = Field(
        default=None,
        description="OpenAI API key for Whisper audio transcription",
    )

    # Webhook Security
    WEBHOOK_SECRET: str = Field(
        default="change_me_to_a_secure_random_string",
        description="Secret key required in x-secret-key header for webhooks",
    )

    # Storage & Database Settings
    DB_FILE_PATH: str = Field(
        default="expenses.json",
        description="Path to local JSON expense storage file (fallback)",
    )
    GOOGLE_SHEET_ID: str = Field(
        default="",
        description="Google Sheets Document ID or Spreadsheet Name",
    )
    GOOGLE_CREDENTIALS_FILE: str = Field(
        default="google_credentials.json",
        description="Path to service account JSON credentials file",
    )
    DEFAULT_CURRENCY: str = Field(
        default="Toman",
        description="Default currency label recorded in database/sheets",
    )

    # Budget Configuration (Monthly limit per category)
    # --------------------------------------------------------------------------
    CATEGORY_BUDGETS: dict = Field(
        default_factory=lambda: {
            "Food & Dining": 2000000.0,
            "کافه و رستوران": 2000000.0,
            "غذا و رستوران": 2000000.0,
            "Groceries": 3000000.0,
            "سوپرمارکت": 3000000.0,
            "Shopping": 5000000.0,
            "خرید": 5000000.0,
            "Transportation": 1000000.0,
            "حمل و نقل": 1000000.0,
            "Utilities & Bills": 1500000.0,
            "قبوض": 1500000.0,
            "Entertainment": 1500000.0,
            "تفریح": 1500000.0,
        },
        description="Dictionary mapping category names to monthly spending budget limits",
    )

    # Server Settings
    HOST: str = Field(default="0.0.0.0", description="Host address for FastAPI server")
    PORT: int = Field(default=8000, description="Port for FastAPI server")
    DEBUG: bool = Field(default=False, description="Enable debug logging and hot-reload")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator("ALLOWED_CHAT_ID", mode="before")
    @classmethod
    def parse_chat_id(cls, v):
        if isinstance(v, str):
            v = v.strip()
            if not v:
                return 0
            return int(v)
        return v or 0

    def validate_runtime_keys(self) -> None:
        """Log warnings or validation notices for essential runtime keys."""
        missing = []
        if not self.TELEGRAM_BOT_TOKEN:
            missing.append("TELEGRAM_BOT_TOKEN")
        if not self.ALLOWED_CHAT_ID:
            missing.append("ALLOWED_CHAT_ID")
        if not self.OPENROUTER_API_KEY:
            missing.append("OPENROUTER_API_KEY")

        if missing:
            logger.warning(
                "⚠️ Missing critical environment variables: %s. "
                "Ensure these are set in your .env file or environment.",
                ", ".join(missing),
            )
        else:
            logger.info("✅ All core environment variables validated.")


@lru_cache()
def get_settings() -> Settings:
    """Return cached instance of application settings."""
    settings = Settings()
    return settings
