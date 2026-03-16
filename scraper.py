"""
Messe Frankfurt Exhibitor List Scraper
Replicates: https://apify.com/skython/messe-frankfurt-exhibitor-list-scraper

Usage:
    python scraper.py --url "https://heimtextil.messefrankfurt.com/frankfurt/en/exhibitor-search.html"
    python scraper.py --url "https://ambiente.messefrankfurt.com/frankfurt/en/exhibitor-search.html" --output output.xlsx
    python scraper.py --url "https://automechanika.messefrankfurt.com/frankfurt/en/exhibitor-search.html" --format json
"""

import asyncio
import argparse
import json
import re
import sys
import time
from urllib.parse import urljoin, urlparse

import pandas as pd
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright, Page, BrowserContext


# ── helpers ──────────────────────────────────────────────────────────────────

def base_url(url: str) -> str:
    """Return scheme + netloc of a URL."""
    p = urlparse(url)
    return f"{p.scheme}://{p.netloc}"


def clean(text: str | None) -> str:
    if not text:
        return ""
    return " ".join(text.split())


# ── list-page crawler ─────────────────────────────────────────────────────────

async def get_exhibitor_links(page: Page, start_url: str) -> list[str]:
    """
    Navigate through all pages of the exhibitor search and collect
    every detail-page URL.
    """
    links: list[str] = []
    origin = base_url(start_url)

    print(f"[list] Loading {start_url}")
    await page.goto(start_url, wait_until="networkidle", timeout=60_000)

    # Some pages need a cookie/consent click
    for selector in ["button#onetrust-accept-btn-handler",
                     "button.accept-cookies",
                     "[data-testid='cookie-accept']"]:
        try:
            btn = page.locator(selector)
            if await btn.count() > 0:
                await btn.first.click()
                await page.wait_for_timeout(1000)
                break
        except Exception:
            pass

    page_num = 0
    while True:
        page_num += 1
        await page.wait_for_timeout(2000)

        html = await page.content()
        soup = BeautifulSoup(html, "lxml")

        # Collect all exhibitor detail links on this listing page
        new_links = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "exhibitor-search.detail" in href:
                full = urljoin(origin, href)
                if full not in links:
                    new_links.append(full)
                    links.append(full)

        print(f"[list] Page {page_num}: found {len(new_links)} links "
              f"(total {len(links)})")

        # Try to click the "next page" / pagination button
        next_btn = None
        for selector in [
            "a[aria-label='Next']",
            "a.pagination__next",
            "li.pagination-next > a",
            "button[aria-label='Next page']",
            ".pager__next a",
            "a.next",
            "[data-role='next-page']",
        ]:
            try:
                loc = page.locator(selector)
                if await loc.count() > 0:
                    is_disabled = await loc.first.get_attribute("aria-disabled")
                    if is_disabled == "true":
                        break
                    next_btn = loc.first
                    break
            except Exception:
                pass

        # Also try finding a numbered pagination link with a higher number
        if next_btn is None:
            # Look for a pagination list
            for sel in ["ul.pagination li", "nav.pagination a", ".pager a"]:
                try:
                    items = page.locator(sel)
                    count = await items.count()
                    if count > 0:
                        # Find the "active" item index and click next
                        for i in range(count):
                            item = items.nth(i)
                            cls = await item.get_attribute("class") or ""
                            aria = await item.get_attribute("aria-current") or ""
                            if "active" in cls or aria == "page":
                                if i + 1 < count:
                                    nxt = items.nth(i + 1)
                                    tag = await nxt.evaluate("el => el.tagName")
                                    if tag.lower() == "a":
                                        next_btn = nxt
                                    else:
                                        a_in_nxt = nxt.locator("a")
                                        if await a_in_nxt.count() > 0:
                                            next_btn = a_in_nxt.first
                                break
                        if next_btn:
                            break
                except Exception:
                    pass

        if next_btn is None:
            print("[list] No more pages found.")
            break

        try:
            await next_btn.click()
            await page.wait_for_load_state("networkidle", timeout=30_000)
        except Exception as e:
            print(f"[list] Could not navigate to next page: {e}")
            break

    return links


# ── detail-page parser ────────────────────────────────────────────────────────

