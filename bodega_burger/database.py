from __future__ import annotations

import datetime
from contextlib import contextmanager
from typing import Generator, Optional

from sqlalchemy import (
    Column, Date, DateTime, ForeignKey, Integer, Numeric, String, Text,
    create_engine, func, text
)
from sqlalchemy.orm import DeclarativeBase, Session, joinedload, relationship, sessionmaker

from config import DATABASE_URL

# Timezone-aware UTC helper (replaces deprecated datetime.utcnow)
_utcnow = lambda: datetime.datetime.now(datetime.timezone.utc)


class Base(DeclarativeBase):
    pass


class Receipt(Base):
    __tablename__ = "receipts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    telegram_msg_id = Column(Integer, nullable=True)   # no unique — multiple NULLs allowed cleanly
    image_path = Column(Text, nullable=True)
    vendor = Column(String(255), nullable=False)
    date = Column(Date, nullable=False)
    total = Column(Numeric(10, 2), nullable=False)
    tax = Column(Numeric(10, 2), default=0.0)
    category = Column(String(50), nullable=False)  # food/beverage/supplies/utilities/other
    processed_at = Column(DateTime, default=_utcnow)
    raw_text = Column(Text, nullable=True)

    items = relationship(
        "ReceiptItem",
        back_populates="receipt",
        cascade="all, delete-orphan",
        lazy="joined",   # always load items with receipt
    )
    expense = relationship("Expense", back_populates="receipt", uselist=False)


class ReceiptItem(Base):
    __tablename__ = "receipt_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    receipt_id = Column(Integer, ForeignKey("receipts.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(255), nullable=False)
    quantity = Column(Numeric(10, 3), nullable=False)
    unit_price = Column(Numeric(10, 2), nullable=False)
    total_price = Column(Numeric(10, 2), nullable=False)
    stock_category = Column(String(50), nullable=False)  # meat/bread/produce/dairy/supplies/beverages/other

    receipt = relationship("Receipt", back_populates="items")


class Stock(Base):
    __tablename__ = "stock"

    id = Column(Integer, primary_key=True, autoincrement=True)
    item_name = Column(String(255), unique=True, nullable=False)
    category = Column(String(50), nullable=False)
    current_quantity = Column(Numeric(10, 3), default=0.0)
    unit = Column(String(20), default="units")
    last_updated = Column(DateTime, default=_utcnow)
    min_threshold = Column(Numeric(10, 3), default=0.0)


class IncomeEntry(Base):
    __tablename__ = "income_entries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(Date, nullable=False)
    amount = Column(Numeric(10, 2), nullable=False)
    source = Column(String(50), default="daily_sales")  # daily_sales/catering/other
    note = Column(Text, nullable=True)
    created_at = Column(DateTime, default=_utcnow)


class Expense(Base):
    __tablename__ = "expenses"

    id = Column(Integer, primary_key=True, autoincrement=True)
    receipt_id = Column(Integer, ForeignKey("receipts.id", ondelete="SET NULL"), nullable=True)
    date = Column(Date, nullable=False)
    amount = Column(Numeric(10, 2), nullable=False)
    category = Column(String(50), nullable=False)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=_utcnow)

    receipt = relationship("Receipt", back_populates="expense")


# ---------------------------------------------------------------------------
# Engine & Session factory
# ---------------------------------------------------------------------------

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
    echo=False,
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
    expire_on_commit=False,  # objects remain usable after session closes
)


def init_db() -> None:
    """Create all tables and apply SQLite pragmas."""
    with engine.connect() as conn:
        conn.execute(text("PRAGMA journal_mode=WAL"))
        conn.execute(text("PRAGMA foreign_keys=ON"))
        conn.commit()
    Base.metadata.create_all(bind=engine)


@contextmanager
def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VALID_STOCK_CATEGORIES = {"meat", "bread", "produce", "dairy", "supplies", "beverages", "other"}
VALID_RECEIPT_CATEGORIES = {"food", "beverage", "supplies", "utilities", "other"}


def _norm_stock_cat(cat: Optional[str]) -> str:
    return cat.lower() if cat and cat.lower() in VALID_STOCK_CATEGORIES else "other"


def _norm_receipt_cat(cat: Optional[str]) -> str:
    return cat.lower() if cat and cat.lower() in VALID_RECEIPT_CATEGORIES else "other"


# ---------------------------------------------------------------------------
# CRUD helpers
# ---------------------------------------------------------------------------

def save_receipt(
    parsed: dict,
    image_path: Optional[str],
    telegram_msg_id: Optional[int],
) -> Receipt:
    """Persist a parsed receipt and create a linked expense row.
    Returns a Receipt with items already loaded (safe to use after session closes).
    """
    import dateutil.parser as dp

    with get_db() as db:
        date_val = datetime.date.today()
        try:
            if parsed.get("date"):
                date_val = dp.parse(str(parsed["date"])).date()
        except Exception:
            pass

        # Validate total — reject $0 receipts only if no items either
        total = float(parsed.get("total") or 0)
        items_data = parsed.get("items") or []

        receipt = Receipt(
            telegram_msg_id=telegram_msg_id,
            image_path=image_path,
            vendor=parsed.get("vendor") or "Unknown",
            date=date_val,
            total=total,
            tax=float(parsed.get("tax") or 0),
            category=_norm_receipt_cat(parsed.get("category")),
            raw_text=parsed.get("raw_text"),
        )
        db.add(receipt)
        db.flush()  # get receipt.id

        for item_data in items_data:
            item = ReceiptItem(
                receipt_id=receipt.id,
                name=item_data.get("name") or "Unknown item",
                quantity=float(item_data.get("quantity") or 1),
                unit_price=float(item_data.get("unit_price") or 0),
                total_price=float(item_data.get("total_price") or 0),
                stock_category=_norm_stock_cat(item_data.get("stock_category")),
            )
            db.add(item)

        expense = Expense(
            receipt_id=receipt.id,
            date=date_val,
            amount=total,
            category=_norm_receipt_cat(parsed.get("category")),
            description=f"Receipt from {receipt.vendor}",
        )
        db.add(expense)
        db.flush()

        # Force-load items while session is still open
        db.refresh(receipt)
        # Access items to trigger join-loaded population
        _ = receipt.items

        return receipt


