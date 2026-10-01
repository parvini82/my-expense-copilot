import asyncio
import os
import unittest
from app.agent.llm_parser import ExpenseRecord, extract_amount_from_notification
from app.database.mock_db import MockDatabase
from app.state import PendingTransaction, StateManager


class TestExpenseAgent(unittest.TestCase):
    """Unit tests for regex parsing, Pydantic schemas, StateManager, and MockDatabase."""

    def test_amount_extraction_regex(self):
        """Test regex parsing on various bank notification formats including Iranian/Persian banks."""
        test_cases = [
            # Persian digits and Rial
            ("برداشت مبلغ ۵۰،۰۰۰ ریال از حساب ۱۲۳۴ موجودی: ۵۰۰،۰۰۰ ریال", 50000.0),
            # Persian digits and Toman
            ("مبلغ ۲۵،۰۰۰ تومان از کارت کسر شد مانده: ۱۰۰،۰۰۰ تومان", 25000.0),
            # English digits with Rial and balance stripping
            ("برداشت 500,000 ریال از حساب 1234 موجودی: 12,000,000 ریال", 500000.0),
            # English digits with Toman and Persian comma
            ("کارت 5678؛ برداشت: 75،000 تومان؛ مانده: 350،000 تومان", 75000.0),
            # Toman in English letters
            ("Purchase of 150000 Toman approved. Balance: 400000 Toman", 150000.0),
            # Rial in English letters
            ("Payment: 250000 Rial. Available balance: 1000000 Rial", 250000.0),
            # Deposit / Income notification (extracts monetary amount normally)
            ("واریز مبلغ 1,000,000 ریال به حساب شما", 1000000.0),
            ("مبلغ ۲،۰۰۰،۰۰۰ ریال به حساب شما نشست موجودی: ۵،۰۰۰،۰۰۰ ریال", 2000000.0),
            ("واریز شد: 500,000 تومان", 500000.0),
            # International formats
            ("Chase: You made a $42.50 purchase at WHOLEFDS.", 42.50),
            ("Alert: Debit of USD 12.99 from Account ending in 1234", 12.99),
            ("Your card was charged €15.00 by UBER", 15.00),
            ("You spent £8.75 at Starbucks", 8.75),
            ("Payment of 120.00 USD received", 120.00),
            ("Purchase of $1,250.00 at Apple Store", 1250.00),
            ("Account debited by 99.50", 99.50),
            ("No numbers in this text", None),
        ]

        for text, expected in test_cases:
            result = extract_amount_from_notification(text)
            self.assertEqual(
                result,
                expected,
                f"Failed for '{text}': got {result}, expected {expected}",
            )

    def test_expense_record_schema(self):
        """Test Pydantic model validation for ExpenseRecord."""
        record = ExpenseRecord(
            amount=25.50,
            category="Food & Dining",
            sub_category="Personal Meals",
            description="Dinner at Chipotle",
            date="2026-08-21",
        )
        self.assertEqual(record.amount, 25.50)
        self.assertEqual(record.category, "Food & Dining")
        self.assertEqual(record.sub_category, "Personal Meals")
        self.assertEqual(record.description, "Dinner at Chipotle")
        self.assertEqual(record.date, "2026-08-21")

    def test_state_manager_lifecycle(self):
        """Test setting, getting, and popping pending transactions."""
        async def _run():
            manager = StateManager()
            chat_id = 987654321

            # Initially empty
            self.assertIsNone(await manager.get_pending(chat_id))
            self.assertFalse(await manager.has_pending(chat_id))

            # Set transaction
            tx = PendingTransaction(
                amount=35.00,
                raw_text="Spent $35 at Target",
                app_name="BankApp",
                chat_id=chat_id,
            )
            await manager.set_pending(chat_id, tx)

            self.assertTrue(await manager.has_pending(chat_id))
            retrieved = await manager.get_pending(chat_id)
            self.assertIsNotNone(retrieved)
            self.assertEqual(retrieved.amount, 35.00)

            # Pop transaction
            popped = await manager.pop_pending(chat_id)
            self.assertIsNotNone(popped)
            self.assertEqual(popped.amount, 35.00)
            self.assertFalse(await manager.has_pending(chat_id))

        asyncio.run(_run())

    def test_mock_database(self):
        """Test MockDatabase file saving and reading."""
        async def _run():
            test_db_path = "test_expenses_tmp.json"
            if os.path.exists(test_db_path):
                os.remove(test_db_path)

            try:
                db = MockDatabase(file_path=test_db_path)

                # Initially empty
                records = await db.get_all_expenses()
                self.assertEqual(records, [])

                # Save record
                exp = ExpenseRecord(
                    amount=19.99,
                    category="Bills & Utilities",
                    sub_category="Subscriptions",
                    description="Monthly Netflix subscription",
                    date="2026-08-21",
                )
                await db.save_expense(exp)

                # Read back
                records = await db.get_all_expenses()
                self.assertEqual(len(records), 1)
                self.assertEqual(records[0]["amount"], 19.99)
                self.assertEqual(records[0]["category"], "Bills & Utilities")
                self.assertEqual(records[0]["sub_category"], "Subscriptions")
            finally:
                if os.path.exists(test_db_path):
                    os.remove(test_db_path)

        asyncio.run(_run())

    def test_full_pipeline_saving(self):
        """Test full save pipeline with ExpenseRecord serialization into JSON mock_db."""
        async def _run():
            test_db_path = "test_pipeline_expenses.json"
            if os.path.exists(test_db_path):
                os.remove(test_db_path)

            try:
                db = MockDatabase(file_path=test_db_path)
                record = ExpenseRecord(
                    amount=50000.0,
                    category="Food & Dining",
                    sub_category="Personal Meals",
                    description="ناهار رستوران (Restaurant Lunch)",
                    date="2026-08-21",
                )
                saved = await db.save_expense(record)
                self.assertEqual(saved["amount"], 50000.0)
                self.assertEqual(saved["category"], "Food & Dining")
                self.assertEqual(saved["sub_category"], "Personal Meals")
                self.assertEqual(saved["description"], "ناهار رستوران (Restaurant Lunch)")

                # Verify persistent read from disk
                all_records = await db.get_all_expenses()
                self.assertEqual(len(all_records), 1)
                self.assertEqual(all_records[0]["amount"], 50000.0)
            finally:
                if os.path.exists(test_db_path):
                    os.remove(test_db_path)

        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main()
