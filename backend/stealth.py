"""
Enhanced stealth layer for bypassing Cloudflare/Qrator challenges.

Provides realistic browser fingerprinting, human-like behavior simulation,
and CDP-based automation masking.
"""

import logging
import random
import time
from dataclasses import dataclass, field
from typing import Optional

from seleniumbase import Driver as SeleniumBaseDriver

from config import HEADLESS, SELENIUM_TIMEOUT

logger = logging.getLogger(__name__)


# ─── Realistic User Agents ─────────────────────────────────────────────────────

USER_AGENTS = [
    # Chrome 124 - Windows 10
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    # Chrome 123 - Windows 11
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    # Chrome 124 - macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    # Edge 124 - Windows 10
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0",
    # Chrome 123 - Linux
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
]

# ─── Realistic viewport sizes ──────────────────────────────────────────────────

VIEWPORTS = [
    (1920, 1080),
    (1366, 768),
    (1536, 864),
    (1440, 900),
    (1280, 720),
    (1600, 900),
]

# ─── Stealth JS to mask automation ─────────────────────────────────────────────

STEALTH_JS = """
// Override navigator.webdriver
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });

// Override chrome.runtime
window.chrome = { runtime: {} };

// Override permissions
const originalQuery = window.navigator.permissions.query;
window.navigator.permissions.query = (params) => (
    params.name === 'notifications'
        ? Promise.resolve({ state: 'denied' })
        : originalQuery(params)
);

// Override plugins array to appear as real browser
Object.defineProperty(navigator, 'plugins', {
    get: () => [
        { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer' },
        { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai' },
        { name: 'Native Client', filename: 'internal-nacl-plugin' }
    ]
});

// Override languages
Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });

// Override hardwareConcurrency
Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => 8 });

// Override deviceMemory
Object.defineProperty(navigator, 'deviceMemory', { get: () => 8 });

// Mask WebGL fingerprint slightly (vendor/renderer)
const getParameter = WebGLRenderingContext.prototype.getParameter;
WebGLRenderingContext.prototype.getParameter = function(param) {
    if (param === 37445) return 'Intel Inc.';
    if (param === 37446) return 'Intel Iris OpenGL Engine';
    return getParameter.call(this, param);
};
"""


# ─── Platform-specific delay config (Cloudflare sites get longer delays) ──────

PLATFORM_DELAYS = {
    "z2u":     {"min": 3.0, "max": 6.0},    # Cloudflare-heavy
    "funpay":  {"min": 2.0, "max": 4.0},    # Less aggressive
    "g2g":     {"min": 3.5, "max": 7.0},    # Cloudflare + Qrator
    "default": {"min": 1.5, "max": 4.0},
}


# ─── Config ────────────────────────────────────────────────────────────────────

@dataclass
class StealthConfig:
    """Configuration for stealth browser fingerprint."""
    user_agent: str = field(default_factory=lambda: random.choice(USER_AGENTS))
    viewport_width: int = field(default_factory=lambda: random.choice(VIEWPORTS)[0])
    viewport_height: int = field(default_factory=lambda: random.choice(VIEWPORTS)[1])
    locale: str = "en-US,en;q=0.9"
    timezone: str = "America/New_York"
    geolocation: Optional[dict] = None

    def __post_init__(self):
        if self.geolocation is None:
            self.geolocation = {"latitude": 40.7128, "longitude": -74.0060, "accuracy": 100}


# ─── Driver Creation ───────────────────────────────────────────────────────────

