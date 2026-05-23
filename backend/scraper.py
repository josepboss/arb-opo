"""
Phase 2: Stealth Deep-Scraping & Product Normalization

For each qualified overlapping category, perform deep scraping of product listings
using SeleniumBase in undetected mode with enhanced stealth:
- Per-platform delay profiles (Cloudflare sites get longer delays)
- Human-like scroll & mouse simulation
- Progressive backoff on failure
- Realistic browser fingerprint randomization per session
"""

import logging
import random
import re
import time
from typing import Optional

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
)
from utils.pricing import parse_quantity, compute_unit_price, extract_item_type
from utils.normalize import normalize_game_title, resolve_alias
from matcher import Category
from stealth import (
    StealthConfig,
    create_stealth_driver,
    navigate_with_stealth,
    human_delay,
    simulate_human_scroll,
    get_platform_delay,
)

logger = logging.getLogger(__name__)


def scrape_z2u_listings(driver: SeleniumBaseDriver, category: Category, retry_count: int = 0) -> list[dict]:
    """
    Scrape product listings from Z2U for a given category.
    Uses stealth navigation with Cloudflare-appropriate delays.
    """
    logger.info("Scraping Z2U category: %s (%s)", category.name, category.url)

    # Use enhanced stealth navigation
    navigate_with_stealth(driver, category.url, "z2u", extra_delay=retry_count * 2)

    soup = BeautifulSoup(driver.page_source, "html.parser")

    # Check for Cloudflare challenge page
    if "challenge" in driver.page_source.lower() or "cf-browser-verification" in driver.page_source:
        logger.warning("Cloudflare challenge detected on Z2U. Retrying with longer delay...")
        if retry_count < SCRAPE_RETRIES:
            extra_wait = 5 * (retry_count + 1)
            logger.info("Waiting %d seconds before retry %d/%d...", extra_wait, retry_count + 1, SCRAPE_RETRIES)
            time.sleep(extra_wait)
            # Refresh with new stealth config
            return scrape_z2u_listings(driver, category, retry_count + 1)
        else:
            logger.error("Max retries reached for Z2U category: %s", category.name)
            return []

    listings = []
    item_cards = soup.select(
        "[class*='product'], [class*='listing'], [class*='item'], "
        ".goods-item, .product-item, tr[class*='goods'], "
        "div[class*='card']:has([class*='price'])"
    )

    if not item_cards:
        item_cards = soup.select("tbody tr, .list-view > div, [class*='row']")

    logger.debug("Found %d potential item containers on Z2U", len(item_cards))

    for card in item_cards[:50]:
        title_el = card.select_one(
            "a[href*='/goods/'], a[class*='title'], "
            "[class*='name'] a, [class*='title'] a, h3 a, h4 a, "
            "a[href*='/detail/']"
        )
        if not title_el:
            title_el = card.select_one("a")

        price_el = card.select_one(
            "[class*='price'], .amount, .cost, "
            "[class*='money'], span[class*='usd'], span[class*='dollar']"
        )

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
            url = f"{PLATFORMS['z2u']}{url}"

        listings.append({"title": title, "price_usd": price, "url": url})

    logger.info("Scraped %d listings from Z2U / %s", len(listings), category.name)
    return listings


def scrape_funpay_listings(driver: SeleniumBaseDriver, category: Category, retry_count: int = 0) -> list[dict]:
    """
    Scrape product listings from FunPay for a given category.
    """
    logger.info("Scraping FunPay category: %s (%s)", category.name, category.url)
    navigate_with_stealth(driver, category.url, "funpay", extra_delay=retry_count * 1.5)

    soup = BeautifulSoup(driver.page_source, "html.parser")

    if "challenge" in driver.page_source.lower() or "cf-browser-verification" in driver.page_source:
        logger.warning("Cloudflare challenge detected on FunPay. Retrying...")
        if retry_count < SCRAPE_RETRIES:
            extra_wait = 5 * (retry_count + 1)
            time.sleep(extra_wait)
            return scrape_funpay_listings(driver, category, retry_count + 1)
        else:
            logger.error("Max retries reached for FunPay category: %s", category.name)
            return []

    listings = []
    item_cards = soup.select(
        ".lot-item, .offer-item, .listing-item, "
        "tr[class*='lot'], div[class*='lot'], "
        "div[class*='offer'], [class*='product']"
    )

    if not item_cards:
        item_cards = soup.select("tbody tr, .table > div, .items-list > div")

    logger.debug("Found %d potential item containers on FunPay", len(item_cards))

    for card in item_cards[:50]:
        title_el = card.select_one(
            "a[class*='title'], .lot-title a, .item-title a, "
            "h3 a, h4 a, [class*='name'] a"
        )
        if not title_el:
            title_el = card.select_one("a")

        price_el = card.select_one(
            "[class*='price'], .amount, .cost, "
            "span[class*='money'], [class*='usd']"
        )

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
            url = f"{PLATFORMS['funpay']}{url}"

        listings.append({"title": title, "price_usd": price, "url": url})

    logger.info("Scraped %d listings from FunPay / %s", len(listings), category.name)
    return listings


