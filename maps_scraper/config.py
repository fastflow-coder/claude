"""
Scraper configuration.
Edit SEARCH_QUERIES and MAX_RESULTS_PER_QUERY to control what gets scraped.
"""

SEARCH_QUERIES: list[str] = [
    "tesisatçı istanbul avrupa yakası",
    "elektrikçi kadıköy",
    "fırın bakırköy",
    "berber beşiktaş",
    "çiçekçi üsküdar",
]

# Google Maps scroll limit is ~120; stay safely below it
MAX_RESULTS_PER_QUERY: int = 60

# Milliseconds between scroll steps (human-like pace)
SCROLL_PAUSE_MS: int = 1800

# Set True for production runs; False lets you watch the browser
HEADLESS: bool = False

# Seconds to wait between different search queries (anti-ban)
INTER_QUERY_DELAY_S: float = 8.0

# How many "stale" scroll rounds before we assume list is exhausted
STALE_ROUNDS_LIMIT: int = 3

# Retry config for transient Playwright errors
MAX_RETRIES: int = 2
RETRY_BASE_DELAY_S: float = 2.0
