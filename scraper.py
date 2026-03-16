"""
Messe Frankfurt Exhibitor List Scraper

Supports all events on the Messe Frankfurt platform:
    *.messefrankfurt.com, *.mesago.com

Usage:
    python scraper.py --url "https://heimtextil.messefrankfurt.com/frankfurt/en/exhibitor-search.html"
    python scraper.py --url "https://ambiente.messefrankfurt.com/frankfurt/en/exhibitor-search.html" --format xlsx
    python scraper.py --url "https://automechanika.messefrankfurt.com/frankfurt/en/exhibitor-search.html" --max 50
"""

import asyncio
import argparse
import json
import re
import sys
from urllib.parse import urljoin, urlparse

import pandas as pd
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright, Page, BrowserContext
from playwright.async_api import TimeoutError as PWTimeout


# ── constants ─────────────────────────────────────────────────────────────────

SOCIAL_PATTERNS: dict[str, re.Pattern] = {
    "linkedin":  re.compile(r"linkedin\.com", re.I),
    "facebook":  re.compile(r"facebook\.com", re.I),
    "instagram": re.compile(r"instagram\.com", re.I),
    "twitter":   re.compile(r"(twitter|x)\.com", re.I),
    "youtube":   re.compile(r"youtube\.com", re.I),
    "xing":      re.compile(r"xing\.com", re.I),
}

MESSE_DOMAINS = re.compile(r"messefrankfurt\.com|mesago\.com", re.I)

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


# ── helpers ───────────────────────────────────────────────────────────────────

def base_url(url: str) -> str:
    p = urlparse(url)
    return f"{p.scheme}://{p.netloc}"


def clean(text: str | None) -> str:
    if not text:
        return ""
    return " ".join(text.split())


# ── consent handler ───────────────────────────────────────────────────────────

async def dismiss_consent(page: Page) -> None:
    """Accept any GDPR/cookie consent overlay."""
    selectors = [
        "button#onetrust-accept-btn-handler",
        "button.onetrust-accept-btn-handler",
        "#didomi-notice-agree-button",
        ".cc-btn.cc-allow",
        "button[id*='accept'][id*='cookie']",
        "button[class*='accept'][class*='cookie']",
        "[data-testid='cookie-accept']",
    ]
    for sel in selectors:
        try:
            btn = page.locator(sel)
            if await btn.count() > 0:
                await btn.first.click(timeout=3_000)
                await page.wait_for_timeout(800)
                return
        except Exception:
            pass


# ── list-page crawler ─────────────────────────────────────────────────────────

