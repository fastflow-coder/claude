import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///bodega_burger.db")
RECEIPT_IMAGES_DIR = os.getenv("RECEIPT_IMAGES_DIR", "receipt_images")
WEB_HOST = os.getenv("WEB_HOST", "0.0.0.0")
WEB_PORT = int(os.getenv("WEB_PORT", "8000"))

# AI Models
VISION_MODEL = "claude-sonnet-4-6"          # Receipt OCR — vision capable
CHAT_MODEL = "claude-haiku-4-5-20251001"    # Text responses — cheapest

# Ensure receipt images directory exists
Path(RECEIPT_IMAGES_DIR).mkdir(parents=True, exist_ok=True)
