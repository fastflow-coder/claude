"""
Playwright-based Google Maps crawler.

For each query:
  1. Navigate to maps/search/<query>
  2. Handle GDPR consent if present
  3. Scroll the results feed until max_results or list end
  4. Click each card → extract detail panel via parser.py
  5. Return list[dict]
"""

import asyncio
import random
from typing import Any

from playwright.async_api import BrowserContext, Page, async_playwright

from maps_scraper import config, parser
from maps_scraper.utils import content_hash, normalize_phone, validate_url

# Random viewport pool — avoids a fixed fingerprint
_VIEWPORTS = [
    {"width": 1280, "height": 900},
    {"width": 1366, "height": 768},
    {"width": 1440, "height": 900},
    {"width": 1536, "height": 864},
]

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


async def scrape_query(query: str, max_results: int | None = None) -> list[dict]:
    """
    Scrape Google Maps for *query* and return up to *max_results* businesses.
    Falls back to config.MAX_RESULTS_PER_QUERY if max_results is None.
    """
    if max_results is None:
        max_results = config.MAX_RESULTS_PER_QUERY

    results: list[dict] = []

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=config.HEADLESS,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ],
        )
        context = await _make_context(browser)
        page = await context.new_page()

        try:
            url = f"https://www.google.com/maps/search/{query.replace(' ', '+')}"
            await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            await _random_delay(2, 4)

            await _accept_consent(page)

            await page.wait_for_selector(parser.FEED_SEL, timeout=15_000)

            results = await _scroll_and_collect(page, query, max_results)

        except Exception as exc:
            print(f"  [scraper] Fatal error for '{query}': {exc}")
        finally:
            await browser.close()

    return results


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


async def _make_context(browser: Any) -> BrowserContext:
    viewport = random.choice(_VIEWPORTS)
    return await browser.new_context(
        user_agent=_UA,
        viewport=viewport,
        locale="tr-TR",
        timezone_id="Europe/Istanbul",
    )


async def _accept_consent(page: Page) -> None:
    """Click through GDPR/cookie consent dialogs if present."""
    for sel in parser.CONSENT_BTNS:
        try:
            btn = await page.query_selector(sel)
            if btn and await btn.is_visible():
                await _human_click(page, btn)
                await _random_delay(1, 2)
                return
        except Exception:
            continue


async def _scroll_and_collect(
    page: Page, query: str, max_results: int
) -> list[dict]:
    results: list[dict] = []
    seen_hrefs: set[str] = set()
    stale_rounds = 0

    while len(results) < max_results:
        cards = await page.query_selector_all(parser.CARD_SEL)

        # Filter to cards we haven't processed yet
        new_cards = []
        for card in cards:
            href = await card.get_attribute("href") or ""
            if href not in seen_hrefs:
                seen_hrefs.add(href)
                new_cards.append(card)

        if not new_cards:
            stale_rounds += 1
            if stale_rounds >= config.STALE_ROUNDS_LIMIT:
                break
        else:
            stale_rounds = 0

        for card in new_cards:
            if len(results) >= max_results:
                break

            data = await _extract_card(page, card, query)
            if data:
                results.append(data)
                print(
                    f"  [+] {data['name']}"
                    + (f" | {data['phone']}" if data.get("phone") else "")
                )

        # Scroll the feed panel down
        await page.evaluate(
            f"document.querySelector('{parser.FEED_SEL}').scrollBy(0, 800)"
        )
        await _random_delay(
            config.SCROLL_PAUSE_MS / 1000 * 0.8,
            config.SCROLL_PAUSE_MS / 1000 * 1.2,
        )

    return results


async def _extract_card(page: Page, card: Any, query: str) -> dict | None:
    """Click a card, wait for the detail panel, parse it."""
    for attempt in range(config.MAX_RETRIES + 1):
        try:
            await _human_click(page, card)
            await _random_delay(1.5, 3.0)

            data = await parser.parse_detail(page)
            if not data:
                return None

            # Enrich with utils
            phone_raw = data.pop("phone_raw", "")
            data["phone_raw"] = phone_raw
            data["phone"] = normalize_phone(phone_raw)
            data["website"] = validate_url(data.get("website", "")) or ""
            data["query"] = query
            data["content_hash"] = content_hash(
                data["name"], data.get("address", "")
            )
            return data

        except Exception as exc:
            if attempt == config.MAX_RETRIES:
                print(f"  [-] Skipping card after {attempt + 1} attempts: {exc}")
                return None
            await asyncio.sleep(config.RETRY_BASE_DELAY_S * (attempt + 1))

    return None


async def _human_click(page: Page, element: Any) -> None:
    """Move mouse to element before clicking (humanized)."""
    box = await element.bounding_box()
    if box:
        # Move to a random point inside the element
        x = box["x"] + random.uniform(box["width"] * 0.2, box["width"] * 0.8)
        y = box["y"] + random.uniform(box["height"] * 0.2, box["height"] * 0.8)
        await page.mouse.move(x, y)
        await _random_delay(0.05, 0.2)
    await element.click()


async def _random_delay(lo: float, hi: float) -> None:
    await asyncio.sleep(random.uniform(lo, hi))
