import asyncio
import unittest
from unittest.mock import MagicMock, patch
from app.agent.llm_parser import ExpenseRecord
from app.database.google_sheets import DEFAULT_HEADERS, GoogleSheetsDatabase


class TestGoogleSheetsDatabase(unittest.TestCase):
    """Unit tests for Google Sheets database wrapper."""

    def test_default_headers(self):
        """Verify column headers requirement: [Date, Amount, Currency, Category, Sub Category, Is Refund, Description, Bank]."""
        expected_columns = ["Date", "Amount", "Currency", "Category", "Sub Category", "Is Refund", "Description", "Bank"]
        self.assertEqual(DEFAULT_HEADERS, expected_columns)

    def test_is_configured_logic(self):
        """Test configuration detection with and without sheet_id."""
        db_unconfigured = GoogleSheetsDatabase(sheet_id="", credentials_path="non_existent.json")
        self.assertFalse(db_unconfigured.is_configured())

    def test_append_expense_sync_mock(self):
        """Test asynchronous append_expense with mocked gspread worksheet."""
        async def _run():
            mock_worksheet = MagicMock()
            mock_worksheet.row_values.return_value = DEFAULT_HEADERS
            mock_worksheet.append_row.return_value = {"updates": {"updatedRows": 1}}

            db = GoogleSheetsDatabase(sheet_id="test_sheet_id", credentials_path="google_credentials.json")
            db._worksheet = mock_worksheet

            record = ExpenseRecord(
                amount=50000.0,
                category="Food & Dining",
                sub_category="Social & Cafe",
                is_refund=False,
                description="Dinner with friends",
                date="2026-08-21",
                currency="Toman",
                bank="Mellat",
            )

            result = await db.append_expense(record, bank="Mellat", currency="Toman")

            self.assertEqual(result["amount"], 50000.0)
            self.assertEqual(result["category"], "Food & Dining")
            self.assertEqual(result["sub_category"], "Social & Cafe")
            self.assertFalse(result["is_refund"])
            self.assertEqual(result["bank"], "Mellat")
            self.assertEqual(result["currency"], "Toman")

            # Verify gspread append_row arguments
            mock_worksheet.append_row.assert_called_once_with(
                ["2026-08-21", 50000.0, "Toman", "Food & Dining", "Social & Cafe", False, "Dinner with friends", "Mellat"],
                value_input_option="USER_ENTERED",
            )

        asyncio.run(_run())

    def test_get_all_expenses_mock(self):
        """Test retrieving all expenses from Google Sheets with mock."""
        async def _run():
            mock_worksheet = MagicMock()
            mock_records = [
                {
                    "Date": "2026-08-21",
                    "Amount": 75000.0,
                    "Currency": "Toman",
                    "Category": "Groceries",
                    "Description": "Supermarket",
                    "Bank": "Saman",
                }
            ]
            mock_worksheet.get_all_records.return_value = mock_records

            db = GoogleSheetsDatabase(sheet_id="test_sheet_id", credentials_path="google_credentials.json")
            db._worksheet = mock_worksheet

            records = await db.get_all_expenses()
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["Amount"], 75000.0)
            self.assertEqual(records[0]["Bank"], "Saman")

        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main()