def parse_detail(html: str, url: str) -> dict:
    """Extract all exhibitor fields from a detail page."""
    soup = BeautifulSoup(html, "lxml")

    def text(sel: str) -> str:
        el = soup.select_one(sel)
        return clean(el.get_text()) if el else ""

    def texts(sel: str) -> list[str]:
        return [clean(el.get_text()) for el in soup.select(sel) if el.get_text(strip=True)]

    def attr(sel: str, attribute: str) -> str:
        el = soup.select_one(sel)
        return el[attribute].strip() if el and el.get(attribute) else ""

    # ── company name ──────────────────────────────────────────────────────────
    name = (
        text("h1.exhibitor-detail__name")
        or text("h1.company-name")
        or text("h1[class*='company']")
        or text("h1[class*='exhibitor']")
        or text("h1")
    )

    # ── address block ─────────────────────────────────────────────────────────
    address_parts: list[str] = []
    for sel in [
        ".exhibitor-detail__address",
        ".company-address",
        "[class*='address']",
        "address",
    ]:
        block = soup.select_one(sel)
        if block:
            address_parts = [clean(line) for line in block.get_text("\n").splitlines()
                             if line.strip()]
            break
    address = ", ".join(address_parts)

    # ── contacts ──────────────────────────────────────────────────────────────
    phone = ""
    email = ""
    website = ""

    # phone: look for tel: links or labelled fields
    tel_a = soup.find("a", href=re.compile(r"^tel:"))
    if tel_a:
        phone = clean(tel_a.get_text()) or tel_a["href"].replace("tel:", "").strip()

    # email: look for mailto: links
    mail_a = soup.find("a", href=re.compile(r"^mailto:"))
    if mail_a:
        email = mail_a["href"].replace("mailto:", "").strip()

    # website: look for http links that aren't on the messe domain
    for a in soup.find_all("a", href=re.compile(r"^https?://")):
        href = a["href"]
        if "messefrankfurt.com" not in href and "facebook." not in href \
                and "instagram." not in href and "linkedin." not in href \
                and "twitter." not in href and "youtube." not in href:
            website = href.strip()
            break

    # ── social media ──────────────────────────────────────────────────────────
    social: dict[str, str] = {}
    for platform in ["facebook", "instagram", "linkedin", "twitter", "youtube", "xing"]:
        a = soup.find("a", href=re.compile(platform, re.I))
        if a:
            social[platform] = a["href"].strip()

    # ── hall / stand ──────────────────────────────────────────────────────────
    hall = ""
    stand = ""
    for sel in [
        ".exhibitor-detail__stand",
        ".hall-stand",
        "[class*='stand']",
        "[class*='hall']",
        "[class*='booth']",
    ]:
        el = soup.select_one(sel)
        if el:
            raw = clean(el.get_text())
            # try to split "Hall 3 / B10"
            m = re.search(r"(\d[\w.]*)\s*/\s*(\w+)", raw)
            if m:
                hall, stand = m.group(1), m.group(2)
            else:
                hall = raw
            break

    # ── product groups / categories ───────────────────────────────────────────
    products: list[str] = []
    for sel in [
        ".exhibitor-detail__product-groups li",
        ".product-groups li",
        "[class*='product'] li",
        "[class*='category'] li",
    ]:
        items = soup.select(sel)
        if items:
            products = [clean(i.get_text()) for i in items if i.get_text(strip=True)]
            break

    # ── brands ────────────────────────────────────────────────────────────────
    brands: list[str] = []
    for sel in [
        ".exhibitor-detail__brands li",
        ".brands li",
        "[class*='brand'] li",
    ]:
        items = soup.select(sel)
        if items:
            brands = [clean(i.get_text()) for i in items if i.get_text(strip=True)]
            break

    # ── keywords ──────────────────────────────────────────────────────────────
    keywords: list[str] = []
    for sel in [
        ".exhibitor-detail__keywords li",
        ".keywords li",
        "[class*='keyword'] li",
        "meta[name='keywords']",
    ]:
        if sel.startswith("meta"):
            el = soup.select_one(sel)
            if el and el.get("content"):
                keywords = [k.strip() for k in el["content"].split(",")]
        else:
            items = soup.select(sel)
            if items:
                keywords = [clean(i.get_text()) for i in items if i.get_text(strip=True)]
        if keywords:
            break

    # ── contact person ────────────────────────────────────────────────────────
    contact_person = ""
    for sel in [
        ".contact-person__name",
        ".exhibitor-detail__contact-name",
        "[class*='contact'] [class*='name']",
    ]:
        el = soup.select_one(sel)
        if el:
            contact_person = clean(el.get_text())
            break

    # ── description / about ───────────────────────────────────────────────────
    description = ""
    for sel in [
        ".exhibitor-detail__description",
        ".company-description",
        "[class*='description']",
        "[class*='about']",
    ]:
        el = soup.select_one(sel)
        if el:
            description = clean(el.get_text())
            break

    return {
        "url": url,
        "name": name,
        "address": address,
        "phone": phone,
        "email": email,
        "website": website,
        "hall": hall,
        "stand": stand,
        "contact_person": contact_person,
        "description": description,
        "products": " | ".join(products),
        "brands": " | ".join(brands),
        "keywords": " | ".join(keywords),
        "facebook": social.get("facebook", ""),
        "instagram": social.get("instagram", ""),
        "linkedin": social.get("linkedin", ""),
        "twitter": social.get("twitter", ""),
        "youtube": social.get("youtube", ""),
        "xing": social.get("xing", ""),
    }


