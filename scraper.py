"""
Messe Frankfurt Exhibitor List Scraper
Replicates: https://apify.com/skython/messe-frankfurt-exhibitor-list-scraper

Uses the official Messe Frankfurt public API (no browser needed).

Usage:
    python scraper.py --url "https://heimtextil.messefrankfurt.com/frankfurt/en/exhibitor-search.html"
    python scraper.py --url "https://ambiente.messefrankfurt.com/frankfurt/en/exhibitor-search.html" --format xlsx
    python scraper.py --url "https://automechanika.messefrankfurt.com/frankfurt/en/exhibitor-search.html" --format json --max 50
"""

import argparse
import json
import re
import sys
import time
from html import unescape
from urllib.parse import urljoin

import pandas as pd
import requests
from bs4 import BeautifulSoup


# ── constants ────────────────────────────────────────────────────────────────

API_BASE = "https://api.messefrankfurt.com/service/esb_api"
API_KEY = "LXnMWcYQhipLAS7rImEzmZ3CkrU033FMha9cwVSngG4vbufTsAOCQQ=="
IMAGE_BASE = "https://exhibitorsearch.messefrankfurt.com/images"
PAGE_SIZE = 25

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
    "apikey": API_KEY,
}


# ── config extraction ────────────────────────────────────────────────────────

def extract_config(url: str) -> dict:
    """Fetch the exhibitor-search page and extract the data-config JSON."""
    print(f"[config] Fetching {url}")
    r = requests.get(url, headers={"User-Agent": HEADERS["User-Agent"]}, timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "lxml")

    el = soup.find(attrs={"data-config": True})
    if not el:
        print("[ERROR] Could not find data-config element on the page.")
        print("        Make sure the URL points to an exhibitor-search.html page.")
        sys.exit(1)

    config = json.loads(el["data-config"])
    event_id = config.get("API_EVENT_ID")
    language = config.get("LANGUAGE", "en-GB")
    base_path = config.get("BASE_PATH", "")
    routes = config.get("ROUTES", {})
    image_url = config.get("IMAGE_URL", IMAGE_BASE)

    if not event_id:
        print("[ERROR] API_EVENT_ID not found in config.")
        sys.exit(1)

    print(f"[config] Event: {event_id}  Language: {language}")
    return {
        "event_id": event_id,
        "language": language,
        "base_path": base_path,
        "routes": routes,
        "image_url": image_url,
        "origin": re.match(r"https?://[^/]+", url).group(0),
    }


# ── helpers ──────────────────────────────────────────────────────────────────

def strip_html(text: str | None) -> str:
    """Remove HTML tags and clean whitespace."""
    if not text:
        return ""
    text = unescape(text)
    text = re.sub(r"<[^>]+>", " ", text)
    return " ".join(text.split()).strip()


def safe_get(d: dict | None, *keys, default=""):
    """Safely traverse nested dicts."""
    current = d
    for key in keys:
        if not isinstance(current, dict):
            return default
        current = current.get(key)
        if current is None:
            return default
    return current if current is not None else default


# ── API calls ────────────────────────────────────────────────────────────────

