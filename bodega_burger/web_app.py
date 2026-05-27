"""
Bodega Burger — FastAPI Web Dashboard
"""
from __future__ import annotations

import asyncio
import datetime
import json as _json
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from database import (
    add_income_entry,
    get_all_stock,
    get_income_entries,
    get_monthly_pl,
    get_receipt_by_id,
    get_receipts,
    get_recent_expenses,
    get_weekly_summary,
    init_db,
    save_receipt,
    update_stock_quantity,
    upsert_stock_from_dicts,
)


# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    await asyncio.to_thread(init_db)
    yield


app = FastAPI(title="Bodega Burger Dashboard", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")
templates.env.filters["tojson"] = lambda v: _json.dumps(v)


# ---------------------------------------------------------------------------
# Base context helper
# ---------------------------------------------------------------------------

async def base_ctx(request: Request, **kwargs) -> dict:
    summary = await asyncio.to_thread(get_weekly_summary)
    return {
        "request": request,
        "low_stock_count": summary["low_stock_count"],
        **kwargs,
    }


# ---------------------------------------------------------------------------
# Page routes
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    summary, receipts = await asyncio.gather(
        asyncio.to_thread(get_weekly_summary),
        asyncio.to_thread(get_receipts, 10),
    )
    ctx = await base_ctx(request)
    ctx.update({
        "summary": summary,
        "recent_receipts": receipts,
        "today": datetime.date.today().isoformat(),
    })
    return templates.TemplateResponse("dashboard.html", ctx)


@app.get("/receipts", response_class=HTMLResponse)
async def receipts_page(
    request: Request,
    page: int = 1,
    category: Optional[str] = None,
    search: Optional[str] = None,
):
    limit = 20
    offset = (page - 1) * limit
    receipts = await asyncio.to_thread(get_receipts, limit, offset, category, search)
    ctx = await base_ctx(request)
    ctx.update({"receipts": receipts, "page": page, "category": category or "", "search": search or ""})
    return templates.TemplateResponse("receipts.html", ctx)


@app.get("/receipts/{receipt_id}", response_class=HTMLResponse)
async def receipt_detail(request: Request, receipt_id: int):
    receipt = await asyncio.to_thread(get_receipt_by_id, receipt_id)
    if not receipt:
        raise HTTPException(status_code=404, detail="Receipt not found")
    ctx = await base_ctx(request)
    ctx["receipt"] = receipt
    return templates.TemplateResponse("receipt_detail.html", ctx)


@app.get("/stock", response_class=HTMLResponse)
async def stock_page(request: Request):
    items = await asyncio.to_thread(get_all_stock)
    ctx = await base_ctx(request)
    ctx["stock_items"] = items
    return templates.TemplateResponse("stock.html", ctx)


@app.get("/income", response_class=HTMLResponse)
async def income_page(request: Request, page: int = 1):
    limit = 30
    offset = (page - 1) * limit
    entries = await asyncio.to_thread(get_income_entries, limit, offset)
    ctx = await base_ctx(request)
    ctx.update({"entries": entries, "page": page, "today": datetime.date.today().isoformat()})
    return templates.TemplateResponse("income.html", ctx)


@app.get("/reports", response_class=HTMLResponse)
async def reports_page(
    request: Request,
    year: Optional[int] = None,
    month: Optional[int] = None,
):
    today = datetime.date.today()
    year = year or today.year
    month = month or today.month
    pl = await asyncio.to_thread(get_monthly_pl, year, month)
    ctx = await base_ctx(request)
    ctx.update({
        "pl": pl,
        "year": year,
        "month": month,
        "month_name": datetime.date(year, month, 1).strftime("%B %Y"),
    })
    return templates.TemplateResponse("reports.html", ctx)


# ---------------------------------------------------------------------------
# Form POST routes
# ---------------------------------------------------------------------------

@app.post("/income/add")
async def add_income_form(
    date: str = Form(...),
    amount: float = Form(...),
    source: str = Form("daily_sales"),
    note: Optional[str] = Form(None),
):
    try:
        date_val = datetime.date.fromisoformat(date)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid date format. Use YYYY-MM-DD.")
    await asyncio.to_thread(add_income_entry, date_val, amount, source, note or None)
    return RedirectResponse(url="/income", status_code=303)


@app.post("/stock/update")
async def update_stock_form(
    item_name: str = Form(...),
    quantity_delta: float = Form(...),
    unit: Optional[str] = Form(None),
):
    # create_if_missing=True so manual entries always work
    await asyncio.to_thread(
        update_stock_quantity, item_name, quantity_delta, unit or None, True
    )
    return RedirectResponse(url="/stock", status_code=303)


# ---------------------------------------------------------------------------
# JSON API
# ---------------------------------------------------------------------------

class IncomePayload(BaseModel):
    date: str
    amount: float
    source: str = "daily_sales"
    note: Optional[str] = None


class StockUpdatePayload(BaseModel):
    item_name: str
    quantity_delta: float
    unit: Optional[str] = None


@app.post("/api/income")
async def api_add_income(payload: IncomePayload):
    try:
        date_val = datetime.date.fromisoformat(payload.date)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid date format. Use YYYY-MM-DD.")
    entry = await asyncio.to_thread(
        add_income_entry, date_val, payload.amount, payload.source, payload.note
    )
    return {"id": entry["id"], "status": "created"}


@app.post("/api/stock/update")
async def api_update_stock(payload: StockUpdatePayload):
    result = await asyncio.to_thread(
        update_stock_quantity, payload.item_name, payload.quantity_delta, payload.unit, True
    )
    return result


@app.get("/api/summary")
async def api_summary():
    return await asyncio.to_thread(get_weekly_summary)


@app.get("/api/reports/monthly")
async def api_monthly_report(year: Optional[int] = None, month: Optional[int] = None):
    today = datetime.date.today()
    return await asyncio.to_thread(get_monthly_pl, year or today.year, month or today.month)
