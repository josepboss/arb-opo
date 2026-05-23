"""
Phase 1: Category Mapping & Intersection Filter

Discovers categories across Z2U, FunPay, and G2G, then computes
the overlapping intersection — categories present on 2 or 3 platforms
are passed through for deep scraping.
"""

import re
import logging
from dataclasses import dataclass, field
from typing import Optional

from bs4 import BeautifulSoup
from seleniumbase import Driver as SeleniumBaseDriver

from config import PLATFORMS, CATEGORY_URLS, HEADLESS, SELENIUM_TIMEOUT
from utils.normalize import normalize_game_title, resolve_alias

logger = logging.getLogger(__name__)


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


def create_driver() -> SeleniumBaseDriver:
    """Create a stealth SeleniumBase driver for scraping."""
    driver = SeleniumBaseDriver(
        browser="chrome",
        headless=HEADLESS,
        undetected=True,
        disable_images=True,
        uc_cdp=True,
        headless2=HEADLESS,
        agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    )
    driver.set_page_load_timeout(SELENIUM_TIMEOUT)
    driver.implicitly_wait(5)
    return driver


def discover_categories_z2u(driver: SeleniumBaseDriver) -> list[dict]:
    """
    Discover game/service categories from Z2U.
    Navigate to the categories page and extract links.
    """
    logger.info("Discovering categories from Z2U...")
    driver.get(CATEGORY_URLS["z2u"])
    import time
    time.sleep(2)

    categories = []
    soup = BeautifulSoup(driver.page_source, "html.parser")

    # Z2U typically has category links in a sidebar or grid
    # Selectors may need tuning as Z2U updates their layout
    for link in soup.select("a[href*='/games/'], a[href*='/category/'], "
                            ".category-item a, .menu-item a, "
                            "[class*='category'] a[href]"):
        href = link.get("href", "")
        text = link.get_text(strip=True)
        if href and text and len(text) > 2:
            full_url = href if href.startswith("http") else f"{PLATFORMS['z2u']}{href}"
            categories.append({"name": text, "url": full_url})

    logger.info("Found %d categories on Z2U", len(categories))
    return categories


def discover_categories_funpay(driver: SeleniumBaseDriver) -> list[dict]:
    """
    Discover categories from FunPay.
    """
    logger.info("Discovering categories from FunPay...")
    driver.get(CATEGORY_URLS["funpay"])
    import time
    time.sleep(2)

    categories = []
    soup = BeautifulSoup(driver.page_source, "html.parser")

    # FunPay uses a sidebar with game links
    for link in soup.select("a[href*='/lots/'], .game-item a, "
                            ".sidebar-game a, [class*='game'] a[href]"):
        href = link.get("href", "")
        text = link.get_text(strip=True)
        if href and text and len(text) > 2:
            full_url = href if href.startswith("http") else f"{PLATFORMS['funpay']}{href}"
            categories.append({"name": text, "url": full_url})

    logger.info("Found %d categories on FunPay", len(categories))
    return categories


def discover_categories_g2g(driver: SeleniumBaseDriver) -> list[dict]:
    """
    Discover categories from G2G.
    """
    logger.info("Discovering categories from G2G...")
    driver.get(CATEGORY_URLS["g2g"])
    import time
    time.sleep(2)

    categories = []
    soup = BeautifulSoup(driver.page_source, "html.parser")

    # G2G typically uses mega-menu or category grid
    for link in soup.select("a[href*='/category/'], a[href*='/products/'], "
                            ".category-card a, .nav-link[href*='g2g'], "
                            "[class*='category'] a[href]"):
        href = link.get("href", "")
        text = link.get_text(strip=True)
        if href and text and len(text) > 2:
            full_url = href if href.startswith("http") else f"{PLATFORMS['g2g']}{href}"
            categories.append({"name": text, "url": full_url})

    logger.info("Found %d categories on G2G", len(categories))
    return categories


def get_intersection(categories_by_platform: dict[str, list[dict]]) -> list[tuple[str, int, list[Category]]]:
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

    # Filter: only include categories present on 2+ platforms
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


def discover_and_filter() -> list[tuple[str, int, list[Category]]]:
    """
    Full discovery pipeline: scrape categories from all platforms,
    normalize, and return only the overlapping intersection.

    Returns list of (normalized_name, platform_count, [Category]).
    """
    driver = create_driver()
    try:
        raw_categories = {
            "z2u": discover_categories_z2u(driver),
            "funpay": discover_categories_funpay(driver),
            "g2g": discover_categories_g2g(driver),
        }
        return get_intersection(raw_categories)
    finally:
        try:
            driver.quit()
        except Exception:
            pass