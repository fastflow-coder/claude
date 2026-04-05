"""
Bodega Burger — FastAPI Web Dashboard
"""
from __future__ import annotations

import datetime
from typing import Optional

from fastapi import Depends, FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy.orm import Session

import database as db
from database import (
    SessionLocal,
    add_income_entry,
    get_all_stock,
    get_income_entries,
    get_low_stock_items,
    get_monthly_pl,
    get_receipt_by_id,
    get_receipts,
    get_recent_expenses,
    get_weekly_summary,
    init_db,
    update_stock_quantity,
)

app = FastAPI(title="Bodega Burger Dashboard")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

@app.on_event("startup")
async def startup_event():
    init_db()


# ---------------------------------------------------------------------------
# Template helper — inject common data
# ---------------------------------------------------------------------------

def base_ctx(request: Request, **kwargs) -> dict:
    summary = get_weekly_summary()
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
    summary = get_weekly_summary()
    receipts = get_receipts(limit=10)
    return templates.TemplateResponse("dashboard.html", {
        **base_ctx(request),
        "summary": summary,
        "recent_receipts": receipts,
    })


@app.get("/receipts", response_class=HTMLResponse)
async def receipts_page(
    request: Request,
    page: int = 1,
    category: Optional[str] = None,
    search: Optional[str] = None,
):
    limit = 20
    offset = (page - 1) * limit
    receipts = get_receipts(limit=limit, offset=offset, category=category, search=search)
    return templates.TemplateResponse("receipts.html", {
        **base_ctx(request),
        "receipts": receipts,
        "page": page,
        "category": category or "",
        "search": search or "",
    })


@app.get("/receipts/{receipt_id}", response_class=HTMLResponse)
async def receipt_detail(request: Request, receipt_id: int):
    receipt = get_receipt_by_id(receipt_id)
    if not receipt:
        raise HTTPException(status_code=404, detail="Receipt not found")
    return templates.TemplateResponse("receipt_detail.html", {
        **base_ctx(request),
        "receipt": receipt,
    })


@app.get("/stock", response_class=HTMLResponse)
async def stock_page(request: Request):
    items = get_all_stock()
    low_items = {i.id for i in get_low_stock_items()}
    return templates.TemplateResponse("stock.html", {
        **base_ctx(request),
        "stock_items": items,
        "low_ids": low_items,
    })


@app.get("/income", response_class=HTMLResponse)
async def income_page(request: Request, page: int = 1):
    limit = 30
    offset = (page - 1) * limit
    entries = get_income_entries(limit=limit, offset=offset)
    return templates.TemplateResponse("income.html", {
        **base_ctx(request),
        "entries": entries,
        "page": page,
    })


@app.get("/reports", response_class=HTMLResponse)
async def reports_page(request: Request, year: Optional[int] = None, month: Optional[int] = None):
    today = datetime.date.today()
    year = year or today.year
    month = month or today.month
    pl = get_monthly_pl(year, month)
    return templates.TemplateResponse("reports.html", {
        **base_ctx(request),
        "pl": pl,
        "year": year,
        "month": month,
        "month_name": datetime.date(year, month, 1).strftime("%B %Y"),
    })


# ---------------------------------------------------------------------------
# Form POST routes (used by web UI forms)
# ---------------------------------------------------------------------------

@app.post("/income/add")
async def add_income_form(
    request: Request,
    date: str = Form(...),
    amount: float = Form(...),
    source: str = Form("daily_sales"),
    note: str = Form(""),
):
    date_val = datetime.date.fromisoformat(date)
    add_income_entry(date_val, amount, source, note or None)
    return RedirectResponse(url="/income", status_code=303)


@app.post("/stock/update")
async def update_stock_form(
    request: Request,
    item_name: str = Form(...),
    quantity_delta: float = Form(...),
    unit: str = Form(""),
):
    update_stock_quantity(item_name, quantity_delta, unit or None)
    return RedirectResponse(url="/stock", status_code=303)


# ---------------------------------------------------------------------------
# JSON API endpoints
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
    date_val = datetime.date.fromisoformat(payload.date)
    entry = add_income_entry(date_val, payload.amount, payload.source, payload.note)
    return {"id": entry.id, "status": "created"}


@app.post("/api/stock/update")
async def api_update_stock(payload: StockUpdatePayload):
    item = update_stock_quantity(payload.item_name, payload.quantity_delta, payload.unit)
    if not item:
        raise HTTPException(status_code=404, detail="Stock item not found")
    return {
        "id": item.id,
        "item_name": item.item_name,
        "current_quantity": float(item.current_quantity),
    }


@app.get("/api/summary")
async def api_summary():
    return get_weekly_summary()


@app.get("/api/reports/monthly")
async def api_monthly_report(year: Optional[int] = None, month: Optional[int] = None):
    today = datetime.date.today()
    return get_monthly_pl(year or today.year, month or today.month)
