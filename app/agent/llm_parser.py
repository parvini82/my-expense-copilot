import datetime
import logging
import os
import re
from typing import Optional
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field
from app.config import get_settings

logger = logging.getLogger("expense_agent.llm_parser")


class ExpenseRecord(BaseModel):
    """Structured representation of a categorized personal transaction."""

    amount: float = Field(
        ...,
        description="The monetary value of the transaction as a floating-point number.",
    )
    category: str = Field(
        ...,
        description="Main category of the transaction matching the required taxonomy.",
    )
    sub_category: str = Field(
        ...,
        description="Specific subcategory matching the main category taxonomy.",
    )
    is_refund: bool = Field(
        default=False,
        description="Set to True if this transaction is a shared expense refund / Dong (e.g. دنگ, سهم). Default False.",
    )
    description: str = Field(
        ...,
        description="A concise and clear description of the purchase/transaction based on the user's explanation and context.",
    )
    date: str = Field(
        ...,
        description="ISO 8601 date of the transaction in YYYY-MM-DD format.",
    )
    currency: Optional[str] = Field(
        default="Toman",
        description="Currency of the transaction (e.g. Toman, Rial, USD, EUR).",
    )
    bank: Optional[str] = Field(
        default="Bank",
        description="Bank or payment method name (e.g. Mellat, Saman, Chase, Apple Pay).",
    )


# Conversion mapping for Persian and Arabic digits to English
PERSIAN_ARABIC_DIGITS_TABLE = str.maketrans({
    "۰": "0", "۱": "1", "۲": "2", "۳": "3", "۴": "4",
    "۵": "5", "۶": "6", "۷": "7", "۸": "8", "۹": "9",
    "٠": "0", "١": "1", "٢": "2", "٣": "3", "٤": "4",
    "٥": "5", "٦": "6", "٧": "7", "٨": "8", "٩": "9",
})


def extract_amount_from_notification(text: str) -> Optional[float]:
    """Extract monetary transaction amount from bank notifications.

    Supports:
    - Iranian/Persian bank notifications (Rial, Toman, ریال, تومان)
    - Persian/Arabic digit conversion ('۰'-'۹' -> '0'-'9')
    - Removal of standard and Persian commas (',', '،')
    - Stripping out account balances after 'موجودی' or 'مانده'
    - International currencies ($45.20, €15.00, £12.50, USD, EUR)
    """
    if not text or not text.strip():
        return None

    # 1. Convert Persian/Arabic digits to English digits
    normalized_text = text.translate(PERSIAN_ARABIC_DIGITS_TABLE)

    # 2. Remove all standard commas and Persian commas
    normalized_text = normalized_text.replace(",", "").replace("،", "")

    # 3. Strip out account balance by removing text starting from 'موجودی' or 'مانده'
    # Using re.DOTALL so it strips across multiple lines if present
    stripped_text = re.sub(
        r"(?:موجودی|مانده|balance|available(?:\s+balance)?).*$",
        "",
        normalized_text,
        flags=re.DOTALL | re.IGNORECASE,
    ).strip()

    # 5. Regex for Iranian bank currencies: number immediately preceding 'ریال', 'تومان', 'Rial', 'Toman'
    persian_patterns = [
        # Number immediately preceding currency keyword (e.g., 50000 ریال, 25000 تومان, 50000 Rial, 25000 Toman)
        r"([0-9]+(?:\.[0-9]+)?)\s*(?:ریال|تومان|rial|toman)\b",
        # Number immediately following currency keyword (e.g., ریال 50000, تومان 25000, Rial: 50000)
        r"(?:ریال|تومان|rial|toman)\s*:?\s*([0-9]+(?:\.[0-9]+)?)",
        # Persian keywords followed by amount (e.g., مبلغ 50000, کسر 50000, برداشت 50000)
        r"(?:مبلغ|برداشت|کسر(?:\s+شد)?|خرید|پرداخت)\s*:?\s*([0-9]+(?:\.[0-9]+)?)",
    ]

    for pattern in persian_patterns:
        match = re.search(pattern, stripped_text, re.IGNORECASE)
        if match:
            raw_val = match.group(1).strip()
            try:
                val = float(raw_val)
                if val > 0:
                    logger.info("Extracted Persian/Iranian transaction amount: %f from '%s'", val, text)
                    return val
            except ValueError:
                continue

    # 6. Fallback to International Currency Patterns
    international_patterns = [
        # Currency symbol followed by number: $45.20, €15.00, £12.50, ¥500
        r"[\$\€\£\¥\₹]\s*([0-9]+(?:\.[0-9]{1,2})?)",
        # ISO Currency code followed by number: USD 45.20, EUR 15.00
        r"(?:USD|EUR|GBP|CAD|AUD|INR|CHF|JPY|AED)\s*([0-9]+(?:\.[0-9]{1,2})?)",
        # Number followed by currency symbol/code: 45.20 USD, 15.00 EUR, 45.20$
        r"([0-9]+(?:\.[0-9]{1,2})?)\s*(?:USD|EUR|GBP|CAD|AUD|INR|CHF|JPY|AED|[\$\€\£\¥\₹])",
        # Keywords followed by amount: charged 42.50, spent 19.99, debit of 100.00
        r"(?:charged|spent|paid|debit(?:ed)?(?:\s+of)?|payment(?:\s+of)?|purchase(?:\s+of)?|amount(?:\s+of)?)\s*(?:[\$\€\£\¥\₹]|USD|EUR|GBP)?\s*([0-9]+(?:\.[0-9]{1,2})?)",
        # Generic standalone decimal number (e.g. 42.50)
        r"\b([0-9]+\.[0-9]{2})\b",
    ]

    for pattern in international_patterns:
        match = re.search(pattern, stripped_text, re.IGNORECASE)
        if match:
            raw_val = match.group(1).strip()
            try:
                val = float(raw_val)
                if val > 0:
                    logger.info("Extracted international transaction amount: %f from '%s'", val, text)
                    return val
            except ValueError:
                continue

    logger.warning("Could not extract transaction amount from notification: '%s'", text)
    return None


