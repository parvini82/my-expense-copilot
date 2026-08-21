import asyncio
import datetime
import io
import logging
from typing import Optional, Tuple
import arabic_reshaper
from bidi.algorithm import get_display
import matplotlib
# Use non-interactive Agg backend to prevent GUI thread issues
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from app.agent.qa_agent import fetch_expenses_dataframe

logger = logging.getLogger("expense_agent.reporting")


def format_persian_text(text: str) -> str:
    """Reshape and reorder Persian/Arabic text for correct Matplotlib rendering."""
    if not text:
        return ""
    try:
        reshaped_text = arabic_reshaper.reshape(text)
        bidi_text = get_display(reshaped_text)
        return bidi_text
    except Exception:
        return text


def _generate_pie_chart_sync(df: pd.DataFrame, target_month: str) -> Tuple[Optional[io.BytesIO], str]:
    """Synchronously filter DataFrame by month, generate matplotlib pie chart, and build summary text."""
    if df.empty:
        return None, "📂 No expense records found in the database."

    # Filter by target month (YYYY-MM)
    # Ensure Date column starts with target_month
    month_df = df[df["Date"].astype(str).str.startswith(target_month)].copy()

    if month_df.empty:
        available_dates = df["Date"].unique()
        return None, (
            f"📅 No expenses found for `{target_month}`.\n\n"
            f"Existing recorded dates range from {min(available_dates)} to {max(available_dates)}."
        )

    # Group by category and calculate sum
    category_summary = month_df.groupby("Category")["Amount"].sum().sort_values(ascending=False)
    total_spent = category_summary.sum()

    if total_spent <= 0:
        return None, f"ℹ️ Total expenses for `{target_month}` amount to 0."

    currency = month_df["Currency"].iloc[0] if "Currency" in month_df.columns and not month_df.empty else "Toman"

    # Color palette (Modern aesthetic palette)
    colors = [
        "#4E79A7", "#F28E2B", "#E15759", "#76B7B2", "#59A14F",
        "#EDC948", "#B07AA1", "#FF9DA7", "#9C755F", "#BAB0AC",
    ]

    # Create Matplotlib Figure
    plt.style.use("seaborn-v0_8-whitegrid" if "seaborn-v0_8-whitegrid" in plt.style.available else "default")
    fig, ax = plt.subplots(figsize=(8, 6), dpi=150)

    # Reshape labels for Persian/Arabic support
    categories = category_summary.index.tolist()
    values = category_summary.values.tolist()
    reshaped_labels = [format_persian_text(cat) for cat in categories]

    # Create Donut / Pie Chart
    wedges, texts, autotexts = ax.pie(
        values,
        labels=reshaped_labels,
        autopct=lambda pct: f"{pct:.1f}%" if pct >= 3 else "",
        pctdistance=0.75,
        startangle=140,
        colors=colors[: len(categories)],
        wedgeprops=dict(width=0.45, edgecolor="white", linewidth=2),
    )

    # Styling labels and percentages
    for autotext in autotexts:
        autotext.set_color("black")
        autotext.set_fontsize(9)
        autotext.set_fontweight("bold")

    for text in texts:
        text.set_fontsize(10)

    title_text = format_persian_text(f"گزارش مخارج ماهانه ({target_month})")
    ax.set_title(f"{title_text}\nTotal: {total_spent:,.0f} {currency}", fontsize=14, fontweight="bold", pad=20)

    plt.tight_layout()

    # Save to in-memory bytes buffer
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)

    # Build textual breakdown summary
    summary_lines = [
        f"📊 *گزارش مخارج ماه ({target_month})*\n",
        f"💰 *مجموع کل:* `{total_spent:,.0f}` {currency}\n",
        "📑 *تفکیک دسته‌بندی‌ها:*",
    ]
    for cat, val in category_summary.items():
        percentage = (val / total_spent) * 100
        summary_lines.append(f"• *{cat}:* `{val:,.0f}` {currency} ({percentage:.1f}%)")

    top_cat = category_summary.index[0]
    summary_lines.append(f"\n🏆 *بیشترین هزینه:* {top_cat} (`{category_summary.iloc[0]:,.0f}` {currency})")

    caption = "\n".join(summary_lines)
    return buf, caption


async def generate_monthly_expense_chart(
    month: Optional[str] = None,
) -> Tuple[Optional[io.BytesIO], str]:
    """Generate a pie chart and statistical breakdown of monthly expenses.

    Args:
        month: Target month string in 'YYYY-MM' format (defaults to current month).

    Returns:
        Tuple[Optional[io.BytesIO], str]: In-memory image buffer and markdown caption text.
    """
    target_month = month or datetime.date.today().strftime("%Y-%m")
    logger.info("[REPORTING] Generating monthly expense chart for '%s'...", target_month)

    df = await fetch_expenses_dataframe()
    return await asyncio.to_thread(_generate_pie_chart_sync, df, target_month)
