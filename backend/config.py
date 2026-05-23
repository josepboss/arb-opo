"""
Application configuration for the Multi-Marketplace Arbitrage Engine.
All values are overridable via environment variables.
"""
import os
from pathlib import Path

# ─── Project paths ─────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent
DB_PATH = os.getenv("ARBITRAGE_DB_PATH", str(BASE_DIR / "arbitrage.db"))

# ─── Server config ─────────────────────────────────────────────────────────────
HOST = os.getenv("ARBITRAGE_HOST", "0.0.0.0")
PORT = int(os.getenv("ARBITRAGE_PORT", "2105"))

# ─── Scraping schedule ─────────────────────────────────────────────────────────
SCRAPE_INTERVAL_MINUTES = int(os.getenv("SCRAPE_INTERVAL_MINUTES", "30"))

# ─── Selenium base config ──────────────────────────────────────────────────────
HEADLESS = os.getenv("HEADLESS", "true").lower() == "true"
SELENIUM_TIMEOUT = int(os.getenv("SELENIUM_TIMEOUT", "45"))
PAGE_LOAD_WAIT = int(os.getenv("PAGE_LOAD_WAIT", "15"))

# ─── Cloudflare challenge retries ──────────────────────────────────────────────
SCRAPE_RETRIES = int(os.getenv("SCRAPE_RETRIES", "3"))

# ─── Human-like delay defaults (fallback; per-platform overrides in stealth.py) ─
MIN_DELAY = float(os.getenv("MIN_DELAY", "1.5"))
MAX_DELAY = float(os.getenv("MAX_DELAY", "4.0"))

# ─── Platform base URLs ────────────────────────────────────────────────────────
PLATFORMS = {
    "z2u": os.getenv("Z2U_BASE_URL", "https://www.z2u.com"),
    "funpay": os.getenv("FUNPAY_BASE_URL", "https://funpay.com"),
    "g2g": os.getenv("G2G_BASE_URL", "https://www.g2g.com"),
}

CATEGORY_URLS = {
    "z2u": f"{PLATFORMS['z2u']}/categories",
    "funpay": f"{PLATFORMS['funpay']}/categories",
    "g2g": f"{PLATFORMS['g2g']}/categories",
}

# ─── Proxy (optional) ──────────────────────────────────────────────────────────
PROXY = os.getenv("ARBITRAGE_PROXY", None)

# ─── Output limits ─────────────────────────────────────────────────────────────
TOP_N_PRODUCTS = int(os.getenv("TOP_N_PRODUCTS", "10"))