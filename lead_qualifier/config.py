"""
Lead qualifier configuration.
"""

# Path to the SQLite database written by maps_scraper
DB_PATH: str = "output/leads.db"

# Concurrent HTTP connections for site analysis
ANALYSIS_CONCURRENCY: int = 6

# HTTP timeout per site (seconds)
HTTP_TIMEOUT_S: float = 10.0

# Ollama endpoint and model
OLLAMA_URL: str = "http://localhost:11434/api/generate"
OLLAMA_MODEL: str = "llama3"  # swap for mistral, phi3, etc.
OLLAMA_TIMEOUT_S: float = 45.0

# Minimum website_score to include in the priority export
PRIORITY_SCORE_THRESHOLD: int = 40

# Noisy email domains to exclude from extraction
EMAIL_EXCLUDE_DOMAINS: set[str] = {
    "example.com",
    "sentry.io",
    "w3.org",
    "schema.org",
    "google.com",
    "facebook.com",
    "instagram.com",
    "twitter.com",
}

# Output paths
PRIORITY_CSV: str = "output/priority_leads.csv"
PRIORITY_XLSX: str = "output/priority_leads.xlsx"
PRIORITY_JSON: str = "output/priority_leads.json"