def scrape_g2g_listings(driver: SeleniumBaseDriver, category: Category, retry_count: int = 0) -> list[dict]:
    """
    Scrape product listings from G2G for a given category.
    G2G has the most aggressive protection (Cloudflare + Qrator), so delays are longest.
    """
    logger.info("Scraping G2G category: %s (%s)", category.name, category.url)
    navigate_with_stealth(driver, category.url, "g2g", extra_delay=retry_count * 3)

    soup = BeautifulSoup(driver.page_source, "html.parser")

    if "challenge" in driver.page_source.lower() or "cf-browser-verification" in driver.page_source:
        logger.warning("Cloudflare challenge detected on G2G. Retrying with longer delay...")
        if retry_count < SCRAPE_RETRIES:
            extra_wait = 8 * (retry_count + 1)
            logger.info("Waiting %d seconds before retry %d/%d...", extra_wait, retry_count + 1, SCRAPE_RETRIES)
            time.sleep(extra_wait)
            return scrape_g2g_listings(driver, category, retry_count + 1)
        else:
            logger.error("Max retries reached for G2G category: %s", category.name)
            return []

    listings = []
    item_cards = soup.select(
        ".product-card, .offer-card, .listing-card, "
        "div[class*='product'], div[class*='offer'], "
        "div[class*='card']:has([class*='price'])"
    )

    if not item_cards:
        item_cards = soup.select(
            "div[class*='grid'] > div, "
            ".list-view > div, [class*='items'] > div"
        )

    logger.debug("Found %d potential item containers on G2G", len(item_cards))

    for card in item_cards[:50]:
        title_el = card.select_one(
            "a[class*='title'], [class*='name'] a, "
            "h3 a, h4 a, [class*='product-title'] a"
        )
        if not title_el:
            title_el = card.select_one("a[href]")

        price_el = card.select_one(
            "[class*='price'], .amount, .cost, "
            "[class*='money'], [data-price], "
            "span[class*='usd']"
        )

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
            url = f"{PLATFORMS['g2g']}{url}"

        listings.append({"title": title, "price_usd": price, "url": url})

    logger.info("Scraped %d listings from G2G / %s", len(listings), category.name)
    return listings


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


def scrape_category(driver: SeleniumBaseDriver, category: Category, platform: str) -> list[dict]:
    """Route scraping to the correct platform-specific function."""
    scrapers = {
        "z2u": scrape_z2u_listings,
        "funpay": scrape_funpay_listings,
        "g2g": scrape_g2g_listings,
    }
    scraper_fn = scrapers.get(platform)
    if not scraper_fn:
        logger.warning("Unknown platform: %s", platform)
        return []
    return scraper_fn(driver, category)


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


def deep_scrape_categories(qualified_categories: list[tuple[str, int, list[Category]]]) -> list[dict]:
    """
    Perform deep scraping for all qualified overlapping categories
    with fresh driver per category group for stealth rotation.
    """
    all_products = []

    for norm_name, platform_count, categories in qualified_categories:
        logger.info("=== Deep scraping category: %s (on %d platforms) ===",
                    norm_name, platform_count)

        # Use a fresh driver per category group for stealth rotation
        driver = create_stealth_driver(StealthConfig())

        try:
            for cat in categories:
                try:
                    human_delay(1.0, 2.0)
                    raw = scrape_category(driver, cat, cat.platform)
                    processed = process_listings(raw, cat.platform, norm_name)
                    all_products.extend(processed)
                    logger.info("Scraped %d products from %s / %s",
                                len(processed), cat.platform, cat.name)
                except (TimeoutException, WebDriverException) as e:
                    logger.error("Error scraping %s / %s: %s",
                                 cat.platform, cat.name, e)
                    continue
        finally:
            try:
                driver.quit()
            except Exception:
                pass

        # Long inter-category delay to avoid rate limiting
                human_delay(3.0, 6.0)

    logger.info("Deep scrape complete. Total raw products: %d", len(all_products))
    return all_products