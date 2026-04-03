"""
Async website technical analysis.

Runs up to ANALYSIS_CONCURRENCY requests in parallel using asyncio + httpx.
Extracts: load time, HTTPS, meta tags, mobile viewport, email, copyright year.
"""

import asyncio
import re
import time
from typing import Any

import httpx
from bs4 import BeautifulSoup

from lead_qualifier.config import (
    ANALYSIS_CONCURRENCY,
    EMAIL_EXCLUDE_DOMAINS,
    HTTP_TIMEOUT_S,
)

_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
_YEAR_RE = re.compile(r"20[12]\d")

_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; LeadQualifier/1.0)"}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def analyze_all(businesses: list[dict]) -> list[dict]:
    """
    Analyze each business's website concurrently.
    Returns a list of analysis dicts (same order as input).
    """
    sem = asyncio.Semaphore(ANALYSIS_CONCURRENCY)
    async with httpx.AsyncClient(
        timeout=HTTP_TIMEOUT_S,
        follow_redirects=True,
        headers=_HEADERS,
    ) as client:
        tasks = [_analyze_one(sem, client, biz) for biz in businesses]
        return await asyncio.gather(*tasks)


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


async def _analyze_one(
    sem: asyncio.Semaphore,
    client: httpx.AsyncClient,
    biz: dict,
) -> dict:
    async with sem:
        url = biz.get("website", "")
        result = _empty_result(biz["id"], url)
        if not url:
            return result

        try:
            t0 = time.monotonic()
            resp = await client.get(url)
            result["load_time_ms"] = int((time.monotonic() - t0) * 1000)
            result["reachable"] = resp.status_code < 400
            result["is_https"] = str(resp.url).startswith("https")

            html = resp.text
            soup = BeautifulSoup(html, "lxml")
            body_text = soup.get_text(" ", strip=True)

            result["has_meta_description"] = _has_meta(soup, "description")
            result["has_viewport"] = _has_meta(soup, "viewport")
            result["has_phone"] = _has_turkish_phone(body_text)
            result["copyright_year"] = _latest_year(body_text)
            result["email"] = _extract_email(html + " " + body_text)
            result["html_snippet"] = body_text[:1500]

        except (httpx.RequestError, httpx.HTTPStatusError) as exc:
            result["error"] = str(exc)

        return result


def _empty_result(biz_id: int, url: str) -> dict:
    return {
        "biz_id": biz_id,
        "url": url,
        "reachable": False,
        "load_time_ms": None,
        "is_https": url.startswith("https") if url else False,
        "has_meta_description": False,
        "has_viewport": False,
        "has_phone": False,
        "copyright_year": None,
        "email": "",
        "html_snippet": "",
        "error": None,
    }


def _has_meta(soup: Any, name: str) -> bool:
    el = soup.find("meta", attrs={"name": name})
    return bool(el and el.get("content"))


def _has_turkish_phone(text: str) -> bool:
    return any(prefix in text for prefix in ("0212", "0216", "0850", "0532", "+90"))


def _latest_year(text: str) -> int | None:
    years = _YEAR_RE.findall(text)
    return max(int(y) for y in years) if years else None


def _extract_email(text: str) -> str:
    for match in _EMAIL_RE.findall(text):
        domain = match.split("@")[1].lower()
        if domain not in EMAIL_EXCLUDE_DOMAINS:
            return match.lower()
    return ""
