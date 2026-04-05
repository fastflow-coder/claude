"""
AI Receipt Parser for Bodega Burger
- Receipt OCR:       claude-sonnet-4-6  (vision capable)
- Chat responses:    claude-haiku-4-5-20251001 (cheapest)
"""
from __future__ import annotations

import base64
import json
import re
from pathlib import Path
from typing import Optional

import anthropic

from config import ANTHROPIC_API_KEY, CHAT_MODEL, VISION_MODEL

_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

_MEDIA_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
}

_RECEIPT_PROMPT = """Analyze this receipt image and extract ALL information as valid JSON only.
Do NOT include markdown fences, comments, or any text outside the JSON object.

Return exactly this structure:
{
  "vendor": "store or supplier name",
  "date": "YYYY-MM-DD or null",
  "items": [
    {
      "name": "item name exactly as printed on receipt",
      "quantity": 1.0,
      "unit_price": 0.00,
      "total_price": 0.00,
      "stock_category": "meat|bread|produce|dairy|supplies|beverages|other"
    }
  ],
  "subtotal": 0.00,
  "tax": 0.00,
  "total": 0.00,
  "category": "food|beverage|supplies|utilities|other"
}

Rules:
- Keep item names exactly as they appear on the receipt — do NOT translate or modify them
- stock_category must be one of: meat, bread, produce, dairy, supplies, beverages, other
- category (top-level) must be one of: food, beverage, supplies, utilities, other
- Use null for any field you cannot determine
- All numeric values must be numbers (not strings)
"""


def parse_receipt_image(image_path: str) -> tuple[dict, str]:
    """
    Parse a receipt image with claude-sonnet-4-6.
    Returns (parsed_dict, raw_response_text).
    Raises ValueError if JSON cannot be extracted.
    """
    path = Path(image_path)
    media_type = _MEDIA_TYPES.get(path.suffix.lower(), "image/jpeg")
    image_data = base64.standard_b64encode(path.read_bytes()).decode()

    response = _client.messages.create(
        model=VISION_MODEL,
        max_tokens=2000,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": image_data,
                    },
                },
                {"type": "text", "text": _RECEIPT_PROMPT},
            ],
        }],
    )

    raw_text = response.content[0].text
    parsed = _extract_json(raw_text)
    parsed["raw_text"] = raw_text
    return parsed, raw_text


def _extract_json(text: str) -> dict:
    """Strip markdown fences and parse JSON from Claude's response."""
    cleaned = text.strip()
    # Remove ```json ... ``` or ``` ... ``` fences
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    cleaned = cleaned.strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        # Try to find the first {...} block
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            return json.loads(match.group())
        raise ValueError(f"Could not parse JSON from response: {cleaned[:200]}")


def generate_chat_response(system_context: str, user_message: str) -> str:
    """
    Generate a conversational reply with claude-haiku-4-5-20251001.
    Used for bot command responses, help text, etc.
    """
    response = _client.messages.create(
        model=CHAT_MODEL,
        max_tokens=500,
        system=(
            "You are a helpful assistant for Bodega Burger, a burger restaurant in Toronto, Canada. "
            "Be concise and professional. "
            + system_context
        ),
        messages=[{"role": "user", "content": user_message}],
    )
    return response.content[0].text


def format_receipt_summary(parsed: dict) -> str:
    """Format parsed receipt data into a readable Telegram message (HTML)."""
    vendor = parsed.get("vendor") or "Unknown vendor"
    date = parsed.get("date") or "Unknown date"
    total = parsed.get("total") or 0
    tax = parsed.get("tax") or 0
    category = parsed.get("category") or "other"
    items = parsed.get("items") or []

    lines = [
        f"<b>Receipt Processed</b>",
        f"Vendor: <b>{vendor}</b>",
        f"Date: {date}",
        f"Category: {category}",
        "",
        "<b>Items:</b>",
    ]

    for item in items:
        name = item.get("name", "?")
        qty = item.get("quantity", 1)
        price = item.get("total_price", 0)
        lines.append(f"  • {name} x{qty} — ${price:.2f}")

    lines += [
        "",
        f"Tax: ${float(tax):.2f}",
        f"<b>Total: ${float(total):.2f}</b>",
        "",
        "Stock updated.",
    ]

    return "\n".join(lines)