async def get_exhibitor_links(page: Page, start_url: str) -> list[str]:
    """
    Collect all exhibitor detail-page URLs.
    Handles both "Load More" and numbered pagination layouts.
    """
    seen: set[str] = set()
    links: list[str] = []
    origin = base_url(start_url)

    print(f"[list] Loading {start_url}")
    # domcontentloaded is far more reliable than networkidle on SPAs
    await page.goto(start_url, wait_until="domcontentloaded", timeout=60_000)
    await page.wait_for_timeout(3_000)
    await dismiss_consent(page)
    await page.wait_for_timeout(1_000)

    # Wait for at least one exhibitor link to appear
    for sel in [
        "a[href*='exhibitor-search.detail']",
        "[class*='exhibitor-teaser']",
        "[class*='exhibitor-list']",
    ]:
        try:
            await page.wait_for_selector(sel, timeout=15_000)
            break
        except Exception:
            pass

    def harvest(html: str) -> list[str]:
        soup = BeautifulSoup(html, "lxml")
        found = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "exhibitor-search.detail" in href:
                full = urljoin(origin, href).split("?")[0]
                if full not in seen:
                    seen.add(full)
                    found.append(full)
                    links.append(full)
        return found

    page_num = 0
    consecutive_empty = 0

    while True:
        page_num += 1
        html = await page.content()
        new_links = harvest(html)
        print(f"[list] Page {page_num}: +{len(new_links)} links (total {len(links)})")

        if not new_links:
            consecutive_empty += 1
            if consecutive_empty >= 2:
                print("[list] No new links found – stopping.")
                break
        else:
            consecutive_empty = 0

        # ── try "Load More" / "Show More" button ──────────────────────────────
        load_more_clicked = False
        for sel in [
            "button[class*='load-more']",
            "a[class*='load-more']",
            "[class*='show-more'] button",
            "button[class*='show-more']",
            ".mf-c-load-more button",
            "[class*='load-more'] button",
            "[data-action*='load']",
        ]:
            try:
                btn = page.locator(sel)
                if await btn.count() == 0:
                    continue
                first = btn.first
                if not await first.is_visible():
                    continue
                if (await first.get_attribute("disabled")) is not None:
                    continue
                if (await first.get_attribute("aria-disabled")) == "true":
                    continue
                await first.scroll_into_view_if_needed()
                await first.click(timeout=5_000)
                await page.wait_for_timeout(2_500)
                load_more_clicked = True
                break
            except Exception:
                pass

        if load_more_clicked:
            continue

        # ── try explicit "Next" link ───────────────────────────────────────────
        next_clicked = False
        for sel in [
            "a[aria-label='Next']",
            "a[aria-label='next']",
            "a[title='Next']",
            "a[rel='next']",
            "a.pagination__next",
            "li.pagination-next:not(.disabled) a",
            ".pager__next a",
        ]:
            try:
                loc = page.locator(sel)
                if await loc.count() == 0:
                    continue
                first = loc.first
                if (await first.get_attribute("aria-disabled")) == "true":
                    break
                if (await first.get_attribute("disabled")) is not None:
                    break
                await first.click(timeout=5_000)
                await page.wait_for_load_state("domcontentloaded", timeout=20_000)
                await page.wait_for_timeout(1_500)
                next_clicked = True
                break
            except Exception:
                pass

        if next_clicked:
            continue

        # ── try clicking the page after the active one ─────────────────────────
        for container_sel in [
            ".mf-c-pagination",
            "ul.pagination",
            "nav[aria-label*='pagination' i]",
            "[class*='pagination']",
            ".pager",
        ]:
            try:
                items = page.locator(f"{container_sel} li")
                count = await items.count()
                if count == 0:
                    continue
                for i in range(count):
                    item = items.nth(i)
                    cls = await item.get_attribute("class") or ""
                    aria = await item.get_attribute("aria-current") or ""
                    if "active" in cls or "current" in cls or aria == "page":
                        if i + 1 < count:
                            a_tag = items.nth(i + 1).locator("a")
                            if await a_tag.count() > 0:
                                a_cls = await a_tag.first.get_attribute("class") or ""
                                if "disabled" not in a_cls:
                                    await a_tag.first.click(timeout=5_000)
                                    await page.wait_for_load_state(
                                        "domcontentloaded", timeout=20_000
                                    )
                                    await page.wait_for_timeout(1_500)
                                    next_clicked = True
                        break
                if next_clicked:
                    break
            except Exception:
                pass

        if not next_clicked:
            print("[list] No further pagination found – all pages collected.")
            break

    return links


# ── detail-page parser ────────────────────────────────────────────────────────

def _extract_address(soup: BeautifulSoup) -> tuple[str, str]:
    """Return (full_address, country)."""
    for sel in [
        "[class*='address']",
        "[class*='location']",
        ".company-address",
        "address",
        "[itemprop='address']",
    ]:
        block = soup.select_one(sel)
        if not block:
            continue
        lines = [clean(ln) for ln in block.get_text("\n").splitlines() if ln.strip()]
        if not lines:
            continue
        full = ", ".join(lines)
        # Last non-numeric line is typically the country
        country = ""
        for line in reversed(lines):
            if not re.search(r"\d", line):
                country = line
                break
        return full, country
    return "", ""


def _walk_product_node(el) -> dict | None:
    """Recursively build a product-group node from a <li> element."""
    # Get the direct text of this node (not children)
    children_text = "".join(
        c.get_text() for c in el.find_all(["ul", "ol"], recursive=False)
    )
    own_text = clean(el.get_text().replace(children_text, ""))
    if not own_text:
        own_text = clean(el.get_text())
    if not own_text:
        return None

    sub_nodes = []
    for child_ul in el.find_all(["ul", "ol"], recursive=False):
        for child_li in child_ul.find_all("li", recursive=False):
            node = _walk_product_node(child_li)
            if node:
                sub_nodes.append(node)

    return {"title": own_text, "subgroups": sub_nodes or None}


