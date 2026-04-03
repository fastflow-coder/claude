"""
maps_scraper entry point.

Usage:
    python -m maps_scraper.main
    # or from repo root:
    python maps_scraper/main.py
"""

import asyncio
import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table

from maps_scraper import config
from maps_scraper.scraper import scrape_query
from maps_scraper.storage import (
    export_csv,
    export_json,
    export_xlsx,
    init_db,
    is_session_complete,
    mark_session_complete,
    save_businesses,
)

console = Console()


async def main() -> None:
    init_db()
    total_new = 0

    console.rule("[bold green]Google Maps Lead Scraper")

    for query in config.SEARCH_QUERIES:
        if is_session_complete(query):
            console.print(f"[dim]Skipping (already done): {query}[/dim]")
            continue

        console.print(f"\n[bold cyan]Searching:[/bold cyan] {query}")

        results = await scrape_query(query)
        new_count = save_businesses(results)
        mark_session_complete(query, len(results))
        total_new += new_count

        console.print(
            f"  [green]Found {len(results)} businesses, "
            f"{new_count} new (deduped)[/green]"
        )

        if query != config.SEARCH_QUERIES[-1]:
            console.print(
                f"  [dim]Waiting {config.INTER_QUERY_DELAY_S}s before next query…[/dim]"
            )
            await asyncio.sleep(config.INTER_QUERY_DELAY_S)

    # Export all formats
    console.rule("[bold green]Exporting")
    n_csv = export_csv()
    n_json = export_json()
    n_xlsx = export_xlsx()

    _print_summary(total_new, n_csv)


def _print_summary(new: int, total: int) -> None:
    table = Table(title="Export Summary", show_header=True, header_style="bold magenta")
    table.add_column("File", style="cyan")
    table.add_column("Records", justify="right")
    table.add_row("output/export.csv", str(total))
    table.add_row("output/export.json", str(total))
    table.add_row("output/export.xlsx", str(total))
    table.add_row("[bold]New this run[/bold]", f"[bold green]{new}[/bold green]")
    console.print(table)
    console.print("\nNext step: [bold]python lead_qualifier/main.py[/bold]")


if __name__ == "__main__":
    # Allow running from repo root or from within maps_scraper/
    if Path.cwd().name == "maps_scraper":
        sys.path.insert(0, str(Path.cwd().parent))

    asyncio.run(main())
