"""
Phase 2: Stealth Deep-Scraping & Product Normalization

For each qualified overlapping category, scrape product listings using the
best available method per platform:

  - Z2U, G2G → FlareSolverr (Cloudflare bypass, rotating proxies)
  - FunPay   → SeleniumBase (direct, no blocking)

Each method falls back to the other on failure.
"""

import logging
import random
import re
import time
from typing import Optional, Callable

from bs4 import BeautifulSoup
from seleniumbase import Driver as SeleniumBaseDriver
from selenium.common.exceptions import (
    TimeoutException,
    NoSuchElementException,
    WebDriverException,
)

from config import (
    HEADLESS, SELENIUM_TIMEOUT, MIN_DELAY, MAX_DELAY,
    PLATFORMS, TOP_N_PRODUCTS, SCRAPE_RETRIES, PAGE_LOAD_WAIT,
    CLOUDFLARE_PLATFORMS,
)
from flaresolverr_client import get_flaresolverr_client, FlareSolverrError
from utils.pricing import parse_quantity, compute_unit_price, extract_item_type
from matcher import Category
from stealth import (
    StealthConfig,
    create_stealth_driver,
    navigate_with_stealth,
    human_delay,
)

logger = logging.getLogger(__name__)


# ─── CSS Selectors per platform ──────────────────────────────────────────────

PLATFORM_SELECTORS = {
    "z2u": {
        "containers": [
            "[class*='product']", "[class*='listing']", "[class*='item']",
            ".goods-item", ".product-item", "tr[class*='goods']",
            "div[class*='card']:has([class*='price'])",
            "tbody tr", ".list-view > div", "[class*='row']",
        ],
        "title": [
            "a[href*='/goods/']", "a[class*='title']",
            "[class*='name'] a", "[class*='title'] a", "h3 a", "h4 a",
            "a[href*='/detail/']", "a",
        ],
        "price": [
            "[class*='price']", ".amount", ".cost",
            "[class*='money']", "span[class*='usd']", "span[class*='dollar']",
        ],
    },
    "g2g": {
        "containers": [
            ".product-card", ".offer-card", ".listing-card",
            "div[class*='product']", "div[class*='offer']",
            "div[class*='card']:has([class*='price'])",
            "div[class*='grid'] > div",
            ".list-view > div", "[class*='items'] > div",
        ],
        "title": [
            "a[class*='title']", "[class*='name'] a",
            "h3 a", "h4 a", "[class*='product-title'] a",
            "a[href]",
        ],
        "price": [
            "[class*='price']", ".amount", ".cost",
            "[class*='money']", "[data-price]", "span[class*='usd']",
        ],
    },
    "funpay": {
        "containers": [
            ".lot-item", ".offer-item", ".listing-item",
            "tr[class*='lot']", "div[class*='lot']",
            "div[class*='offer']", "[class*='product']",
            "tbody tr", ".table > div", ".items-list > div",
        ],
        "title": [
            "a[class*='title']", ".lot-title a", ".item-title a",
            "h3 a", "h4 a", "[class*='name'] a", "a",
        ],
        "price": [
            "[class*='price']", ".amount", ".cost",
            "span[class*='money']", "[class*='usd']",
        ],
    },
}


# ─── HTML parsing helper ─────────────────────────────────────────────────────


def _extract_listings_from_html(
    html: str,
    platform: str,
    limit: int = 50,
) -> list[dict]:
    """
    Parse product listings from raw HTML using platform-specific CSS selectors.
    Shared between FlareSolverr and Selenium code paths.
    """
    selectors = PLATFORM_SELECTORS.get(platform, PLATFORM_SELECTORS["z2u"])
    soup = BeautifulSoup(html, "html.parser")

    # Build selector string
    container_selector = ", ".join(selectors["containers"])
    title_selector = ", ".join(selectors["title"])
    price_selector = ", ".join(selectors["price"])

    item_cards = soup.select(container_selector)
    logger.debug("Found %d potential item containers on %s", len(item_cards), platform)

    listings = []
    for card in item_cards[:limit]:
        title_el = card.select_one(title_selector)
        price_el = card.select_one(price_selector)
        url_el = title_el if title_el else card.select_one("a[href]")

        title = title_el.get_text(strip=True) if title_el else ""
        price_text = price_el.get_text(strip=True) if price_el else ""
        url = url_el.get("href", "") if url_el else ""

        if not title or not price_text:
            continue

        price = parse_price_text(price_text)
        if price is None:
            continue

        if url and not url.startswith("http"):
            url = f"{PLATFORMS[platform]}{url}"

        listings.append({"title": title, "price_usd": price, "url": url})

    return listings


