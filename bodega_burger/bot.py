"""
Bodega Burger — Telegram Bot
Commands:
  /start        Welcome message
  /help         Command list
  /summary      Weekly KPIs
  /stock        Stock inventory + low-stock alerts
  /income       Record daily sales: /income 1250.50 Friday lunch
  /expenses     Last 10 expenses
  /report       Current month P&L
  [photo]       Process receipt image → parse → save → update stock
"""
from __future__ import annotations

import asyncio
import datetime
import logging
import os
from pathlib import Path

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from ai_parser import format_receipt_summary, generate_chat_response, parse_receipt_image
from config import RECEIPT_IMAGES_DIR, TELEGRAM_BOT_TOKEN
from database import (
    add_income_entry,
    get_all_stock,
    get_low_stock_items,
    get_monthly_pl,
    get_receipt_by_id,
    get_recent_expenses,
    get_weekly_summary,
    init_db,
    save_receipt,
    upsert_stock_from_receipt_items,
)

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _money(val: float) -> str:
    return f"${val:,.2f}"


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "<b>Welcome to Bodega Burger Manager</b>\n\n"
        "Send a <b>receipt photo</b> and I'll parse it automatically.\n\n"
        "<b>Commands:</b>\n"
        "/summary — Weekly revenue, expenses & profit\n"
        "/stock — Current inventory\n"
        "/income &lt;amount&gt; [note] — Record sales\n"
        "/expenses — Last 10 expenses\n"
        "/report — This month's P&amp;L\n"
        "/help — Full help\n"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    help_text = await asyncio.to_thread(
        generate_chat_response,
        "Generate a concise help message listing all available bot commands and what they do.",
        "List all commands for the Bodega Burger restaurant management bot with brief descriptions.",
    )
    # Prepend static command list in case AI response is cut
    static = (
        "<b>Bodega Burger Bot — Commands</b>\n\n"
        "/start — Welcome & quick guide\n"
        "/summary — Weekly KPIs\n"
        "/stock — Inventory status\n"
        "/income 1250.50 [note] — Log daily sales\n"
        "/expenses — Recent expense list\n"
        "/report — Monthly P&amp;L\n"
        "/help — This message\n\n"
        "<b>Receipt Processing:</b>\n"
        "Just send any receipt photo — I'll extract items, update stock &amp; log the expense automatically.\n"
    )
    await update.message.reply_text(static, parse_mode=ParseMode.HTML)


