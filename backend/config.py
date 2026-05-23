"""
Application configuration for the Multi-Marketplace Arbitrage Engine.
"""
import os
from pathlib import Path

# Project paths
BASE_DIR = Path(__file__).resolve().parent
DB_PATH = os.getenv("ARBITRAGE_DB_PATH", str(BASE_DIR / "arbitrage.db"))

# Server config
HOST = os.getenv("ARBITRAGE_HOST", "0.0.0.0")
PORT = int(os.getenv("ARBITRAGE_PORT", "2105"))

# Scraping schedule (in minutes)
SCRAPE_INTERVAL_MINUTES = int(os.getenv("SCRAPE_INTERVAL_MINUTES", "30"))

# Selenium config
HEADLESS = os.getenv("HEADLESS", "true").lower() == "true"
SELENIUM_TIMEOUT = int(os.getenv("SELENIUM_TIMEOUT", "30"))

# Human-like delays (seconds)
MIN_DELAY = float(os.getenv("MIN_DELAY", "1.5"))
MAX_DELAY = float(os.getenv("MAX_DELAY", "4.0"))

# Platform base URLs
PLATFORMS = {
    "z2u": os.getenv("Z2U_BASE_URL", "https://www.z2u.com"),
    "funpay": os.getenv("FUNPAY_BASE_URL", "https://funpay.com"),
    "g2g": os.getenv("G2G_BASE_URL", "https://www.g2g.com"),
}

# Category discovery URLs
CATEGORY_URLS = {
    "z2u": f"{PLATFORMS['z2u']}/categories",
    "funpay": f"{PLATFORMS['funpay']}/categories",
    "g2g": f"{PLATFORMS['g2g']}/categories",
}

# Proxy configuration (optional)
PROXY = os.getenv("ARBITRAGE_PROXY", None)

# Max products to retain per item type group
TOP_N_PRODUCTS = int(os.getenv("TOP_N_PRODUCTS", "10"))