def upsert_stock_from_receipt_items(items: list) -> None:
    """Add receipt item quantities to stock; create entry if missing."""
    with get_db() as db:
        for item in items:
            key = item.name.strip().lower()
            existing = db.query(Stock).filter(Stock.item_name == key).first()
            if existing:
                existing.current_quantity = float(existing.current_quantity) + float(item.quantity)
                existing.last_updated = _utcnow()
            else:
                db.add(Stock(
                    item_name=key,
                    category=item.stock_category,
                    current_quantity=float(item.quantity),
                    unit="units",
                    min_threshold=0.0,
                ))


def get_receipts(
    limit: int = 50,
    offset: int = 0,
    category: Optional[str] = None,
    search: Optional[str] = None,
) -> list[Receipt]:
    with get_db() as db:
        q = db.query(Receipt).order_by(Receipt.date.desc(), Receipt.processed_at.desc())
        if category:
            q = q.filter(Receipt.category == category)
        if search:
            q = q.filter(Receipt.vendor.ilike(f"%{search}%"))
        return q.offset(offset).limit(limit).all()


def get_receipt_by_id(receipt_id: int) -> Optional[Receipt]:
    with get_db() as db:
        return (
            db.query(Receipt)
            .options(joinedload(Receipt.items))
            .filter(Receipt.id == receipt_id)
            .first()
        )


def get_all_stock() -> list[Stock]:
    with get_db() as db:
        return db.query(Stock).order_by(Stock.category, Stock.item_name).all()


def get_low_stock_items() -> list[Stock]:
    with get_db() as db:
        return db.query(Stock).filter(
            Stock.current_quantity <= Stock.min_threshold,
            Stock.min_threshold > 0,
        ).all()


def add_income_entry(
    date: datetime.date,
    amount: float,
    source: str = "daily_sales",
    note: Optional[str] = None,
) -> IncomeEntry:
    with get_db() as db:
        entry = IncomeEntry(date=date, amount=amount, source=source, note=note)
        db.add(entry)
        db.flush()
        db.refresh(entry)
        return entry


def get_income_entries(limit: int = 50, offset: int = 0) -> list[IncomeEntry]:
    with get_db() as db:
        return (
            db.query(IncomeEntry)
            .order_by(IncomeEntry.date.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )


def get_weekly_summary() -> dict:
    """Revenue, expenses and profit for the last 7 days."""
    today = datetime.date.today()
    week_ago = today - datetime.timedelta(days=7)

    with get_db() as db:
        revenue = db.query(func.coalesce(func.sum(IncomeEntry.amount), 0)).filter(
            IncomeEntry.date >= week_ago
        ).scalar()

        expenses = db.query(func.coalesce(func.sum(Expense.amount), 0)).filter(
            Expense.date >= week_ago
        ).scalar()

        receipts_count = db.query(func.count(Receipt.id)).filter(
            Receipt.date >= week_ago
        ).scalar()

        low_stock = db.query(func.count(Stock.id)).filter(
            Stock.current_quantity <= Stock.min_threshold,
            Stock.min_threshold > 0,
        ).scalar()

    return {
        "weekly_revenue": float(revenue),
        "weekly_expenses": float(expenses),
        "weekly_profit": float(revenue) - float(expenses),
        "receipts_this_week": int(receipts_count),
        "low_stock_count": int(low_stock),
    }


def get_monthly_pl(year: int, month: int) -> dict:
    """P&L breakdown for a given month."""
    from calendar import monthrange
    first = datetime.date(year, month, 1)
    last = datetime.date(year, month, monthrange(year, month)[1])

    with get_db() as db:
        revenue = db.query(func.coalesce(func.sum(IncomeEntry.amount), 0)).filter(
            IncomeEntry.date >= first, IncomeEntry.date <= last
        ).scalar()

        expense_rows = db.query(
            Expense.category,
            func.sum(Expense.amount).label("total"),
        ).filter(
            Expense.date >= first, Expense.date <= last
        ).group_by(Expense.category).all()

        total_expenses = sum(float(r.total) for r in expense_rows)

    return {
        "year": year,
        "month": month,
        "revenue": float(revenue),
        "expenses_by_category": {r.category: float(r.total) for r in expense_rows},
        "total_expenses": total_expenses,
        "net_profit": float(revenue) - total_expenses,
    }


def update_stock_quantity(
    item_name: str,
    quantity_delta: float,
    unit: Optional[str] = None,
) -> Optional[dict]:
    """Adjust stock level. Returns plain dict (safe after session close)."""
    key = item_name.strip().lower()
    with get_db() as db:
        item = db.query(Stock).filter(Stock.item_name == key).first()
        if not item:
            return None
        item.current_quantity = float(item.current_quantity) + quantity_delta
        item.last_updated = _utcnow()
        if unit:
            item.unit = unit
        db.flush()
        # Return plain dict — no detached-object risk
        return {
            "id": item.id,
            "item_name": item.item_name,
            "current_quantity": float(item.current_quantity),
            "unit": item.unit,
        }


def get_recent_expenses(limit: int = 10) -> list[Expense]:
    with get_db() as db:
        return db.query(Expense).order_by(Expense.date.desc()).limit(limit).all()
