"""
DB queries that split the business list into segments for the qualifier.
"""

import sqlite3
from pathlib import Path

from lead_qualifier.config import DB_PATH


def _connect() -> sqlite3.Connection:
    if not Path(DB_PATH).exists():
        raise FileNotFoundError(
            f"Database not found at {DB_PATH!r}. "
            "Run maps_scraper/main.py first."
        )
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def _rows_to_dicts(rows) -> list[dict]:
    return [dict(r) for r in rows]


def get_no_website() -> list[dict]:
    """Businesses with no website → immediate HIGH priority leads."""
    con = _connect()
    rows = con.execute(
        "SELECT * FROM businesses WHERE has_website = 0 ORDER BY rating DESC NULLS LAST"
    ).fetchall()
    con.close()
    return _rows_to_dicts(rows)


def get_unanalyzed_with_website() -> list[dict]:
    """Businesses with a website that haven't been scored yet."""
    con = _connect()
    rows = con.execute(
        """
        SELECT * FROM businesses
        WHERE has_website = 1
          AND (website_score IS NULL OR scrape_state != 'analyzed')
        ORDER BY id
        """
    ).fetchall()
    con.close()
    return _rows_to_dicts(rows)


def get_priority_leads(score_threshold: int) -> list[dict]:
    """
    Returns businesses that are either:
    - no website (NULL score) → ordered first
    - website_score >= threshold → ordered by score desc
    """
    con = _connect()
    rows = con.execute(
        """
        SELECT
            name, phone, email, website, address,
            category, rating, review_count,
            has_website, website_score, analysis_json, maps_url
        FROM businesses
        WHERE has_website = 0
           OR website_score >= ?
        ORDER BY
            has_website ASC,          -- no-website first
            website_score DESC NULLS LAST,
            rating DESC NULLS LAST
        """,
        (score_threshold,),
    ).fetchall()
    con.close()
    return _rows_to_dicts(rows)