# ─── FlareSolverr-based listing scraping (Z2U, G2G) ──────────────────────────


def _scrape_via_flaresolverr(
    category: Category,
    platform: str,
) -> list[dict]:
    """
    Scrape product listings via FlareSolverr.
    Retries with different proxies, then falls back to Selenium.
    """
    logger.info("Scraping %s category via FlareSolverr: %s", platform, category.name)

    # Try FlareSolverr
    client = get_flaresolverr_client()
    if client.is_available():
        try:
            html = client.fetch_html(
                category.url,
                platform=platform,
                use_proxy=True,
                session_ttl_minutes=3,
            )
            if html:
                # Check if FlareSolverr returned a challenge page
                if "challenge" in html.lower()[:2000]:
                    logger.warning("FlareSolverr returned challenge page for %s. May need proxy refresh.", platform)
                else:
                    listings = _extract_listings_from_html(html, platform)
                    logger.info(
                        "FlareSolverr returned %d listings from %s / %s",
                        len(listings), platform, category.name,
                    )
                    return listings
        except (FlareSolverrError, Exception) as e:
            logger.warning("FlareSolverr failed for %s / %s: %s", platform, category.name, e)
    else:
        logger.warning("FlareSolverr not available for %s / %s", platform, category.name)

    # Fallback: Selenium
    logger.info("Falling back to Selenium for %s / %s...", platform, category.name)
    return _scrape_via_selenium(category, platform)


# ─── Selenium-based listing scraping (FunPay + fallback) ─────────────────────


def _scrape_via_selenium(
    category: Category,
    platform: str,
    retry_count: int = 0,
) -> list[dict]:
    """
    Scrape product listings using SeleniumBase in undetected mode.
    Primary method for FunPay; fallback for Z2U/G2G.
    """
    logger.info(
        "Scraping %s via Selenium%s: %s",
        platform,
        f" (retry {retry_count}/{SCRAPE_RETRIES})" if retry_count > 0 else "",
        category.name,
    )

    driver = create_stealth_driver(StealthConfig())
    try:
        navigate_with_stealth(driver, category.url, platform, extra_delay=retry_count * 2)

        html = driver.page_source

        # Check for Cloudflare challenge
        if _is_cloudflare_challenge(html):
            if retry_count < SCRAPE_RETRIES:
                wait = 5 * (retry_count + 1)
                logger.warning("Cloudflare on %s. Waiting %ds before retry %d/%d...",
                               platform, wait, retry_count + 1, SCRAPE_RETRIES)
                time.sleep(wait)
                return _scrape_via_selenium(category, platform, retry_count + 1)
            else:
                logger.error("Max Selenium retries for %s / %s", platform, category.name)
                return []

        listings = _extract_listings_from_html(html, platform)
        logger.info("Selenium returned %d listings from %s / %s",
                    len(listings), platform, category.name)
        return listings

    finally:
        try:
            driver.quit()
        except Exception:
            pass


def _is_cloudflare_challenge(html: str) -> bool:
    """Check if HTML looks like a Cloudflare challenge page."""
    lower = html.lower()
    return (
        "challenge" in lower[:3000] or
        "cf-browser-verification" in lower[:3000] or
        "just a moment" in lower[:2000]
    )


# ─── Price parsing ───────────────────────────────────────────────────────────


