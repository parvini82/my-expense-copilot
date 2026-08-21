import asyncio
from datetime import datetime, timezone
from typing import Dict, List, Optional
import uuid
from pydantic import BaseModel, Field


class PendingTransaction(BaseModel):
    """Represents a bank notification waiting for user explanation and categorization."""

    id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique identifier for the pending transaction",
    )
    amount: float = Field(
        ...,
        description="Extracted monetary amount of the transaction",
    )
    raw_text: str = Field(
        ...,
        description="Original notification text received from the mobile webhook",
    )
    app_name: str = Field(
        default="Bank",
        description="Name of the banking or payment app (e.g., Chase, Revolut, Apple Pay)",
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp when the transaction was detected",
    )
    chat_id: int = Field(
        ...,
        description="Telegram chat ID of the user responsible for this transaction",
    )


class StateManager:
    """Thread-safe in-memory state manager for pending expense transactions."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._pending: Dict[int, PendingTransaction] = {}

    async def set_pending(self, chat_id: int, transaction: PendingTransaction) -> None:
        """Store a pending transaction for a specific chat ID."""
        async with self._lock:
            self._pending[chat_id] = transaction

    async def get_pending(self, chat_id: int) -> Optional[PendingTransaction]:
        """Retrieve the pending transaction for a given chat ID without removing it."""
        async with self._lock:
            return self._pending.get(chat_id)

    async def pop_pending(self, chat_id: int) -> Optional[PendingTransaction]:
        """Retrieve and remove the pending transaction for a given chat ID."""
        async with self._lock:
            return self._pending.pop(chat_id, None)

    async def clear_pending(self, chat_id: int) -> bool:
        """Remove the pending transaction for a given chat ID."""
        async with self._lock:
            if chat_id in self._pending:
                del self._pending[chat_id]
                return True
            return False

    async def has_pending(self, chat_id: int) -> bool:
        """Check whether there is an active pending transaction for the chat ID."""
        async with self._lock:
            return chat_id in self._pending

    async def get_all_pending(self) -> List[PendingTransaction]:
        """Return a list of all active pending transactions across all chats."""
        async with self._lock:
            return list(self._pending.values())


# Global singleton state manager instance
state_manager = StateManager()