async def summary_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    data = await asyncio.to_thread(get_weekly_summary)
    profit = data["weekly_profit"]
    profit_sign = "+" if profit >= 0 else ""

    text = (
        "<b>Weekly Summary (last 7 days)</b>\n\n"
        f"Revenue:    {_money(data['weekly_revenue'])}\n"
        f"Expenses:   {_money(data['weekly_expenses'])}\n"
        f"Net Profit: <b>{profit_sign}{_money(profit)}</b>\n\n"
        f"Receipts processed: {data['receipts_this_week']}\n"
        f"Low stock alerts:   {data['low_stock_count']}\n"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def stock_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    items = await asyncio.to_thread(get_all_stock)
    low = await asyncio.to_thread(get_low_stock_items)
    low_ids = {i.id for i in low}

    if not items:
        await update.message.reply_text("No stock items recorded yet. Upload receipt photos to populate inventory.")
        return

    lines = ["<b>Current Inventory</b>\n"]
    current_cat = None
    for item in items:
        if item.category != current_cat:
            current_cat = item.category
            lines.append(f"\n<b>{current_cat.upper()}</b>")
        alert = " ⚠️ LOW" if item.id in low_ids else ""
        lines.append(f"  {item.item_name}: {float(item.current_quantity):.1f} {item.unit}{alert}")

    if low:
        lines.append(f"\n⚠️ {len(low)} item(s) below minimum threshold")

    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def income_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args
    if not args:
        await update.message.reply_text(
            "Usage: /income &lt;amount&gt; [note]\nExample: /income 1250.50 Saturday lunch rush",
            parse_mode=ParseMode.HTML,
        )
        return

    try:
        amount = float(args[0])
    except ValueError:
        await update.message.reply_text("Invalid amount. Example: /income 1250.50")
        return

    note = " ".join(args[1:]) if len(args) > 1 else None
    today = datetime.date.today()

    await asyncio.to_thread(add_income_entry, today, amount, "daily_sales", note)

    text = (
        f"Income recorded!\n"
        f"Amount: <b>{_money(amount)}</b>\n"
        f"Date: {today}\n"
    )
    if note:
        text += f"Note: {note}\n"
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def expenses_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    expenses = await asyncio.to_thread(get_recent_expenses, 10)
    if not expenses:
        await update.message.reply_text("No expenses recorded yet.")
        return

    lines = ["<b>Last 10 Expenses</b>\n"]
    for exp in expenses:
        lines.append(f"{exp.date} | {exp.category:12} | {_money(float(exp.amount))} | {exp.description or ''}")

    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def report_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    today = datetime.date.today()
    data = await asyncio.to_thread(get_monthly_pl, today.year, today.month)

    month_name = today.strftime("%B %Y")
    profit = data["net_profit"]
    profit_sign = "+" if profit >= 0 else ""

    lines = [f"<b>{month_name} — P&amp;L Report</b>\n"]
    lines.append(f"Revenue:        {_money(data['revenue'])}")
    lines.append(f"Total Expenses: {_money(data['total_expenses'])}")
    lines.append(f"<b>Net Profit:     {profit_sign}{_money(profit)}</b>\n")

    if data["expenses_by_category"]:
        lines.append("<b>Expenses by Category:</b>")
        for cat, amt in sorted(data["expenses_by_category"].items(), key=lambda x: -x[1]):
            lines.append(f"  {cat:15} {_money(amt)}")

    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


# ---------------------------------------------------------------------------
# Photo handler — core receipt processing
# ---------------------------------------------------------------------------

async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = await update.message.reply_text("Processing receipt, please wait...")

    # Download highest-res photo
    photo = update.message.photo[-1]
    tg_file = await context.bot.get_file(photo.file_id)

    image_path = str(Path(RECEIPT_IMAGES_DIR) / f"{photo.file_id}.jpg")
    await tg_file.download_to_drive(image_path)

    try:
        # Parse receipt with claude-sonnet-4-6 (runs in thread — sync SDK)
        parsed, raw_text = await asyncio.to_thread(parse_receipt_image, image_path)

        # Save to DB
        receipt = await asyncio.to_thread(
            save_receipt, parsed, image_path, update.message.message_id
        )

        # Update stock
        await asyncio.to_thread(upsert_stock_from_receipt_items, receipt.items)

        # Reply with formatted summary
        summary = format_receipt_summary(parsed)
        await msg.edit_text(summary, parse_mode=ParseMode.HTML)

    except ValueError as e:
        logger.warning("JSON parse error: %s", e)
        await msg.edit_text(
            "Could not read the receipt. Please try a clearer photo with better lighting."
        )
    except Exception as e:
        logger.error("Receipt processing error: %s", e, exc_info=True)
        await msg.edit_text("An error occurred while processing the receipt. Please try again.")


# ---------------------------------------------------------------------------
# App builder & entrypoint
# ---------------------------------------------------------------------------

def build_application() -> Application:
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("summary", summary_command))
    app.add_handler(CommandHandler("stock", stock_command))
    app.add_handler(CommandHandler("income", income_command))
    app.add_handler(CommandHandler("expenses", expenses_command))
    app.add_handler(CommandHandler("report", report_command))
    app.add_handler(MessageHandler(filters.PHOTO, photo_handler))
    return app


def main() -> None:
    init_db()
    logger.info("Starting Bodega Burger Telegram bot...")
    app = build_application()
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
