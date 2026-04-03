"""
lead_qualifier entry point.

Usage:
    python lead_qualifier/main.py
"""

import asyncio
import json
import sys
from pathlib import Path

from rich.console import Console

from lead_qualifier.ai_scorer import score_website
from lead_qualifier.reporter import generate_reports
from lead_qualifier.segmenter import get_no_website, get_unanalyzed_with_website
from lead_qualifier.site_analyzer import analyze_all
from maps_scraper.storage import update_analysis

console = Console()


async def main() -> None:
    console.rule("[bold green]Lead Qualifier")

    # ── 1. No-website leads (already highest priority — no analysis needed)
    no_site = get_no_website()
    console.print(
        f"\n[bold yellow]No-website leads:[/bold yellow] {len(no_site)} "
        "(direct HIGH priority — skipping technical analysis)"
    )

    # ── 2. Analyze businesses that have websites
    with_site = get_unanalyzed_with_website()
    console.print(
        f"[bold yellow]Websites to analyze:[/bold yellow] {len(with_site)}\n"
    )

    if with_site:
        console.print("[dim]Running concurrent site analysis…[/dim]")
        analyses = await analyze_all(with_site)

        for biz, analysis in zip(with_site, analyses):
            _display_analysis(biz, analysis)

            # AI scoring (Ollama → rule-based fallback)
            score_data = score_website(analysis)
            score_data["reachable"] = analysis.get("reachable", False)

            update_analysis(biz["id"], analysis.get("email", ""), score_data)

    # ── 3. Export priority reports
    console.rule("[bold green]Reports")
    n = generate_reports()

    console.print(
        f"\n[green]Done.[/green] {n} priority leads exported to:\n"
        "  output/priority_leads.csv\n"
        "  output/priority_leads.xlsx\n"
        "  output/priority_leads.json\n"
    )


def _display_analysis(biz: dict, analysis: dict) -> None:
    name = biz.get("name", "?")
    ok = "[green]OK[/green]" if analysis.get("reachable") else "[red]UNREACHABLE[/red]"
    ms = analysis.get("load_time_ms")
    load = f"{ms} ms" if ms else "N/A"
    email = analysis.get("email", "")
    console.print(
        f"  {name[:40]:<40} {ok}  {load:>8}"
        + (f"  [cyan]{email}[/cyan]" if email else "")
    )


if __name__ == "__main__":
    if Path.cwd().name == "lead_qualifier":
        sys.path.insert(0, str(Path.cwd().parent))

    asyncio.run(main())
