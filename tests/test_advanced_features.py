import asyncio
import io
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import pandas as pd
from app.agent.budget import _match_category_budget, check_and_send_budget_alert
from app.agent.qa_agent import _prepare_dataframe
from app.agent.reporting import _generate_pie_chart_sync, format_persian_text


class TestAdvancedFeatures(unittest.TestCase):
    """Unit tests for QA Agent, Visual Reports, and Budget Alert features."""

    def test_persian_text_formatting(self):
        """Test that Persian text reshaping produces non-empty string."""
        sample_text = "کافه و رستوران"
        reshaped = format_persian_text(sample_text)
        self.assertTrue(len(reshaped) > 0)
        self.assertIsInstance(reshaped, str)

    def test_prepare_dataframe_structure(self):
        """Test normalization of raw records into a standardized DataFrame."""
        raw_data = [
            {
                "date": "2026-08-21",
                "amount": "50000",
                "category": "Food & Dining",
                "description": "Lunch",
                "currency": "Toman",
                "bank": "Mellat",
            },
            {
                "Date": "2026-08-20",
                "Amount": 120000.0,
                "Category": "Shopping",
                "Description": "Clothes",
                "Currency": "Toman",
                "Bank": "Saman",
            },
        ]
        df = _prepare_dataframe(raw_data)
        self.assertEqual(len(df), 2)
        self.assertIn("Amount", df.columns)
        self.assertEqual(df["Amount"].iloc[0], 50000.0)
        self.assertEqual(df["Amount"].iloc[1], 120000.0)

    def test_monthly_pie_chart_generation(self):
        """Test synchronous pie chart generation and caption construction."""
        df = pd.DataFrame([
            {
                "Date": "2026-08-15",
                "Amount": 100000.0,
                "Category": "Food & Dining",
                "Description": "Dinner",
                "Currency": "Toman",
                "Bank": "Mellat",
            },
            {
                "Date": "2026-08-18",
                "Amount": 200000.0,
                "Category": "Groceries",
                "Description": "Supermarket",
                "Currency": "Toman",
                "Bank": "Saman",
            },
        ])

        buf, caption = _generate_pie_chart_sync(df, target_month="2026-08")
        self.assertIsNotNone(buf)
        self.assertIsInstance(buf, io.BytesIO)
        self.assertTrue(len(buf.getvalue()) > 0)
        self.assertIn("300,000", caption)
        self.assertIn("Groceries", caption)
        self.assertIn("Food & Dining", caption)

    def test_budget_matching(self):
        """Test budget category matching logic."""
        # Exact match
        limit_food = _match_category_budget("Food & Dining")
        self.assertEqual(limit_food, 2000000.0)

        # Persian category match
        limit_persian = _match_category_budget("کافه و رستوران")
        self.assertEqual(limit_persian, 2000000.0)

        # Non-configured category
        limit_none = _match_category_budget("UnconfiguredCategory999")
        self.assertIsNone(limit_none)

    def test_budget_alert_threshold_exceeded(self):
        """Test budget alert triggers when total exceeds the configured threshold."""
        async def _run():
            mock_bot = AsyncMock()
            mock_df = pd.DataFrame([
                {
                    "Date": "2026-08-10",
                    "Amount": 1800000.0,
                    "Category": "Food & Dining",
                    "Description": "Dinner 1",
                    "Currency": "Toman",
                    "Bank": "Mellat",
                },
                {
                    "Date": "2026-08-20",
                    "Amount": 500000.0,
                    "Category": "Food & Dining",
                    "Description": "Dinner 2",
                    "Currency": "Toman",
                    "Bank": "Mellat",
                },
            ])

            with patch("app.agent.budget.fetch_expenses_dataframe", return_value=mock_df):
                alert_result = await check_and_send_budget_alert(
                    category="Food & Dining",
                    new_expense_amount=500000.0,
                    bot=mock_bot,
                    chat_id=123456,
                    currency="Toman",
                )

                self.assertIsNotNone(alert_result)
                self.assertEqual(alert_result["monthly_total"], 2300000.0)
                self.assertEqual(alert_result["limit"], 2000000.0)
                self.assertEqual(alert_result["exceeded_by"], 300000.0)
                mock_bot.send_message.assert_called_once()

        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main()
