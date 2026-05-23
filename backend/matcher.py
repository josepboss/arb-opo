"""
Phase 1: Category Mapping & Intersection Filter

Discovers categories across Z2U, FunPay, and G2G, then computes
the overlapping intersection — categories present on 2 or 3 platforms
are passed through for deep scraping.

Routing:
  - Z2U  → FlareSolverr (Cloudflare bypass with rotating proxies)
  - G2G  → FlareSolverr (Cloudflare bypass with rotating proxies)
  - FunPay → Direct Selenium (no blocking observed)
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Optional

from bs4 import BeautifulSoup
from seleniumbase import Driver as SeleniumBaseDriver

from config import PLATFORMS, CATEGORY_URLS, CLOUDFLARE_PLATFORMS
from flaresolverr_client import get_flaresolverr_client, FlareSolverrError
from stealth import create_stealth_driver as _create_stealth
from utils.normalize import normalize_game_title, resolve_alias

logger = logging.getLogger(__name__)


# ─── Category data model ──────────────────────────────────────────────────────


@dataclass
class Category:
    """Represents a discovered category on a platform."""
    platform: str
    name: str
    url: str
    normalized_name: str = field(init=False)

    def __post_init__(self):
        self.normalized_name = resolve_alias(normalize_game_title(self.name))

    def __hash__(self):
        return hash(self.normalized_name)

    def __eq__(self, other):
        if isinstance(other, Category):
            return self.normalized_name == other.normalized_name
        return NotImplemented


# ─── Driver creation (used only for FunPay) ───────────────────────────────────


def create_driver() -> SeleniumBaseDriver:
    """Create a stealth SeleniumBase driver (used for FunPay scraping)."""
    return _create_stealth()


# ─── FlareSolverr-based discovery (Z2U, G2G) ──────────────────────────────────


def _discover_via_flaresolverr(platform: str) -> list[dict]:
    """
    Discover categories from a Cloudflare-protected platform via FlareSolverr.

    Args:
        platform: Platform key ('z2u' or 'g2g')

    Returns:
        List of {"name": str, "url": str} dicts
    """
    url = CATEGORY_URLS[platform]
    logger.info("Discovering categories from %s via FlareSolverr...", platform)

    html = _fetch_with_fallback(platform, url)
    if not html:
        logger.error("Failed to fetch %s categories (all methods exhausted).", platform)
        return []

    soup = BeautifulSoup(html, "html.parser")
    categories = _extract_categories(soup, platform)

    logger.info("Found %d categories on %s", len(categories), platform)
    return categories


def _fetch_with_fallback(platform: str, url: str) -> Optional[str]:
    """
    Try FlareSolverr first, then fall back to direct Selenium.

    Returns HTML string or None if both fail.
    """
    # Attempt 1: FlareSolverr
    try:
        client = get_flaresolverr_client()
        if client.is_available():
            html = client.fetch_html(url, platform=platform, use_proxy=True)
            if html:
                return html
        else:
            logger.warning("FlareSolverr not available for %s.", platform)
    except (FlareSolverrError, Exception) as e:
        logger.warning("FlareSolverr failed for %s: %s. Trying Selenium fallback.", platform, e)

    # Attempt 2: Selenium fallback
    logger.info("Falling back to Selenium for %s category discovery...", platform)
    try:
        driver = _create_stealth()
        try:
            driver.get(url)
            time.sleep(4)
            # Check for challenge page
            page_src = driver.page_source.lower()
            if "challenge" in page_src or "cf-browser-verification" in page_src:
                logger.warning("Selenium also blocked by Cloudflare on %s.", platform)
                return None
            return driver.page_source
        finally:
            try:
                driver.quit()
            except Exception:
                pass
    except Exception as e:
        logger.error("Selenium fallback failed for %s: %s", platform, e)
        return None


def _extract_categories(soup: BeautifulSoup, platform: str) -> list[dict]:
    """Extract category links from BeautifulSoup using platform-specific selectors."""
    selectors = {
        "z2u": [
            "a[href*='/games/']", "a[href*='/category/']",
            ".category-item a", ".menu-item a",
            "[class*='category'] a[href]",
        ],
        "funpay": [
            "a[href*='/lots/']", ".game-item a",
            ".sidebar-game a", "[class*='game'] a[href]",
        ],
        "g2g": [
            "a[href*='/category/']", "a[href*='/products/']",
            ".category-card a", ".nav-link[href*='g2g']",
            "[class*='category'] a[href]",
        ],
    }

    platform_selectors = selectors.get(platform, selectors["z2u"])
    selector_string = ", ".join(platform_selectors)

    categories = []
    for link in soup.select(selector_string):
        href = link.get("href", "")
        text = link.get_text(strip=True)
        if href and text and len(text) > 2:
            full_url = href if href.startswith("http") else f"{PLATFORMS[platform]}{href}"
            categories.append({"name": text, "url": full_url})

    # Deduplicate by name
    seen = set()
    unique = []
    for cat in categories:
        if cat["name"].lower() not in seen:
            seen.add(cat["name"].lower())
            unique.append(cat)

    return unique


# ─── Selenium-based discovery (FunPay only) ───────────────────────────────────


def _discover_funpay(driver: SeleniumBaseDriver) -> list[dict]:
    """Discover categories from FunPay using the Selenium driver."""
    logger.info("Discovering categories from FunPay via Selenium...")
    driver.get(CATEGORY_URLS["funpay"])
    time.sleep(2)

    soup = BeautifulSoup(driver.page_source, "html.parser")
    return _extract_categories(soup, "funpay")


# ─── Intersection logic (unchanged) ───────────────────────────────────────────


def get_intersection(
    categories_by_platform: dict[str, list[dict]],
) -> list[tuple[str, int, list[Category]]]:
    """
    Compute the overlapping intersection of categories across platforms.

    Returns a list of tuples: (normalized_name, occurrence_count, [Category objects]).
    Only categories present on 2+ platforms are included.
    """
    all_categories: dict[str, tuple[set[str], list[Category]]] = {}

    for platform, cats in categories_by_platform.items():
        for cat_data in cats:
            cat = Category(platform=platform, name=cat_data["name"], url=cat_data["url"])
            key = cat.normalized_name
            if key not in all_categories:
                all_categories[key] = (set(), [])
            all_categories[key][0].add(platform)
            all_categories[key][1].append(cat)

    result = []
    for norm_name, (platforms, cats) in all_categories.items():
        count = len(platforms)
        if count >= 2:
            result.append((norm_name, count, cats))

    result.sort(key=lambda x: -x[1])
    logger.info("Intersection: %d categories qualified (on 2+ platforms)", len(result))
    for norm_name, count, cats in result:
        platforms_str = ", ".join(sorted(set(c.platform for c in cats)))
        logger.debug("  %s (%d platforms: %s)", norm_name, count, platforms_str)

    return result


# ─── Main discovery pipeline ──────────────────────────────────────────────────


def discover_and_filter() -> list[tuple[str, int, list[Category]]]:
    """
    Full discovery pipeline:
      - Z2U, G2G → FlareSolverr (with Selenium fallback)
      - FunPay   → Selenium driver

    Returns list of (normalized_name, platform_count, [Category]).
    """
    raw_categories: dict[str, list[dict]] = {}

    # Cloudflare platforms → FlareSolverr
    for platform in CLOUDFLARE_PLATFORMS:
        raw_categories[platform] = _discover_via_flaresolverr(platform)
        time.sleep(1.5)

    # FunPay → Selenium
    driver = create_driver()
    try:
        raw_categories["funpay"] = _discover_funpay(driver)
    finally:
        try:
            driver.quit()
        except Exception:
            pass

    return get_intersection(raw_categories)