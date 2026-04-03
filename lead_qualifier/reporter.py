"""
Priority lead report generation.

Exports CSV, XLSX, JSON and prints a Rich summary table.
"""

import csv
import json

import openpyxl
from rich.console import Console
from rich.table import Table

from lead_qualifier.config import (
    PRIORITY_CSV,
    PRIORITY_JSON,
    PRIORITY_SCORE_THRESHOLD,
    PRIORITY_XLSX,
)
from lead_qualifier.segmenter import get_priority_leads

console = Console()

_HEADERS = [
    "İşletme", "Telefon", "E-posta", "Website", "Adres",
    "Kategori", "Puan", "Öncelik", "Sorunlar", "Satış Argümanı",
    "Rating", "Yorum Sayısı", "Maps URL",
]


def generate_reports() -> int:
    """Write all three export formats and print a summary table."""
    leads = get_priority_leads(PRIORITY_SCORE_THRESHOLD)
    rows = [_flatten(lead) for lead in leads]

    _write_csv(rows)
    _write_xlsx(rows)
    _write_json(leads)
    _print_table(rows[:30])  # show at most 30 in terminal

    return len(rows)


# ---------------------------------------------------------------------------
# Export helpers
# ---------------------------------------------------------------------------


def _write_csv(rows: list[list]) -> None:
    with open(PRIORITY_CSV, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(_HEADERS)
        w.writerows(rows)


def _write_xlsx(rows: list[list]) -> None:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Priority Leads"
    ws.append(_HEADERS)
    for row in rows:
        ws.append(row)
    # Auto-width columns
    for col in ws.columns:
        max_len = max((len(str(cell.value or "")) for cell in col), default=0)
        ws.column_dimensions[col[0].column_letter].width = min(max_len + 2, 60)
    wb.save(PRIORITY_XLSX)


def _write_json(leads: list[dict]) -> None:
    # Strip raw HTML snippets to keep JSON readable
    clean = []
    for lead in leads:
        d = dict(lead)
        analysis = {}
        if d.get("analysis_json"):
            try:
                analysis = json.loads(d["analysis_json"])
                analysis.pop("html_snippet", None)
            except Exception:
                pass
        d["analysis"] = analysis
        d.pop("analysis_json", None)
        clean.append(d)
    with open(PRIORITY_JSON, "w", encoding="utf-8") as f:
        json.dump(clean, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Rich terminal table
# ---------------------------------------------------------------------------


def _print_table(rows: list[list]) -> None:
    table = Table(
        title=f"Top {len(rows)} Priority Leads",
        show_header=True,
        header_style="bold magenta",
        show_lines=True,
    )
    short_headers = ["İşletme", "Telefon", "E-posta", "Puan", "Öncelik", "Sorunlar"]
    for h in short_headers:
        table.add_column(h, overflow="fold", max_width=35)

    for row in rows:
        name, phone, email = str(row[0]), str(row[1]), str(row[2])
        score = str(row[6]) if row[6] is not None else "N/A"
        priority = str(row[7]) if row[7] else "—"
        issues = str(row[8])[:60] if row[8] else "—"

        color = {"HIGH": "red", "MEDIUM": "yellow", "LOW": "green"}.get(priority, "white")
        table.add_row(name, phone, email, score, f"[{color}]{priority}[/{color}]", issues)

    console.print(table)


# ---------------------------------------------------------------------------
# Flatten a DB row into an ordered list matching _HEADERS
# ---------------------------------------------------------------------------


def _flatten(lead: dict) -> list:
    analysis: dict = {}
    if lead.get("analysis_json"):
        try:
            analysis = json.loads(lead["analysis_json"])
        except Exception:
            pass

    return [
        lead.get("name", ""),
        lead.get("phone", ""),
        lead.get("email", ""),
        lead.get("website", "YOK"),
        lead.get("address", ""),
        lead.get("category", ""),
        lead.get("website_score"),
        analysis.get("priority", "HIGH" if not lead.get("has_website") else ""),
        " | ".join(analysis.get("main_issues", [])),
        analysis.get("sales_pitch", "Web sitesi yok — birinci öncelik."),
        lead.get("rating"),
        lead.get("review_count"),
        lead.get("maps_url", ""),
    ]
