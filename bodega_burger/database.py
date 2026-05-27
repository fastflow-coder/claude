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
    telegram_msg_id = Column(Integer, nullable=True)
    image_path = Column(Text, nullable=True)
    vendor = Column(String(255), nullable=False)
    date = Column(Date, nullable=False)
    total = Column(Numeric(10, 2), nullable=False)
    tax = Column(Numeric(10, 2), default=0.0)
    category = Column(String(50), nullable=False)
    processed_at = Column(DateTime, default=_utcnow)
    raw_text = Column(Text, nullable=True)

    items = relationship(
        "ReceiptItem",
        back_populates="receipt",
        cascade="all, delete-orphan",
        lazy="joined",
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
    stock_category = Column(String(50), nullable=False)

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
    source = Column(String(50), default="daily_sales")
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
    expire_on_commit=False,
)


def init_db() -> None:
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
# Constants & helpers
# ---------------------------------------------------------------------------

VALID_STOCK_CATEGORIES = {"meat", "bread", "produce", "dairy", "supplies", "beverages", "other"}
VALID_RECEIPT_CATEGORIES = {"food", "beverage", "supplies", "utilities", "other"}


def _norm_stock_cat(cat: Optional[str]) -> str:
    return cat.lower() if cat and cat.lower() in VALID_STOCK_CATEGORIES else "other"


def _norm_receipt_cat(cat: Optional[str]) -> str:
    return cat.lower() if cat and cat.lower() in VALID_RECEIPT_CATEGORIES else "other"


def _upsert_stock_in_session(db: Session, name: str, category: str, quantity: float) -> None:
    """Add quantity to existing stock item or create a new one. Runs inside caller's session."""
    key = name.strip().lower()
    existing = db.query(Stock).filter(Stock.item_name == key).first()
    if existing:
        existing.current_quantity = float(existing.current_quantity) + quantity
        existing.last_updated = _utcnow()
    else:
        db.add(Stock(
            item_name=key,
            category=category,
            current_quantity=quantity,
            unit="units",
            min_threshold=0.0,
        ))


# ---------------------------------------------------------------------------
# Core: save receipt + update stock in ONE transaction
# ---------------------------------------------------------------------------

def save_receipt(
    parsed: dict,
    image_path: Optional[str],
    telegram_msg_id: Optional[int],
) -> dict:
    """
    Persist a parsed receipt, its items, a linked expense, and update stock —
    all inside a single DB transaction. Returns a plain dict (safe across
    threads and sessions):
      {
        "receipt_id": int,
        "vendor": str,
        "date": str,
        "total": float,
        "category": str,
        "items": [{"name", "quantity", "unit_price", "total_price", "stock_category"}, ...],
        "stock_updated": int,   # number of stock rows touched
      }
    """
    import dateutil.parser as dp

    with get_db() as db:
        # --- date ---
        date_val = datetime.date.today()
        try:
            if parsed.get("date"):
                date_val = dp.parse(str(parsed["date"])).date()
        except Exception:
            pass

        total = float(parsed.get("total") or 0)
        items_data = parsed.get("items") or []

        # --- receipt row ---
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
        db.flush()  # assigns receipt.id

        # --- item rows + stock update (same session!) ---
        items_out = []
        stock_updated = 0
        for item_data in items_data:
            name = item_data.get("name") or "Unknown item"
            qty = float(item_data.get("quantity") or 1)
            u_price = float(item_data.get("unit_price") or 0)
            t_price = float(item_data.get("total_price") or 0)
            s_cat = _norm_stock_cat(item_data.get("stock_category"))

            db.add(ReceiptItem(
                receipt_id=receipt.id,
                name=name,
                quantity=qty,
                unit_price=u_price,
                total_price=t_price,
                stock_category=s_cat,
            ))

            # Stock update — SAME session, zero cross-session risk
            _upsert_stock_in_session(db, name, s_cat, qty)
            stock_updated += 1

            items_out.append({
                "name": name,
                "quantity": qty,
                "unit_price": u_price,
                "total_price": t_price,
                "stock_category": s_cat,
            })

        # --- expense row ---
        db.add(Expense(
            receipt_id=receipt.id,
            date=date_val,
            amount=total,
            category=_norm_receipt_cat(parsed.get("category")),
            description=f"Receipt from {receipt.vendor}",
        ))

        # Collect plain-dict result before session closes
        result = {
            "receipt_id": receipt.id,
            "vendor": receipt.vendor,
            "date": str(date_val),
            "total": total,
            "category": receipt.category,
            "items": items_out,
            "stock_updated": stock_updated,
        }

    return result  # session already closed — plain dict is 100% safe


# ---------------------------------------------------------------------------
# Stock helpers
# ---------------------------------------------------------------------------

def upsert_stock_from_dicts(items: list[dict]) -> int:
    """
    Standalone stock update from a list of plain dicts
    (each must have 'name', 'quantity', 'stock_category').
    Returns number of stock rows touched.
    """
    count = 0
    with get_db() as db:
        for item in items:
            _upsert_stock_in_session(
                db,
                item["name"],
                item.get("stock_category", "other"),
                float(item.get("quantity", 1)),
            )
            count += 1
    return count


