"""
Shared helpers: phone normalization, URL validation, content hashing.
"""

import hashlib
import re
from urllib.parse import urlparse

# ---------------------------------------------------------------------------
# Phone normalization
# ---------------------------------------------------------------------------

_DIGITS_RE = re.compile(r"\D")


def normalize_phone(raw: str) -> str:
    """
    Standardize Turkish phone numbers to +90XXXXXXXXXX format.
    Returns the raw string unchanged if it doesn't match a known pattern.
    """
    if not raw:
        return raw
    digits = _DIGITS_RE.sub("", raw)
    if digits.startswith("0") and len(digits) == 11:
        return f"+90{digits[1:]}"
    if digits.startswith("90") and len(digits) == 12:
        return f"+{digits}"
    # Already +90... or foreign number — return as-is
    return raw.strip()


# ---------------------------------------------------------------------------
# URL validation
# ---------------------------------------------------------------------------


def validate_url(url: str) -> str | None:
    """
    Return a cleaned URL (with scheme) or None if it looks invalid.
    Maps sometimes returns relative paths or bare domains.
    """
    if not url:
        return None
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    try:
        parsed = urlparse(url)
        if parsed.netloc and "." in parsed.netloc:
            return url
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Deduplication hash
# ---------------------------------------------------------------------------


def content_hash(name: str, address: str) -> str:
    """
    16-char sha256 fingerprint of (name, address) for cross-query dedup.
    Case- and whitespace-insensitive.
    """
    raw = f"{name.lower().strip()}|{address.lower().strip()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]
