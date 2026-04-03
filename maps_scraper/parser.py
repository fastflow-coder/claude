"""
DOM selectors and extraction logic for Google Maps pages.

Keeping selectors in one place means a Maps UI update requires
editing only this file.
"""

import re

from playwright.async_api import Page

# ---------------------------------------------------------------------------
# Selector constants
# ---------------------------------------------------------------------------

NAME_SEL = "h1.DUwDvf"
ADDR_SEL = '[data-item-id="address"]'
PHONE_SEL = '[data-item-id^="phone:tel:"]'
WEBSITE_SEL = '[data-item-id="authority"]'
RATING_SEL = "div.F7nice span[aria-hidden='true']"
REVIEW_COUNT_SEL = "div.F7nice span[aria-label]"
CATEGORY_SEL = "button.DkEaL"

# Feed of result cards in the left panel
FEED_SEL = 'div[role="feed"]'

# Individual place links inside the feed
CARD_SEL = 'a[href*="/maps/place/"]'

# GDPR / cookie consent button (varies by region)
CONSENT_BTNS = [
    'button[aria-label="Tümünü kabul et"]',
    'button[aria-label="Accept all"]',
    'form:nth-child(2) button',
]

_REVIEW_DIGITS_RE = re.compile(r"[\d,\.]+")


async def parse_detail(page: Page) -> dict | None:
    """
    Extract business details from the currently-open right-side detail panel.
    Returns None on critical failure (e.g. name not found).
    """
    try:
        # Business name — required
        name_el = await page.query_selector(NAME_SEL)
        if not name_el:
            return None
        name = (await name_el.inner_text()).strip()
        if not name:
            return None

        # Address
        address = await _text(page, ADDR_SEL)

        # Phone (raw — normalization done in utils.py)
        phone_raw = await _text(page, PHONE_SEL)

        # Website href
        website = ""
        web_el = await page.query_selector(WEBSITE_SEL)
        if web_el:
            website = (await web_el.get_attribute("href") or "").strip()

        # Rating (numeric string like "4,7")
        rating_str = await _text(page, RATING_SEL)
        rating = _parse_rating(rating_str)

        # Review count
        review_count = None
        rc_el = await page.query_selector(REVIEW_COUNT_SEL)
        if rc_el:
            label = await rc_el.get_attribute("aria-label") or ""
            m = _REVIEW_DIGITS_RE.search(label)
            if m:
                review_count = int(m.group().replace(",", "").replace(".", ""))

        # Business category
        category = await _text(page, CATEGORY_SEL)

        # Maps URL (current page URL is the canonical place URL)
        maps_url = page.url

        return {
            "name": name,
            "address": address,
            "phone_raw": phone_raw,
            "website": website,
            "rating": rating,
            "review_count": review_count,
            "category": category,
            "maps_url": maps_url,
        }

    except Exception:
        return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _text(page: Page, selector: str) -> str:
    el = await page.query_selector(selector)
    if el:
        return (await el.inner_text()).strip()
    return ""


def _parse_rating(raw: str) -> float | None:
    if not raw:
        return None
    try:
        return float(raw.replace(",", "."))
    except ValueError:
        return None
