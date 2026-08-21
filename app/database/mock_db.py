import asyncio
import json
import logging
import os
from typing import Any, Dict, List, Optional
from app.config import get_settings

logger = logging.getLogger("expense_agent.database")


class MockDatabase:
    """Asynchronous, thread-safe JSON mock database for storing expense records."""

    def __init__(self, file_path: Optional[str] = None) -> None:
        configured_path = file_path or get_settings().DB_FILE_PATH
        # Ensure path is absolute so working directory variations don't lose the file
        if not os.path.isabs(configured_path):
            self.file_path = os.path.abspath(configured_path)
        else:
            self.file_path = configured_path

        self._lock = asyncio.Lock()
        self._ensure_file_exists()

    def _ensure_file_exists(self) -> None:
        """Create the JSON file and parent directories if they do not already exist."""
        directory = os.path.dirname(self.file_path)
        if directory and not os.path.exists(directory):
            os.makedirs(directory, exist_ok=True)

        if not os.path.exists(self.file_path) or os.path.getsize(self.file_path) == 0:
            try:
                with open(self.file_path, "w", encoding="utf-8") as f:
                    json.dump([], f, indent=2)
                logger.info("Initialized empty expense database at: %s", self.file_path)
            except Exception as e:
                logger.error("Failed to initialize database file %s: %s", self.file_path, e, exc_info=True)

    async def save_expense(self, expense_data: Any) -> Dict[str, Any]:
        """Save a new expense record to the JSON file.

        Args:
            expense_data: Pydantic model (with model_dump) or dictionary.

        Returns:
            The serialized record dict that was saved.
        """
        logger.info("[DB PIPELINE] Attempting to save expense record: %s (Target: %s)", expense_data, self.file_path)

        async with self._lock:
            # 1. Serialize data
            if hasattr(expense_data, "model_dump"):
                record = expense_data.model_dump()
            elif isinstance(expense_data, dict):
                record = dict(expense_data)
            else:
                raise ValueError(
                    f"Unsupported expense data type: {type(expense_data)}. Expected dict or Pydantic model."
                )

            # Ensure amount is float/number
            if "amount" in record:
                record["amount"] = float(record["amount"])

            # 2. Read existing records
            expenses = await self._read_data()
            previous_count = len(expenses)
            expenses.append(record)

            # 3. Write back
            await self._write_data(expenses)

            logger.info(
                "[DB PIPELINE] ✅ Successfully saved expense to %s! Previous count: %d, New count: %d. Record: %s",
                self.file_path,
                previous_count,
                len(expenses),
                record,
            )
            return record

    async def get_all_expenses(self) -> List[Dict[str, Any]]:
        """Retrieve all expense records from the JSON file."""
        async with self._lock:
            return await self._read_data()

    async def get_recent_expenses(self, limit: int = 5) -> List[Dict[str, Any]]:
        """Retrieve the most recent N expense records."""
        async with self._lock:
            expenses = await self._read_data()
            return expenses[-limit:] if expenses else []

    async def clear_expenses(self) -> None:
        """Clear all stored expenses (useful for testing or reset)."""
        async with self._lock:
            await self._write_data([])
            logger.info("[DB PIPELINE] Cleared all expenses from database at %s.", self.file_path)

    async def _read_data(self) -> List[Dict[str, Any]]:
        """Internal helper to read JSON data safely in a thread."""
        def _sync_read():
            if not os.path.exists(self.file_path):
                return []
            try:
                with open(self.file_path, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                    if not content:
                        return []
                    return json.loads(content)
            except json.JSONDecodeError as e:
                logger.warning("Corrupted or empty JSON db file at %s, returning empty list: %s", self.file_path, e)
                return []
            except Exception as e:
                logger.error("Error reading database file %s: %s", self.file_path, e, exc_info=True)
                return []

        return await asyncio.to_thread(_sync_read)

    async def _write_data(self, data: List[Dict[str, Any]]) -> None:
        """Internal helper to write JSON data safely in a thread."""
        def _sync_write():
            temp_file = f"{self.file_path}.tmp"
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            os.replace(temp_file, self.file_path)

        await asyncio.to_thread(_sync_write)


# Global singleton mock database instance
mock_db = MockDatabase()