def _extract_products(soup: BeautifulSoup) -> list[dict]:
    """Extract hierarchical product group tree."""
    for root_sel in [
        "[class*='product-group']",
        "[class*='product-groups']",
        "[class*='product-categor']",
    ]:
        containers = soup.select(root_sel)
        if not containers:
            continue
        roots = []
        for container in containers:
            for li in container.find_all("li", recursive=False):
                node = _walk_product_node(li)
                if node:
                    roots.append(node)
        if roots:
            return roots

    # Flat fallback
    for sel in ["[class*='product'] li", "[class*='category'] li", "[class*='segment'] li"]:
        items = soup.select(sel)
        if items:
            return [
                {"title": clean(i.get_text()), "subgroups": None}
                for i in items
                if i.get_text(strip=True)
            ]
    return []


def parse_detail(html: str, url: str) -> dict:
    """Extract all exhibitor fields from a detail page."""
    soup = BeautifulSoup(html, "lxml")

    def text(sel: str) -> str:
        el = soup.select_one(sel)
        return clean(el.get_text()) if el else ""

    # ── company name ──────────────────────────────────────────────────────────
    name = ""
    for sel in [
        ".mf-c-company-info__name",
        ".c-company-info__name",
        "h1[class*='company']",
        "h1[class*='exhibitor']",
        "h1[class*='headline']",
        "[class*='company-name']",
        "[class*='exhibitor-name']",
        "h1",
    ]:
        val = text(sel)
        if val and len(val) > 1:
            name = val
            break

    # ── address + country ─────────────────────────────────────────────────────
    address, country = _extract_address(soup)

    # ── phone ─────────────────────────────────────────────────────────────────
    phone = ""
    tel_links = soup.find_all("a", href=re.compile(r"^tel:", re.I))
    if tel_links:
        a = tel_links[0]
        phone = clean(a.get_text()) or re.sub(r"^tel:", "", a["href"]).strip()

    # ── email ─────────────────────────────────────────────────────────────────
    email = ""
    mail_links = soup.find_all("a", href=re.compile(r"^mailto:", re.I))
    if mail_links:
        email = re.sub(r"^mailto:", "", mail_links[0]["href"]).split("?")[0].strip()

    # ── website ───────────────────────────────────────────────────────────────
    website = ""
    for a in soup.find_all("a", href=re.compile(r"^https?://", re.I)):
        href = a["href"].strip()
        if MESSE_DOMAINS.search(href):
            continue
        if any(p.search(href) for p in SOCIAL_PATTERNS.values()):
            continue
        if re.search(r"google\.|maps\.google|#", href):
            continue
        website = href
        break

    # ── social media (collect all unique links per platform) ──────────────────
    social: dict[str, list[str]] = {k: [] for k in SOCIAL_PATTERNS}
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        for platform, pattern in SOCIAL_PATTERNS.items():
            if pattern.search(href) and href not in social[platform]:
                social[platform].append(href)

    # ── hall / stand ──────────────────────────────────────────────────────────
    # FIX: old regex r"(\d[\w.]*)\s*/\s*(\w+)" missed "Hall 4.1 - D71" format
    hall_stand = ""
    for sel in [
        "[class*='booth']",
        "[class*='stand']",
        ".mf-c-booth-location",
        "[class*='hall'][class*='location']",
        "[class*='hall']",
    ]:
        el = soup.select_one(sel)
        if el:
            raw = clean(el.get_text())
            raw = re.sub(r"^\s*(hall|stand|booth|halle)\s*[:\-]?\s*", "", raw, flags=re.I)
            if raw:
                hall_stand = raw
                break

    # ── product groups ────────────────────────────────────────────────────────
    products = _extract_products(soup)

    # ── brands ────────────────────────────────────────────────────────────────
    brands: list[str] = []
    for sel in ["[class*='brand'] li", "[class*='brand-list'] li", "[class*='brands'] li"]:
        items = soup.select(sel)
        if items:
            brands = [clean(i.get_text()) for i in items if i.get_text(strip=True)]
            break

    # ── keywords ──────────────────────────────────────────────────────────────
    keywords: list[str] = []
    for sel in [
        "[class*='keyword'] li",
        "[class*='keywords'] li",
        "[class*='tag'] li",
        "[class*='tags'] li",
    ]:
        items = soup.select(sel)
        if items:
            keywords = [clean(i.get_text()) for i in items if i.get_text(strip=True)]
            break
    if not keywords:
        meta = soup.select_one("meta[name='keywords']")
        if meta and meta.get("content"):
            keywords = [k.strip() for k in meta["content"].split(",") if k.strip()]

    # ── contact persons ───────────────────────────────────────────────────────
    contacts: list[dict] = []
    for container_sel in [
        "[class*='contact-person']",
        "[class*='contact-card']",
        "[class*='contact-info']",
    ]:
        for block in soup.select(container_sel):
            cname = ""
            ctitle = ""
            cphone = ""
            cemail = ""
            for ns in ["[class*='name']", "strong", "b"]:
                el = block.select_one(ns)
                if el:
                    cname = clean(el.get_text())
                    break
            for ts in ["[class*='title']", "[class*='position']", "[class*='role']"]:
                el = block.select_one(ts)
                if el:
                    ctitle = clean(el.get_text())
                    break
            tel = block.find("a", href=re.compile(r"^tel:", re.I))
            if tel:
                cphone = re.sub(r"^tel:", "", tel["href"]).strip()
            mail = block.find("a", href=re.compile(r"^mailto:", re.I))
            if mail:
                cemail = re.sub(r"^mailto:", "", mail["href"]).split("?")[0].strip()
            if cname or cemail:
                contacts.append(
                    {"name": cname, "title": ctitle, "phone": cphone, "email": cemail}
                )
        if contacts:
            break

    # ── description ───────────────────────────────────────────────────────────
    description = ""
    for sel in [
        "[class*='description']",
        "[class*='profile-text']",
        "[class*='company-text']",
        "[class*='about']",
    ]:
        el = soup.select_one(sel)
        if el:
            val = clean(el.get_text())
            if len(val) > 20:
                description = val
                break

    return {
        "url": url,
        "name": name,
        "address": address,
        "country": country,
        "phone": phone,
        "email": email,
        "website": website,
        "hall_stand": hall_stand,
        "description": description,
        "products": products,
        "brands": " | ".join(brands),
        "keywords": " | ".join(keywords),
        "contact_persons": contacts,
        "linkedin":  social["linkedin"][0]  if social["linkedin"]  else "",
        "facebook":  social["facebook"][0]  if social["facebook"]  else "",
        "instagram": social["instagram"][0] if social["instagram"] else "",
        "twitter":   social["twitter"][0]   if social["twitter"]   else "",
        "youtube":   social["youtube"][0]   if social["youtube"]   else "",
        "xing":      social["xing"][0]      if social["xing"]      else "",
    }


