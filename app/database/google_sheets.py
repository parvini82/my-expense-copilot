import asyncio
import json
import logging
import os
from typing import Any, Dict, List, Optional
from google.oauth2.service_account import Credentials
import gspread
from gspread.exceptions import APIError, SpreadsheetNotFound, WorksheetNotFound
from app.config import get_settings

logger = logging.getLogger("expense_agent.google_sheets")

# Google Sheets API Scopes
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# Standard Sheet Column Headers
DEFAULT_HEADERS = ["Date", "Amount", "Currency", "Category", "Description", "Bank"]


class GoogleSheetsDatabase:
    """Asynchronous wrapper around gspread for storing expense records in Google Sheets."""

    def __init__(
        self,
        sheet_id: Optional[str] = None,
        credentials_path: Optional[str] = None,
    ) -> None:
        self.settings = get_settings()
        self.sheet_id = sheet_id or self.settings.GOOGLE_SHEET_ID
        self.credentials_path = credentials_path or self._resolve_credentials_path()
        self._client: Optional[gspread.Client] = None
        self._worksheet: Optional[gspread.Worksheet] = None
        self._lock = asyncio.Lock()

    def _resolve_credentials_path(self) -> str:
        """Find the service account credentials JSON file."""
        candidates = [
            self.settings.GOOGLE_CREDENTIALS_FILE,
            os.path.abspath(self.settings.GOOGLE_CREDENTIALS_FILE),
            os.path.join(os.getcwd(), "google_credentials.json"),
            os.path.join(os.path.dirname(os.path.dirname(__file__)), "google_credentials.json"),
            os.path.join(os.getcwd(), "app", "google_credentials.json"),
        ]
        for path in candidates:
            if path and os.path.exists(path):
                return path
        return "google_credentials.json"

    def is_configured(self) -> bool:
        """Check if Google Sheets integration is configured with credentials and Sheet ID."""
        return bool(self.sheet_id and os.path.exists(self.credentials_path))

    def _get_client_and_worksheet_sync(self) -> gspread.Worksheet:
        """Synchronous helper to authenticate and open the target Google Sheet worksheet."""
        if self._worksheet:
            return self._worksheet

        if not os.path.exists(self.credentials_path):
            raise FileNotFoundError(
                f"Google service account credentials file not found at: '{self.credentials_path}'. "
                "Ensure 'google_credentials.json' is placed in the project root."
            )

        if not self.sheet_id:
            raise ValueError(
                "GOOGLE_SHEET_ID is not configured. Please set GOOGLE_SHEET_ID in your .env file."
            )

        logger.info(
            "[GOOGLE SHEETS] Authenticating with service account '%s'...",
            self.credentials_path,
        )
        creds = Credentials.from_service_account_file(self.credentials_path, scopes=SCOPES)
        client = gspread.authorize(creds)
        self._client = client

        # Open by ID, URL, or Name
        sheet = None
        try:
            if self.sheet_id.startswith("http://") or self.sheet_id.startswith("https://"):
                logger.info("[GOOGLE SHEETS] Opening spreadsheet by URL...")
                sheet = client.open_by_url(self.sheet_id)
            elif len(self.sheet_id) > 25 and "/" not in self.sheet_id:
                # Typical Google Sheet ID is ~44 characters
                logger.info("[GOOGLE SHEETS] Opening spreadsheet by Key/ID '%s'...", self.sheet_id)
                sheet = client.open_by_key(self.sheet_id)
            else:
                logger.info("[GOOGLE SHEETS] Opening spreadsheet by Title '%s'...", self.sheet_id)
                sheet = client.open(self.sheet_id)
        except SpreadsheetNotFound as e:
            # Extract client_email from credentials to provide a helpful message
            client_email = "your-service-account-email"
            try:
                with open(self.credentials_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    client_email = data.get("client_email", client_email)
            except Exception:
                pass

            error_msg = (
                f"Google Spreadsheet '{self.sheet_id}' was not found. "
                f"IMPORTANT: Please make sure you have shared your Google Sheet with "
                f"the Service Account email ({client_email}) with 'Editor' permissions."
            )
            logger.error("[GOOGLE SHEETS] %s", error_msg)
            raise SpreadsheetNotFound(error_msg) from e

        worksheet = sheet.sheet1
        self._worksheet = worksheet

        # Check and initialize headers if row 1 is empty
        self._ensure_headers_sync(worksheet)
        return worksheet

    def _ensure_headers_sync(self, worksheet: gspread.Worksheet) -> None:
        """Synchronously check if row 1 contains headers; initialize if empty."""
        try:
            first_row = worksheet.row_values(1)
            if not first_row:
                logger.info("[GOOGLE SHEETS] Initializing column headers: %s", DEFAULT_HEADERS)
                worksheet.insert_row(DEFAULT_HEADERS, index=1, value_input_option="USER_ENTERED")
        except Exception as e:
            logger.warning("[GOOGLE SHEETS] Could not verify/initialize headers: %s", e)

    async def append_expense(
        self,
        expense_data: Any,
        bank: str = "Bank",
        currency: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Append a new expense row to Google Sheets asynchronously.

        Columns: [Date, Amount, Currency, Category, Description, Bank]

        Args:
            expense_data: Pydantic ExpenseRecord or dict containing expense attributes.
            bank: Source bank or notification name (e.g. 'Mellat', 'Chase', 'Telegram').
            currency: Currency label (defaults to Settings.DEFAULT_CURRENCY or 'Toman').

        Returns:
            Dict containing the serialized record.
        """
        async with self._lock:
            # 1. Normalize record
            if hasattr(expense_data, "model_dump"):
                record = expense_data.model_dump()
            elif isinstance(expense_data, dict):
                record = dict(expense_data)
            else:
                raise ValueError(f"Invalid expense data type: {type(expense_data)}")

            date_val = str(record.get("date", ""))
            amount_val = float(record.get("amount", 0.0))
            category_val = str(record.get("category", "Miscellaneous"))
            desc_val = str(record.get("description", ""))
            curr_val = currency or record.get("currency") or self.settings.DEFAULT_CURRENCY or "Toman"
            bank_val = bank or record.get("bank") or "Bank"

            row_values = [
                date_val,
                amount_val,
                curr_val,
                category_val,
                desc_val,
                bank_val,
            ]

            logger.info("[GOOGLE SHEETS] Attempting to append row: %s", row_values)

            # 2. Run synchronous gspread operations in thread pool
            def _sync_append():
                worksheet = self._get_client_and_worksheet_sync()
                res = worksheet.append_row(row_values, value_input_option="USER_ENTERED")
                return res

            try:
                await asyncio.to_thread(_sync_append)
                logger.info(
                    "[GOOGLE SHEETS] ✅ Successfully appended row to Google Sheet [%s]: %s",
                    self.sheet_id,
                    row_values,
                )
                record["currency"] = curr_val
                record["bank"] = bank_val
                return record
            except Exception as e:
                logger.error("[GOOGLE SHEETS] ❌ Error appending expense to Google Sheets: %s", e, exc_info=True)
                raise

    async def get_all_expenses(self) -> List[Dict[str, Any]]:
        """Retrieve all expenses from the Google Sheet."""
        async with self._lock:
            def _sync_get_all():
                worksheet = self._get_client_and_worksheet_sync()
                return worksheet.get_all_records()

            try:
                records = await asyncio.to_thread(_sync_get_all)
                logger.info("[GOOGLE SHEETS] Fetched %d records from Google Sheet.", len(records))
                return records
            except Exception as e:
                logger.error("[GOOGLE SHEETS] Error fetching records: %s", e, exc_info=True)
                return []

    async def get_recent_expenses(self, limit: int = 5) -> List[Dict[str, Any]]:
        """Retrieve the most recent N expenses from the Google Sheet."""
        records = await self.get_all_expenses()
        return records[-limit:] if records else []


# Global singleton instance
google_sheets_db = GoogleSheetsDatabase()