# ── scraper orchestrator ──────────────────────────────────────────────────────

async def scrape(
    start_url: str,
    output_file: str,
    fmt: str,
    headless: bool,
    concurrency: int,
    max_exhibitors: int | None,
) -> None:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=headless)
        context: BrowserContext = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 900},
        )

        # ── step 1: collect all detail links ─────────────────────────────────
        list_page = await context.new_page()
        links = await get_exhibitor_links(list_page, start_url)
        await list_page.close()

        if not links:
            print("[ERROR] No exhibitor links found. "
                  "The page may require JS rendering that couldn't be detected.")
            await browser.close()
            sys.exit(1)

        if max_exhibitors:
            links = links[:max_exhibitors]

        print(f"\n[scraper] Scraping {len(links)} exhibitor profiles …\n")

        # ── step 2: scrape detail pages with limited concurrency ──────────────
        results: list[dict] = []
        sem = asyncio.Semaphore(concurrency)

        async def scrape_one(url: str, idx: int) -> dict | None:
            async with sem:
                try:
                    pg = await context.new_page()
                    await pg.goto(url, wait_until="networkidle", timeout=45_000)
                    await pg.wait_for_timeout(1500)
                    html = await pg.content()
                    await pg.close()
                    data = parse_detail(html, url)
                    print(f"  [{idx}/{len(links)}] {data['name'] or url}")
                    return data
                except Exception as e:
                    print(f"  [{idx}/{len(links)}] ERROR {url}: {e}")
                    return None

        tasks = [scrape_one(url, i + 1) for i, url in enumerate(links)]
        for coro in asyncio.as_completed(tasks):
            result = await coro
            if result:
                results.append(result)

        await browser.close()

    if not results:
        print("[ERROR] No data was scraped.")
        sys.exit(1)

    # ── step 3: save output ───────────────────────────────────────────────────
    df = pd.DataFrame(results)

    if fmt == "json":
        path = output_file if output_file else "exhibitors.json"
        df.to_json(path, orient="records", indent=2, force_ascii=False)
    elif fmt == "xlsx":
        path = output_file if output_file else "exhibitors.xlsx"
        df.to_excel(path, index=False, engine="openpyxl")
    else:
        path = output_file if output_file else "exhibitors.csv"
        df.to_csv(path, index=False, encoding="utf-8-sig")

    print(f"\n[done] {len(results)} exhibitors saved → {path}")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Messe Frankfurt Exhibitor List Scraper",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scraper.py --url "https://heimtextil.messefrankfurt.com/frankfurt/en/exhibitor-search.html"
  python scraper.py --url "https://ambiente.messefrankfurt.com/frankfurt/en/exhibitor-search.html" --format xlsx
  python scraper.py --url "https://automechanika.messefrankfurt.com/frankfurt/en/exhibitor-search.html" --max 50

Supported events (same URL pattern):
  heimtextil, ambiente, automechanika, christmasworld, creativeworld,
  light-building, ish, prolight-sound, techtextil, and many more.
        """,
    )
    parser.add_argument(
        "--url", required=True,
        help="Messe Frankfurt exhibitor-search.html URL",
    )
    parser.add_argument(
        "--output", default="",
        help="Output file path (default: exhibitors.<format>)",
    )
    parser.add_argument(
        "--format", default="csv", choices=["csv", "json", "xlsx"],
        help="Output format (default: csv)",
    )
    parser.add_argument(
        "--concurrency", type=int, default=3,
        help="Number of detail pages to scrape in parallel (default: 3)",
    )
    parser.add_argument(
        "--max", type=int, default=None,
        dest="max_exhibitors",
        help="Maximum number of exhibitors to scrape (default: all)",
    )
    parser.add_argument(
        "--headful", action="store_true",
        help="Run browser in headful mode (visible)",
    )
    args = parser.parse_args()

    asyncio.run(
        scrape(
            start_url=args.url,
            output_file=args.output,
            fmt=args.format,
            headless=not args.headful,
            concurrency=args.concurrency,
            max_exhibitors=args.max_exhibitors,
        )
    )


if __name__ == "__main__":
    main()