# ── flatten for tabular export ────────────────────────────────────────────────

def _leaf_paths(node: dict, path: list[str]) -> list[list[str]]:
    current = path + [node["title"]]
    if not node.get("subgroups"):
        return [current]
    paths = []
    for child in node["subgroups"]:
        paths.extend(_leaf_paths(child, current))
    return paths


def flatten_record(record: dict) -> list[dict]:
    """
    Expand one record into multiple rows (one per product category leaf).
    Returns at least one row even when products is empty.
    """
    base = {k: v for k, v in record.items() if k not in ("products", "contact_persons")}
    base["contact_persons"] = json.dumps(
        record.get("contact_persons", []), ensure_ascii=False
    )

    products = record.get("products", [])
    if not products:
        base["product_category_1"] = ""
        base["product_category_2"] = ""
        base["product_category_3"] = ""
        return [base]

    rows = []
    for root in products:
        for path in _leaf_paths(root, []):
            row = dict(base)
            row["product_category_1"] = path[0] if len(path) > 0 else ""
            row["product_category_2"] = path[1] if len(path) > 1 else ""
            row["product_category_3"] = path[2] if len(path) > 2 else ""
            rows.append(row)

    return rows if rows else [base]


# ── retry-aware page loader ───────────────────────────────────────────────────