def get_llm_client() -> ChatOpenAI:
    """Initialize LangChain ChatOpenAI configured for OpenRouter."""
    settings = get_settings()
    api_key = settings.OPENROUTER_API_KEY or os.getenv("OPENROUTER_API_KEY", "")
    api_base = settings.OPENROUTER_BASE_URL or "https://openrouter.ai/api/v1"
    model_name = settings.OPENROUTER_MODEL or "google/gemini-2.5-flash-exp:free"

    if not api_key:
        logger.warning("OPENROUTER_API_KEY is not set. LLM calls may fail.")

    # Explicitly configure openai_api_base and openai_api_key for OpenRouter routing
    return ChatOpenAI(
        model_name=model_name,
        openai_api_key=api_key,
        openai_api_base=api_base,
        temperature=0.0,
        default_headers={
            "HTTP-Referer": "https://github.com/expense-agent",
            "X-Title": "Personal Expense Tracker AI Agent",
        },
    )


async def parse_expense_with_llm(
    amount: float,
    user_explanation: str,
    raw_notification: Optional[str] = None,
) -> ExpenseRecord:
    """Parse amount and user explanation into a structured ExpenseRecord via OpenRouter LLM.

    Args:
        amount: The transaction amount detected from the notification.
        user_explanation: Text provided by the user (or transcribed from voice).
        raw_notification: Original bank notification text for extra context.

    Returns:
        ExpenseRecord: Pydantic structured model with amount, category, sub_category, is_refund, description, and date.
    """
    current_date = datetime.date.today().isoformat()
    raw_ctx = raw_notification or "N/A"

    system_prompt = (
        "You are an expert personal finance assistant.\n"
        "Your role is to strictly categorize and summarize personal transactions using the hierarchical taxonomy below.\n\n"
        f"Today's Date: {current_date}\n\n"
        "Taxonomy Guidelines:\n"
        "Expenses:\n"
        "  - Food & Dining: Personal Meals / Social & Cafe / Snacks & Daily Treats / Supermarket\n"
        "  - Relationship & Partner: Date & Outings / Gifts & Shopping\n"
        "  - Transportation: Ride-hailing / Fuel & Car / Public Transit\n"
        "  - Personal Care & Shopping: Clothing / Grooming & Hygiene\n"
        "  - Bills & Utilities: Mobile Data / Subscriptions\n"
        "  - Healthcare: Pharmacy / Doctor Visits\n"
        "  - Savings & Investments: Vault Transfer / Gold & Crypto\n"
        "Incomes:\n"
        "  - Salary & Earnings: Fixed Salary / Bonus & Project\n"
        "  - Family: Allowance from Father / Gifts\n"
        "  - Internal Transfers: Savings Transfer\n"
        "  - Shared Expense Refunds (\"Dong\"): Friends' Share / Shared Purchase\n"
        "  - Other: Bank Interest / Miscellaneous\n\n"
        "STRICT REFUND RULE (\"Dong\"):\n"
        "If the user input indicates the inflow is someone paying back their share (e.g., \"دنگ\", \"سهم\", \"dong\", \"share\"), "
        "you MUST set category=\"Shared Expense Refunds\", set the relevant sub_category (e.g. \"Friends' Share\" or \"Shared Purchase\"), and MUST set is_refund=True.\n"
        "Otherwise, set is_refund=False by default.\n\n"
        "General Field Rules:\n"
        "1. Amount: Use the provided detected amount unless the user explicitly specifies a different amount in their explanation.\n"
        "2. Category & Sub-category: Select the exact main category and subcategory from the taxonomy.\n"
        "3. Description: Write a clear, concise summary of the transaction (in Persian or English based on user input).\n"
        "4. Date: Return the date in YYYY-MM-DD format (use today's date if not specified otherwise).\n"
    )

    human_prompt = (
        "Detected Transaction Amount: {amount}\n"
        "Bank Notification Context: {raw_context}\n"
        "User Explanation: {user_explanation}\n\n"
        "Please extract and return the structured expense record."
    )

    prompt = ChatPromptTemplate.from_messages([
        ("system", system_prompt),
        ("human", human_prompt),
    ])

    llm = get_llm_client()

    try:
        logger.info(
            "Invoking OpenRouter LLM for categorization (amount=%s, user_input='%s')...",
            amount,
            user_explanation,
        )
        structured_llm = llm.with_structured_output(ExpenseRecord)
        chain = prompt | structured_llm

        raw_result = await chain.ainvoke({
            "amount": amount,
            "raw_context": raw_ctx,
            "user_explanation": user_explanation,
        })

        logger.info("Raw response from OpenRouter LLM: %s (type: %s)", raw_result, type(raw_result))

        # Handle Pydantic model vs dict vs unexpected return type
        if isinstance(raw_result, ExpenseRecord):
            result = raw_result
        elif isinstance(raw_result, dict):
            result = ExpenseRecord.model_validate(raw_result)
        else:
            raise ValueError(f"Unexpected LLM output type: {type(raw_result)}")

        # Ensure amount is a valid float
        if result.amount <= 0 and amount > 0:
            result.amount = amount

        logger.info("Successfully validated ExpenseRecord: %s", result)
        return result

    except Exception as e:
        logger.error("LLM structured output call failed or raised error: %s. Using resilient fallback.", e, exc_info=True)
        # Resilient fallback if LLM or API fails
        fallback_amount = amount if amount > 0 else 0.0
        # Try extracting amount from user explanation if amount was 0
        if fallback_amount == 0.0 and user_explanation:
            user_extracted = extract_amount_from_notification(user_explanation)
            if user_extracted:
                fallback_amount = user_extracted

        is_refund_fallback = any(k in (user_explanation or "") for k in ["دنگ", "سهم", "dong"])

        return ExpenseRecord(
            amount=fallback_amount,
            category="Shared Expense Refunds" if is_refund_fallback else "Other",
            sub_category="Friends' Share" if is_refund_fallback else "Miscellaneous",
            is_refund=is_refund_fallback,
            description=user_explanation[:100] if user_explanation else "Bank Transaction",
            date=current_date,
        )