def parse_price_text(price_text: str) -> Optional[float]:
    """Parse price text to USD float."""
    cleaned = price_text.replace("$", "").replace("€", "").replace("£", "")
    cleaned = re.sub(r"(?i)\s*(usd|eur|gbp|€|£)\s*", "", cleaned)
    cleaned = cleaned.replace(",", ".").strip()
    cleaned = re.sub(r"[^\d.]", "", cleaned)
    try:
        value = float(cleaned)
        return value if value > 0 and value < 1_000_000 else None
    except (ValueError, TypeError):
        return None


# ─── Platform router ─────────────────────────────────────────────────────────


def scrape_category(driver: SeleniumBaseDriver, category: Category, platform: str) -> list[dict]:
    """
    Route scraping to the correct method per platform.

    Note: 'driver' param is kept for interface compatibility with the orchestrator.
    Z2U/G2G ignore it and use FlareSolverr; FunPay uses it.
    """
    if platform in CLOUDFLARE_PLATFORMS:
        return _scrape_via_flaresolverr(category, platform)
    else:
        return _scrape_via_selenium(category, platform)


# ─── Listing processing ──────────────────────────────────────────────────────


def process_listings(
    raw_listings: list[dict],
    platform: str,
    category_name: str,
) -> list[dict]:
    """Process raw scraped listings into normalized products with unit pricing."""
    processed = []
    for raw in raw_listings:
        title = raw["title"]
        price_usd = raw["price_usd"]
        url = raw.get("url", "")

        unit_price, quantity = compute_unit_price(price_usd, title)
        item_type = extract_item_type(title)

        processed.append({
            "platform": platform,
            "category": category_name,
            "item_type": item_type,
            "title": title,
            "price_usd": round(price_usd, 4),
            "unit_price": round(unit_price, 6),
            "quantity": round(quantity, 2),
            "url": url,
        })
    return processed


# ─── Deep scrape orchestrator ────────────────────────────────────────────────


def deep_scrape_categories(
    qualified_categories: list[tuple[str, int, list[Category]]],
) -> list[dict]:
    """
    Perform deep scraping for all qualified overlapping categories.

    Z2U/G2G categories are scraped via FlareSolverr (no Selenium driver needed).
    FunPay categories use Selenium (requires driver creation inside the loop).
    """
    all_products = []

    for norm_name, platform_count, categories in qualified_categories:
        logger.info("=== Deep scraping category: %s (on %d platforms) ===",
                    norm_name, platform_count)

        # Separate cloudflare vs direct platforms
        flare_cats = [c for c in categories if c.platform in CLOUDFLARE_PLATFORMS]
        direct_cats = [c for c in categories if c.platform not in CLOUDFLARE_PLATFORMS]

        # FlareSolverr categories (Z2U, G2G) — no Selenium driver needed
        for cat in flare_cats:
            try:
                human_delay(1.0, 2.5)
                raw = _scrape_via_flaresolverr(cat, cat.platform)
                processed = process_listings(raw, cat.platform, norm_name)
                all_products.extend(processed)
                logger.info("Scraped %d products from %s / %s",
                            len(processed), cat.platform, cat.name)
            except Exception as e:
                logger.error("Error scraping %s / %s: %s", cat.platform, cat.name, e)
                continue

        # Direct Selenium categories (FunPay)
        if direct_cats:
            driver = create_stealth_driver(StealthConfig())
            try:
                for cat in direct_cats:
                    try:
                        human_delay(1.0, 2.0)
                        raw = _scrape_via_selenium(cat, cat.platform)
                        processed = process_listings(raw, cat.platform, norm_name)
                        all_products.extend(processed)
                        logger.info("Scraped %d products from %s / %s",
                                    len(processed), cat.platform, cat.name)
                    except Exception as e:
                        logger.error("Error scraping %s / %s: %s",
                                     cat.platform, cat.name, e)
                        continue
            finally:
                try:
                    driver.quit()
                except Exception:
                    pass

        # Inter-category delay
        human_delay(2.0, 5.0)

    logger.info("Deep scrape complete. Total products: %d", len(all_products))
    return all_products