async def load_page(context: BrowserContext, url: str, max_retries: int = 3) -> str | None:
    """Fetch a page's HTML with exponential-backoff retries."""
    for attempt in range(1, max_retries + 1):
        pg = None
        try:
            pg = await context.new_page()
            await pg.goto(url, wait_until="domcontentloaded", timeout=45_000)
            await pg.wait_for_timeout(1_500)
            return await pg.content()
        except PWTimeout:
            print(f"    [attempt {attempt}/{max_retries}] timeout: {url}")
        except Exception as exc:
            print(f"    [attempt {attempt}/{max_retries}] error {url}: {exc}")
        finally:
            if pg:
                try:
                    await pg.close()
                except Exception:
                    pass
        if attempt < max_retries:
            await asyncio.sleep(2 ** attempt)  # 2s, 4s, 8s

    return None


# ── orchestrator ──────────────────────────────────────────────────────────────

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
            user_agent=UA,
            viewport={"width": 1280, "height": 900},
            locale="en-US",
        )

        # step 1 – collect links
        list_page = await context.new_page()
        links = await get_exhibitor_links(list_page, start_url)
        await list_page.close()

        if not links:
            print(
                "[ERROR] No exhibitor links found.\n"
                "        Check that the URL is correct and the site is reachable."
            )
            await browser.close()
            sys.exit(1)

        if max_exhibitors:
            links = links[:max_exhibitors]

        total = len(links)
        print(f"\n[scraper] Scraping {total} exhibitor profiles …\n")

        # step 2 – scrape detail pages concurrently
        results: list[dict] = []
        sem = asyncio.Semaphore(concurrency)
        # FIX: use a shared counter so progress numbers stay accurate
        # regardless of asyncio.gather completion order
        counter = {"done": 0}

        async def scrape_one(url: str) -> dict | None:
            async with sem:
                html = await load_page(context, url)
                counter["done"] += 1
                n = counter["done"]
                if html is None:
                    print(f"  [{n}/{total}] FAILED {url}")
                    return None
                data = parse_detail(html, url)
                print(f"  [{n}/{total}] {data['name'] or url}")
                return data

        tasks = [asyncio.create_task(scrape_one(u)) for u in links]
        for result in await asyncio.gather(*tasks):
            if result:
                results.append(result)

        await browser.close()

    if not results:
        print("[ERROR] No data was scraped.")
        sys.exit(1)

    # step 3 – save output
    if fmt == "json":
        path = output_file or "exhibitors.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
    else:
        flat_rows: list[dict] = []
        for rec in results:
            flat_rows.extend(flatten_record(rec))

        df = pd.DataFrame(flat_rows)

        # Consistent column order
        first_cols = [
            "url", "name", "address", "country", "phone", "email", "website",
            "hall_stand", "linkedin", "facebook", "instagram", "twitter",
            "youtube", "xing", "keywords", "brands", "description",
            "product_category_1", "product_category_2", "product_category_3",
            "contact_persons",
        ]
        other_cols = [c for c in df.columns if c not in first_cols]
        df = df[[c for c in first_cols if c in df.columns] + other_cols]

        if fmt == "xlsx":
            path = output_file or "exhibitors.xlsx"
            df.to_excel(path, index=False, engine="openpyxl")
        else:
            path = output_file or "exhibitors.csv"
            df.to_csv(path, index=False, encoding="utf-8-sig")

    print(f"\n[done] {len(results)} exhibitors → {path}")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Messe Frankfurt Exhibitor List Scraper",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scraper.py --url "https://heimtextil.messefrankfurt.com/frankfurt/en/exhibitor-search.html"
  python scraper.py --url "https://ambiente.messefrankfurt.com/frankfurt/en/exhibitor-search.html" --format xlsx
  python scraper.py --url "https://light-building.messefrankfurt.com/frankfurt/en/exhibitor-search.html" --max 50

Supported domains: *.messefrankfurt.com, *.mesago.com
        """,
    )
    parser.add_argument("--url", required=True, help="Exhibitor search page URL")
    parser.add_argument("--output", default="", help="Output file path (default: exhibitors.<fmt>)")
    parser.add_argument("--format", default="csv", choices=["csv", "json", "xlsx"])
    parser.add_argument(
        "--concurrency", type=int, default=3,
        help="Parallel detail-page requests (default: 3)",
    )
    parser.add_argument(
        "--max", type=int, default=None, dest="max_exhibitors",
        help="Max exhibitors to scrape (default: all)",
    )
    parser.add_argument("--headful", action="store_true", help="Show browser window")
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