def get_all_stock() -> list[dict]:
    """Return all stock rows as plain dicts."""
    with get_db() as db:
        rows = db.query(Stock).order_by(Stock.category, Stock.item_name).all()
        return [
            {
                "id": r.id,
                "item_name": r.item_name,
                "category": r.category,
                "current_quantity": float(r.current_quantity),
                "unit": r.unit,
                "min_threshold": float(r.min_threshold),
                "last_updated": r.last_updated,
                "is_low": float(r.current_quantity) <= float(r.min_threshold) and float(r.min_threshold) > 0,
            }
            for r in rows
        ]


def get_low_stock_count() -> int:
    with get_db() as db:
        return db.query(func.count(Stock.id)).filter(
            Stock.current_quantity <= Stock.min_threshold,
            Stock.min_threshold > 0,
        ).scalar()


# ---------------------------------------------------------------------------
# Receipts
# ---------------------------------------------------------------------------

def get_receipts(
    limit: int = 50,
    offset: int = 0,
    category: Optional[str] = None,
    search: Optional[str] = None,
) -> list[dict]:
    with get_db() as db:
        q = db.query(Receipt).options(joinedload(Receipt.items)).order_by(
            Receipt.date.desc(), Receipt.processed_at.desc()
        )
        if category:
            q = q.filter(Receipt.category == category)
        if search:
            q = q.filter(Receipt.vendor.ilike(f"%{search}%"))
        rows = q.offset(offset).limit(limit).all()
        return [_receipt_to_dict(r) for r in rows]


def get_receipt_by_id(receipt_id: int) -> Optional[dict]:
    with get_db() as db:
        r = (
            db.query(Receipt)
            .options(joinedload(Receipt.items))
            .filter(Receipt.id == receipt_id)
            .first()
        )
        return _receipt_to_dict(r) if r else None


def _receipt_to_dict(r: Receipt) -> dict:
    return {
        "id": r.id,
        "vendor": r.vendor,
        "date": r.date,
        "total": float(r.total),
        "tax": float(r.tax or 0),
        "category": r.category,
        "processed_at": r.processed_at,
        "raw_text": r.raw_text,
        "image_path": r.image_path,
        "items": [
            {
                "id": i.id,
                "name": i.name,
                "quantity": float(i.quantity),
                "unit_price": float(i.unit_price),
                "total_price": float(i.total_price),
                "stock_category": i.stock_category,
            }
            for i in (r.items or [])
        ],
    }


# ---------------------------------------------------------------------------
# Income
# ---------------------------------------------------------------------------

def add_income_entry(
    date: datetime.date,
    amount: float,
    source: str = "daily_sales",
    note: Optional[str] = None,
) -> dict:
    with get_db() as db:
        entry = IncomeEntry(date=date, amount=amount, source=source, note=note)
        db.add(entry)
        db.flush()
        return {"id": entry.id, "date": str(date), "amount": amount, "source": source, "note": note}


def get_income_entries(limit: int = 50, offset: int = 0) -> list[dict]:
    with get_db() as db:
        rows = (
            db.query(IncomeEntry)
            .order_by(IncomeEntry.date.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        return [
            {
                "id": r.id,
                "date": r.date,
                "amount": float(r.amount),
                "source": r.source,
                "note": r.note,
                "created_at": r.created_at,
            }
            for r in rows
        ]


# ---------------------------------------------------------------------------
# Expenses
# ---------------------------------------------------------------------------

def get_recent_expenses(limit: int = 10) -> list[dict]:
    with get_db() as db:
        rows = db.query(Expense).order_by(Expense.date.desc()).limit(limit).all()
        return [
            {
                "id": r.id,
                "date": r.date,
                "amount": float(r.amount),
                "category": r.category,
                "description": r.description,
            }
            for r in rows
        ]


# ---------------------------------------------------------------------------
# Summary / Reports
# ---------------------------------------------------------------------------

def get_weekly_summary() -> dict:
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
    create_if_missing: bool = False,
) -> Optional[dict]:
    """Adjust stock quantity. Returns updated dict or None if not found."""
    key = item_name.strip().lower()
    with get_db() as db:
        item = db.query(Stock).filter(Stock.item_name == key).first()
        if not item:
            if not create_if_missing:
                return None
            # Create new stock item
            item = Stock(
                item_name=key,
                category="other",
                current_quantity=max(0.0, quantity_delta),
                unit=unit or "units",
                min_threshold=0.0,
            )
            db.add(item)
            db.flush()
        else:
            item.current_quantity = float(item.current_quantity) + quantity_delta
            item.last_updated = _utcnow()
            if unit:
                item.unit = unit
            db.flush()

        return {
            "id": item.id,
            "item_name": item.item_name,
            "current_quantity": float(item.current_quantity),
            "unit": item.unit,
        }