def create_stealth_driver(config: Optional[StealthConfig] = None) -> SeleniumBaseDriver:
    """
    Create a SeleniumBase driver with enhanced stealth fingerprinting.
    Uses UC (undetected ChromeDriver) mode with realistic browser properties.
    """
    if config is None:
        config = StealthConfig()

    logger.info(
        "Creating stealth driver (UA: %s..., viewport: %dx%d)",
        config.user_agent[:40], config.viewport_width, config.viewport_height
    )

    # Build Chrome arguments list — SeleniumBase UC driver accepts these via `chrome_options`
    chrome_args = [
        f"--window-size={config.viewport_width},{config.viewport_height}",
        "--disable-blink-features=AutomationControlled",
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--disable-gpu",
        f"--lang=en-US",
        "--disable-web-security",
        "--allow-running-insecure-content",
        "--disable-features=VizDisplayCompositor",
        "--disable-software-rasterizer",
        "--disable-images",
    ]

    if HEADLESS:
        chrome_args.append("--headless=new")

    driver = SeleniumBaseDriver(
        browser="chrome",
        headless2=HEADLESS,          # UC headless mode
        uc=True,                     # Undetected ChromeDriver
        agent=config.user_agent,     # User agent
        chrome_options=chrome_args,  # Chrome arguments list
        disable_csp=True,
        page_load_timeout=SELENIUM_TIMEOUT,
    )

    driver.implicitly_wait(5)

    # Set viewport via CDP
    try:
        driver.execute_cdp_cmd("Emulation.setDeviceMetricsOverride", {
            "width": config.viewport_width,
            "height": config.viewport_height,
            "deviceScaleFactor": 1,
            "mobile": False,
        })
    except Exception as e:
        logger.debug("CDP viewport set failed (non-fatal): %s", e)

    # Inject stealth script into every new document
    _inject_stealth_on_new_document(driver)

    return driver


def _inject_stealth_on_new_document(driver: SeleniumBaseDriver):
    """Inject stealth JS that runs on every page load via CDP."""
    try:
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
            "source": STEALTH_JS,
        })
    except Exception as e:
        logger.debug("CDP script injection failed (non-fatal): %s", e)


# ─── Human-like behavior simulation ───────────────────────────────────────────

def get_platform_delay(platform: str) -> tuple[float, float]:
    """Get min/max delay for a specific platform."""
    delays = PLATFORM_DELAYS.get(platform, PLATFORM_DELAYS["default"])
    return delays["min"], delays["max"]


def human_delay(min_s: float = 1.5, max_s: float = 4.0):
    """Randomized human-like delay with slight gaussian tendency toward lower end."""
    delay = random.triangular(min_s, max_s, min_s + (max_s - min_s) * 0.3)
    time.sleep(delay)


def simulate_human_scroll(driver: SeleniumBaseDriver, steps: int = 3):
    """Simulate human-like scrolling with random pauses."""
    try:
        page_height = driver.execute_script("return document.body.scrollHeight")
        if not page_height or page_height < 500:
            return

        for i in range(steps):
            step_pct = random.uniform(0.2, 0.6)
            target = page_height * (i + 1) / steps * step_pct
            driver.execute_script(f"window.scrollTo({{top: {target}, behavior: 'smooth'}})")
            time.sleep(random.uniform(0.3, 1.2))
    except Exception as e:
        logger.debug("Scroll simulation failed (non-fatal): %s", e)


def simulate_mouse_movement(driver: SeleniumBaseDriver):
    """Move mouse to a random visible element to simulate human presence."""
    try:
        elements = driver.find_elements("a, button, .product-item, .lot-item, h3, h4")
        if elements:
            target = random.choice(elements)
            try:
                driver.execute_script(
                    "arguments[0].dispatchEvent(new MouseEvent('mouseover', {bubbles: true}));",
                    target
                )
            except Exception:
                pass
    except Exception as e:
        logger.debug("Mouse simulation failed (non-fatal): %s", e)


def navigate_with_stealth(
    driver: SeleniumBaseDriver,
    url: str,
    platform: str,
    extra_delay: float = 0.0,
):
    """
    Navigate to a URL with realistic pre/post navigation behavior:
    1. Random pre-navigation wait
    2. Navigate
    3. Wait for page ready
    4. Simulate human scroll + mouse movement
    5. Additional random delay
    """
    time.sleep(random.uniform(0.5, 1.5) + extra_delay)

    logger.debug("Navigating to %s", url)
    driver.get(url)

    try:
        driver.unsafe_js("return document.readyState === 'complete'")
    except Exception:
        pass

    platform_delay = PLATFORM_DELAYS.get(platform, PLATFORM_DELAYS["default"])
    human_delay(platform_delay["min"] * 0.5, platform_delay["max"] * 0.8)

    if random.random() > 0.3:
        simulate_human_scroll(driver, random.randint(2, 4))

    if random.random() > 0.5:
        simulate_mouse_movement(driver)

    human_delay(0.5, 1.5)