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

# ─── Selenium base config (used for FunPay + FlareSolverr fallback) ────────────
HEADLESS = os.getenv("HEADLESS", "true").lower() == "true"
SELENIUM_TIMEOUT = int(os.getenv("SELENIUM_TIMEOUT", "45"))
PAGE_LOAD_WAIT = int(os.getenv("PAGE_LOAD_WAIT", "15"))

# ─── Legacy Cloudflare retries (Selenium fallback only) ────────────────────────
SCRAPE_RETRIES = int(os.getenv("SCRAPE_RETRIES", "3"))

# ─── Human-like delay defaults ─────────────────────────────────────────────────
MIN_DELAY = float(os.getenv("MIN_DELAY", "1.5"))
MAX_DELAY = float(os.getenv("MAX_DELAY", "4.0"))

# ─── FlareSolverr ──────────────────────────────────────────────────────────────
FLARESOLVERR_URL = os.getenv(
    "FLARESOLVERR_URL",
    "http://flaresolverr:8191",  # Docker service name
)
FLARESOLVERR_TIMEOUT = int(os.getenv("FLARESOLVERR_TIMEOUT", "30"))
FLARESOLVERR_MAX_RETRIES = int(os.getenv("FLARESOLVERR_MAX_RETRIES", "3"))

# ─── Proxy Pool ────────────────────────────────────────────────────────────────
# Comma-separated list of proxy URLs in format: http://user:pass@host:port
# Example: "http://proxy1:8080,http://user:pass@proxy2:3128,socks5://proxy3:1080"
# If empty/FALSE, FlareSolverr will use its own outbound IP (no proxy).
PROXY_LIST = os.getenv("PROXY_LIST", "")

# Number of failures before a proxy is blacklisted
PROXY_BLACKLIST_THRESHOLD = int(os.getenv("PROXY_BLACKLIST_THRESHOLD", "3"))

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

# ─── Output limits ─────────────────────────────────────────────────────────────
TOP_N_PRODUCTS = int(os.getenv("TOP_N_PRODUCTS", "10"))

# ─── Platforms that need Cloudflare bypass ─────────────────────────────────────
CLOUDFLARE_PLATFORMS = {"z2u", "g2g"}

# ─── Proxy Refresher (gfpcom/free-proxy-list) ──────────────────────────────────
PROXY_SOURCE_URLS = os.getenv(
    "PROXY_SOURCE_URLS",
    "https://raw.githubusercontent.com/gfpcom/free-proxy-list/main/proxies.txt,"
    "https://raw.githubusercontent.com/gfpcom/free-proxy-list/main/proxy-list-http.txt",
)
PROXY_REFRESH_INTERVAL = int(os.getenv("PROXY_REFRESH_INTERVAL", "15"))
MAX_VERIFIED_PROXIES = int(os.getenv("MAX_VERIFIED_PROXIES", "30"))
PROXY_TEST_TIMEOUT = int(os.getenv("PROXY_TEST_TIMEOUT", "10"))
PROXY_TEST_WORKERS = int(os.getenv("PROXY_TEST_WORKERS", "20"))
VERIFIED_PROXIES_PATH = os.getenv(
    "VERIFIED_PROXIES_PATH", "/app/data/verified_proxies.json"
)