def search_exhibitors(event_id: str, page_number: int = 1, page_size: int = PAGE_SIZE,
                      query: str = "") -> dict:
    """Call the exhibitor search API and return the JSON response."""
    url = f"{API_BASE}/exhibitor-service/api/2.1/public/exhibitor/search"
    params = {
        "findEventVariable": event_id,
        "pageSize": page_size,
        "pageNumber": page_number,
    }
    if query:
        params["q"] = query

    r = requests.get(url, params=params, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.json()


def get_exhibitor_detail(rewrite_id: str, event_id: str, language: str = "en-GB") -> dict:
    """Call the exhibitor detail (profile) API."""
    url = (f"{API_BASE}/exhibitor-service/api/2.1/public/exhibitor/"
           f"profile/{language}/{rewrite_id}/{event_id}")
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.json()


# ── data extraction ──────────────────────────────────────────────────────────

def extract_exhibitor_data(hit: dict, config: dict) -> dict:
    """Extract a flat dict of exhibitor data from a search hit."""
    ex = hit.get("exhibitor", {})

    # Hall / stand
    halls = []
    stands = []
    booth_types = []
    for h in safe_get(ex, "exhibition", "exhibitionHall", default=[]):
        hall_name = safe_get(h, "name", default="")
        if hall_name:
            halls.append(hall_name)
        for s in h.get("stand", []):
            stand_name = s.get("name", "")
            if stand_name:
                stands.append(stand_name)
            bt = s.get("boothType", "")
            if bt:
                booth_types.append(bt)

    # Products (from search hit — basic)
    products_list = safe_get(ex, "products", "products", default=[])
    product_names = [p.get("name", "") for p in products_list if p.get("name")]

    # Categories
    categories = []
    for cat in ex.get("categories", []):
        name = safe_get(cat, "label", default="")
        if not name and isinstance(cat, dict):
            name = safe_get(cat, "name", default="")
        if name:
            categories.append(name)

    # Brands
    raw_brands = ex.get("brands", []) or []
    brands = []
    for b in raw_brands:
        if isinstance(b, dict):
            name = b.get("name", "")
        elif isinstance(b, str):
            name = b
        else:
            name = ""
        if name:
            brands.append(name)

    # Social media
    social = {}
    for link in ex.get("socialMediaChannels", []) or ex.get("socialMedia", []) or []:
        platform = link.get("type", "").lower()
        url = link.get("url", "")
        if platform and url:
            social[platform] = url

    # Website
    website = ""
    for w in ex.get("websites", []) or []:
        if isinstance(w, dict):
            website = w.get("url", "")
        elif isinstance(w, str):
            website = w
        if website:
            break
    if not website:
        website = safe_get(ex, "website", default="")

    # Contact persons
    contact_persons = []
    for cp in ex.get("contactPersons", []) or []:
        name_parts = [cp.get("salutation", ""), cp.get("firstName", ""),
                      cp.get("lastName", "")]
        full = " ".join(p for p in name_parts if p).strip()
        if full:
            contact_persons.append(full)

    # Build detail URL
    origin = config.get("origin", "")
    base_path = config.get("base_path", "")
    rewrite_id = ex.get("rewriteId", "")
    detail_url = f"{origin}{base_path}/exhibitor-search.detail.html/{rewrite_id}.html"

    return {
        "name": ex.get("name", ""),
        "rewrite_id": rewrite_id,
        "detail_url": detail_url,
        "description": strip_html(safe_get(ex, "description", "text")),
        "street": safe_get(ex, "address", "street"),
        "city": safe_get(ex, "address", "city"),
        "zip": safe_get(ex, "address", "zip"),
        "country": safe_get(ex, "address", "country", "label"),
        "country_code": safe_get(ex, "address", "country", "iso3"),
        "phone": safe_get(ex, "address", "tel"),
        "fax": safe_get(ex, "address", "fax"),
        "email": safe_get(ex, "address", "email"),
        "website": website,
        "hall": " | ".join(halls),
        "stand": " | ".join(stands),
        "booth_type": " | ".join(booth_types),
        "exhibition": safe_get(ex, "exhibition", "name"),
        "exhibition_start": safe_get(ex, "exhibition", "startdate"),
        "exhibition_end": safe_get(ex, "exhibition", "enddate"),
        "products": " | ".join(product_names),
        "categories": " | ".join(categories),
        "brands": " | ".join(brands),
        "keywords": " | ".join(ex.get("keyWords", []) or []),
        "contact_persons": " | ".join(contact_persons),
        "facebook": social.get("facebook", ""),
        "instagram": social.get("instagram", ""),
        "linkedin": social.get("linkedin", ""),
        "twitter": social.get("twitter", social.get("x", "")),
        "youtube": social.get("youtube", ""),
        "xing": social.get("xing", ""),
    }


def enrich_with_detail(row: dict, config: dict) -> dict:
    """Optionally fetch the full detail page for richer data."""
    try:
        resp = get_exhibitor_detail(
            row["rewrite_id"],
            config["event_id"],
            config["language"],
        )
        if not resp.get("success"):
            return row

        detail = resp["result"]

        # Enrich with any missing fields
        if not row["description"]:
            row["description"] = strip_html(safe_get(detail, "description", "text"))
        if not row["website"]:
            for w in detail.get("websites", []) or []:
                url = w.get("url", "") if isinstance(w, dict) else w
                if url:
                    row["website"] = url
                    break

        # Social media from detail
        for link in detail.get("socialMediaChannels", []) or []:
            platform = link.get("type", "").lower()
            url = link.get("url", "")
            if platform and url:
                if platform in row and not row[platform]:
                    row[platform] = url

        # Contact persons from detail
        if not row["contact_persons"]:
            cps = []
            for cp in detail.get("contactPersons", []) or []:
                parts = [cp.get("salutation", ""), cp.get("firstName", ""),
                         cp.get("lastName", "")]
                full = " ".join(p for p in parts if p).strip()
                if full:
                    cps.append(full)
            row["contact_persons"] = " | ".join(cps)

        # Brands from detail
        if not row["brands"]:
            brands = [b.get("name", "") for b in detail.get("brands", []) or [] if b.get("name")]
            row["brands"] = " | ".join(brands)

        # More product data from detail
        if not row["products"]:
            products_data = safe_get(detail, "products", "products", default=[])
            names = [p.get("name", "") for p in products_data if p.get("name")]
            row["products"] = " | ".join(names)

    except Exception as e:
        print(f"  [detail] Warning: could not fetch detail for {row['rewrite_id']}: {e}")

    return row


# ── main scraper ─────────────────────────────────────────────────────────────

def scrape(
    url: str,
    output_file: str,
    fmt: str,
    max_exhibitors: int | None,
    fetch_details: bool,
    query: str,
) -> None:
    config = extract_config(url)
    event_id = config["event_id"]

    # First request to get total count
    first_page = search_exhibitors(event_id, page_number=1, page_size=PAGE_SIZE, query=query)
    if not first_page.get("success"):
        print(f"[ERROR] API returned error: {first_page}")
        sys.exit(1)

    total = first_page.get("result", {}).get("metaData", {}).get("hitsTotal", 0)
    print(f"[search] Total exhibitors: {total}")

    if max_exhibitors:
        total = min(total, max_exhibitors)
        print(f"[search] Limited to: {total}")

    # Collect all hits via pagination
    all_hits = first_page.get("result", {}).get("hits", [])
    collected = len(all_hits)
    page_num = 1

    while collected < total:
        page_num += 1
        print(f"[search] Fetching page {page_num} ({collected}/{total}) …")
        resp = search_exhibitors(event_id, page_number=page_num, page_size=PAGE_SIZE, query=query)
        hits = resp.get("result", {}).get("hits", [])
        if not hits:
            break
        all_hits.extend(hits)
        collected = len(all_hits)
        time.sleep(0.3)  # rate limit courtesy

    if max_exhibitors:
        all_hits = all_hits[:max_exhibitors]

    print(f"\n[extract] Extracting data from {len(all_hits)} exhibitors …")

    results = []
    for i, hit in enumerate(all_hits, 1):
        row = extract_exhibitor_data(hit, config)

        if fetch_details:
            print(f"  [{i}/{len(all_hits)}] {row['name']} (fetching detail …)")
            row = enrich_with_detail(row, config)
            time.sleep(0.2)  # rate limit courtesy
        else:
            if i % 100 == 0 or i == len(all_hits):
                print(f"  [{i}/{len(all_hits)}] processed")

        results.append(row)

    if not results:
        print("[ERROR] No data was extracted.")
        sys.exit(1)

    # ── save output ──────────────────────────────────────────────────────────
    df = pd.DataFrame(results)

    if fmt == "json":
        path = output_file or "exhibitors.json"
        df.to_json(path, orient="records", indent=2, force_ascii=False)
    elif fmt == "xlsx":
        path = output_file or "exhibitors.xlsx"
        df.to_excel(path, index=False, engine="openpyxl")
    else:
        path = output_file or "exhibitors.csv"
        df.to_csv(path, index=False, encoding="utf-8-sig")

    print(f"\n[done] {len(results)} exhibitors saved → {path}")


# ── CLI ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Messe Frankfurt Exhibitor List Scraper (API-based)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scraper.py --url "https://heimtextil.messefrankfurt.com/frankfurt/en/exhibitor-search.html"
  python scraper.py --url "https://ambiente.messefrankfurt.com/frankfurt/en/exhibitor-search.html" --format xlsx
  python scraper.py --url "https://automechanika.messefrankfurt.com/frankfurt/en/exhibitor-search.html" --max 50
  python scraper.py --url "https://ish.messefrankfurt.com/frankfurt/en/exhibitor-search.html" --details

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
        "--max", type=int, default=None, dest="max_exhibitors",
        help="Maximum number of exhibitors to scrape (default: all)",
    )
    parser.add_argument(
        "--details", action="store_true",
        help="Fetch full detail page for each exhibitor (slower, richer data)",
    )
    parser.add_argument(
        "--query", default="",
        help="Optional search query to filter exhibitors",
    )
    args = parser.parse_args()

    scrape(
        url=args.url,
        output_file=args.output,
        fmt=args.format,
        max_exhibitors=args.max_exhibitors,
        fetch_details=args.details,
        query=args.query,
    )


if __name__ == "__main__":
    main()
