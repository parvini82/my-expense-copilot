import datetime
import logging
from typing import Optional
from app.agent.qa_agent import fetch_expenses_dataframe
from app.config import get_settings

logger = logging.getLogger("expense_agent.budget")


def _match_category_budget(category_name: str) -> Optional[float]:
    """Find the configured budget limit for a category with fuzzy/bilingual matching."""
    settings = get_settings()
    budgets = settings.CATEGORY_BUDGETS or {}

    if not category_name:
        return None

    cleaned = category_name.strip().lower()

    # Exact key match
    for key, limit in budgets.items():
        if key.strip().lower() == cleaned:
            return float(limit)

    # Substring / partial match
    for key, limit in budgets.items():
        if key.strip().lower() in cleaned or cleaned in key.strip().lower():
            return float(limit)

    return None


async def check_and_send_budget_alert(
    category: str,
    new_expense_amount: float,
    bot,
    chat_id: int,
    currency: str = "Toman",
) -> Optional[dict]:
    """Check if the monthly total for a category exceeds its budget limit and dispatch alert.

    Args:
        category: Expense category name (e.g., 'Food & Dining', 'کافه و رستوران').
        new_expense_amount: The amount of the newly recorded expense.
        bot: Telegram Bot instance to send alerts.
        chat_id: Target user Telegram chat ID.
        currency: Currency symbol/label.

    Returns:
        Optional[dict]: Alert details dictionary if limit exceeded, otherwise None.
    """
    limit = _match_category_budget(category)
    if not limit or limit <= 0:
        return None

    try:
        df = await fetch_expenses_dataframe()
        current_month = datetime.date.today().strftime("%Y-%m")

        if df.empty:
            category_total = new_expense_amount
        else:
            # Filter current month
            month_df = df[df["Date"].astype(str).str.startswith(current_month)]
            # Filter category
            cat_df = month_df[month_df["Category"].str.lower() == category.lower()]
            category_total = float(cat_df["Amount"].sum())

        logger.info(
            "[BUDGET CHECK] Category '%s': Monthly Total = %s, Budget Limit = %s",
            category,
            category_total,
            limit,
        )

        if category_total > limit:
            over_amount = category_total - limit
            percentage = (category_total / limit) * 100

            warning_msg = (
                "🚨 *هشدار بودجه (Budget Alert)!*\n\n"
                f"شما از سقف بودجه تعیین شده برای دسته بندی *{category}* عبور کردید!\n\n"
                f"📊 *سقف بودجه ماهانه:* `{limit:,.0f}` {currency}\n"
                f"📈 *مجموع مخارج این ماه:* `{category_total:,.0f}` {currency} (*{percentage:.1f}%*)\n"
                f"⚠️ *مبلغ مازاد:* `{over_amount:,.0f}` {currency}\n\n"
                "💡 _پیشنهاد: برای مدیریت بهتر هزینه‌ها، خریدهای غیرضروری این دسته را کاهش دهید._"
            )

            if bot and chat_id:
                try:
                    await bot.send_message(
                        chat_id=chat_id,
                        text=warning_msg,
                        parse_mode="Markdown",
                    )
                    logger.info("[BUDGET CHECK] Dispatched budget alert to chat %d for '%s'", chat_id, category)
                except Exception as e:
                    logger.error("Failed to send budget warning alert message: %s", e)

            return {
                "category": category,
                "monthly_total": category_total,
                "limit": limit,
                "exceeded_by": over_amount,
                "percentage": percentage,
            }

    except Exception as e:
        logger.error("Error evaluating budget alerts: %s", e, exc_info=True)

    return None
