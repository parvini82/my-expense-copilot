import asyncio
import datetime
import logging
from typing import Any, Dict, List, Optional
from langchain_experimental.agents.agent_toolkits import create_pandas_dataframe_agent
import pandas as pd
from app.agent.llm_parser import get_llm_client
from app.database.google_sheets import google_sheets_db
from app.database.mock_db import mock_db

logger = logging.getLogger("expense_agent.qa_agent")

QA_SYSTEM_PREFIX = """You are an intelligent financial analyst assistant for personal expenses and transactions.
You have access to a pandas dataframe 'df' containing the user's recorded expenses with columns:
- 'Date': Date of transaction (YYYY-MM-DD)
- 'Amount': Numerical monetary amount spent/received
- 'Currency': Currency label (e.g., Toman, Rial, USD)
- 'Category': Main transaction category (e.g., Food & Dining, Relationship & Partner, Transportation, Shared Expense Refunds, etc.)
- 'Sub Category': Specific subcategory (e.g., Personal Meals, Friends' Share, Supermarket, etc.)
- 'Is Refund': Boolean (True/False) indicating if transaction is a shared expense refund ("Dong")
- 'Description': Description/details of the purchase
- 'Bank': Source bank or payment method

Current Date: {current_date}

Instructions:
1. Carefully analyze the dataframe to answer the user's questions accurately.
2. Calculate sums, averages, comparisons, top categories, or monthly totals by executing Python/pandas code.
3. If the user asks in Persian (Farsi), reply in Persian. If they ask in English, reply in English.
4. Format monetary numbers cleanly with commas (e.g., 2,500,000 Toman).
5. Always provide a clear, concise, and helpful final answer.
"""


def _prepare_dataframe(raw_records: List[Dict[str, Any]]) -> pd.DataFrame:
    """Convert raw expense records into a normalized pandas DataFrame."""
    required_cols = ["Date", "Amount", "Currency", "Category", "Sub Category", "Is Refund", "Description", "Bank"]
    if not raw_records:
        return pd.DataFrame(columns=required_cols)

    # 1. Normalize dictionary keys to avoid duplicate columns (e.g. 'amount' vs 'Amount')
    normalized_records = []
    for item in raw_records:
        row = {}
        for k, v in item.items():
            key_clean = str(k).strip().lower().replace("_", " ")
            if key_clean == "date":
                row["Date"] = str(v)
            elif key_clean == "amount":
                try:
                    row["Amount"] = float(v)
                except (ValueError, TypeError):
                    row["Amount"] = 0.0
            elif key_clean == "currency":
                row["Currency"] = str(v)
            elif key_clean == "category":
                row["Category"] = str(v)
            elif key_clean in ("sub category", "subcategory"):
                row["Sub Category"] = str(v)
            elif key_clean in ("is refund", "isrefund"):
                row["Is Refund"] = bool(v) if not isinstance(v, str) else v.lower() in ("true", "1", "yes")
            elif key_clean == "description":
                row["Description"] = str(v)
            elif key_clean == "bank":
                row["Bank"] = str(v)
            else:
                row[k] = v
        normalized_records.append(row)

    df = pd.DataFrame(normalized_records)

    # 2. Ensure required columns exist
    for col in required_cols:
        if col not in df.columns:
            if col == "Amount":
                df[col] = 0.0
            elif col == "Is Refund":
                df[col] = False
            else:
                df[col] = ""

    # 3. Clean types
    df["Amount"] = pd.to_numeric(df["Amount"], errors="coerce").fillna(0.0)
    df["Currency"] = df["Currency"].replace("", "Toman").fillna("Toman")
    df["Date"] = df["Date"].astype(str)
    df["Category"] = df["Category"].astype(str)
    df["Sub Category"] = df["Sub Category"].astype(str)
    df["Is Refund"] = df["Is Refund"].astype(bool)
    df["Description"] = df["Description"].astype(str)
    df["Bank"] = df["Bank"].astype(str)

    return df[required_cols]


async def fetch_expenses_dataframe() -> pd.DataFrame:
    """Load expense records from Google Sheets (or fallback to local DB) into a DataFrame."""
    records = []
    if google_sheets_db.is_configured():
        try:
            records = await google_sheets_db.get_all_expenses()
            logger.info("Loaded %d records from Google Sheets for QA agent.", len(records))
        except Exception as e:
            logger.warning("Failed to fetch from Google Sheets: %s. Using local DB fallback.", e)
            records = await mock_db.get_all_expenses()
    else:
        records = await mock_db.get_all_expenses()
        logger.info("Loaded %d records from local JSON database for QA agent.", len(records))

    return _prepare_dataframe(records)


async def ask_expenses_agent(user_query: str) -> str:
    """Ask a natural language question about expenses using LangChain Pandas DataFrame Agent.

    Args:
        user_query: The natural language question (e.g. 'How much did I spend on food this month?').

    Returns:
        str: Detailed answer generated by the agent.
    """
    if not user_query or not user_query.strip():
        return "❓ Please provide a question after the `/ask` command (e.g., `/ask چقدر این ماه خرج غذا کردم؟`)."

    logger.info("[QA AGENT] Received user query: '%s'", user_query)
    df = await fetch_expenses_dataframe()

    if df.empty or len(df) == 0:
        return "📂 No expenses found in the database yet. Record some transactions first to start analyzing!"

    current_date = datetime.date.today().isoformat()
    prefix = QA_SYSTEM_PREFIX.format(current_date=current_date)

    def _run_agent_sync() -> str:
        llm = get_llm_client()
        agent = create_pandas_dataframe_agent(
            llm=llm,
            df=df,
            verbose=False,
            allow_dangerous_code=True,
            handle_parsing_errors=True,
            prefix=prefix,
            max_iterations=5,
            agent_type="openai-tools",
        )

        try:
            response = agent.invoke({"input": user_query})
            output = response.get("output", "")
            return output if output else "I couldn't calculate an answer for that query."
        except Exception as e:
            logger.error("Pandas agent execution failed: %s", e, exc_info=True)
            # Fallback to direct calculation heuristic or helpful error
            return f"⚠️ An error occurred while analyzing your data: {str(e)}"

    result_text = await asyncio.to_thread(_run_agent_sync)
    logger.info("[QA AGENT] Completed response: %s", result_text)
    return result_text
