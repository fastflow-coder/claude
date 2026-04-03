"""
SQLite persistence + CSV / JSON / XLSX export.

Schema
------
businesses      — one row per unique business (deduped by content_hash)
scrape_sessions — one row per completed query (for resume support)
"""

import csv
import json
import sqlite3
from pathlib import Path

DB_PATH = Path("output/leads.db")


# ---------------------------------------------------------------------------
# Init
# ---------------------------------------------------------------------------


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = _connect()
    con.executescript("""
        CREATE TABLE IF NOT EXISTS businesses (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            content_hash      TEXT UNIQUE,
            name              TEXT NOT NULL,
            address           TEXT,
            phone             TEXT,
            phone_raw         TEXT,
            email             TEXT,
            website           TEXT,
            category          TEXT,
            rating            REAL,
            review_count      INTEGER,
            maps_url          TEXT,
            query             TEXT,
            has_website       INTEGER DEFAULT 0,
            website_reachable INTEGER,
            website_score     INTEGER,
            analysis_json     TEXT,
            scrape_state      TEXT DEFAULT 'scraped',
            scraped_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            analyzed_at       TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS scrape_sessions (
            query         TEXT PRIMARY KEY,
            results_count INTEGER,
            completed_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    con.commit()
    con.close()


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------


def save_businesses(rows: list[dict]) -> int:
    """
    Insert rows, skipping duplicates (by content_hash).
    Returns number of newly inserted rows.
    """
    if not rows:
        return 0
    con = _connect()
    inserted = 0
    for r in rows:
        try:
            con.execute(
                """
                INSERT OR IGNORE INTO businesses
                    (content_hash, name, address, phone, phone_raw,
                     website, category, rating, review_count,
                     maps_url, query, has_website)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    r.get("content_hash"),
                    r["name"],
                    r.get("address", ""),
                    r.get("phone", ""),
                    r.get("phone_raw", ""),
                    r.get("website", ""),
                    r.get("category", ""),
                    r.get("rating"),
                    r.get("review_count"),
                    r.get("maps_url", ""),
                    r.get("query", ""),
                    1 if r.get("website") else 0,
                ),
            )
            if con.execute("SELECT changes()").fetchone()[0]:
                inserted += 1
        except sqlite3.Error:
            continue
    con.commit()
    con.close()
    return inserted


def mark_session_complete(query: str, count: int) -> None:
    con = _connect()
    con.execute(
        "INSERT OR REPLACE INTO scrape_sessions (query, results_count) VALUES (?,?)",
        (query, count),
    )
    con.commit()
    con.close()


def is_session_complete(query: str) -> bool:
    con = _connect()
    row = con.execute(
        "SELECT 1 FROM scrape_sessions WHERE query = ?", (query,)
    ).fetchone()
    con.close()
    return row is not None


def update_analysis(biz_id: int, email: str, score_data: dict) -> None:
    con = _connect()
    con.execute(
        """
        UPDATE businesses SET
            email             = ?,
            website_reachable = ?,
            website_score     = ?,
            analysis_json     = ?,
            scrape_state      = 'analyzed',
            analyzed_at       = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (
            email,
            1 if score_data.get("reachable") else 0,
            score_data.get("score"),
            json.dumps(score_data, ensure_ascii=False),
            biz_id,
        ),
    )
    con.commit()
    con.close()


# ---------------------------------------------------------------------------
# Exports
# ---------------------------------------------------------------------------

_EXPORT_COLS = [
    "id", "name", "address", "phone", "email",
    "website", "category", "rating", "review_count",
    "has_website", "website_score", "analysis_json",
    "query", "scrape_state", "scraped_at",
]


def export_csv(output_path: str = "output/export.csv") -> int:
    rows, headers = _fetch_all()
    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(rows)
    return len(rows)


def export_json(output_path: str = "output/export.json") -> int:
    rows, headers = _fetch_all()
    data = [dict(zip(headers, r)) for r in rows]
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return len(rows)


def export_xlsx(output_path: str = "output/export.xlsx") -> int:
    import openpyxl

    rows, headers = _fetch_all()
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Leads"
    ws.append(headers)
    for row in rows:
        ws.append(list(row))
    wb.save(output_path)
    return len(rows)


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _connect() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def _fetch_all() -> tuple[list, list[str]]:
    con = _connect()
    cur = con.execute(f"SELECT {', '.join(_EXPORT_COLS)} FROM businesses ORDER BY id")
    headers = [d[0] for d in cur.description]
    rows = cur.fetchall()
    con.close()
    return rows, headers
