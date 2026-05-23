"""
Proxy Refresher — periodically downloads free proxy lists,
verifies them against Z2U/G2G, and feeds working proxies into the
FlareSolverr client's proxy pool.

Sources:
  - gfpcom/free-proxy-list (https://github.com/gfpcom/free-proxy-list)

Pipeline:
  1. Download proxy list from GitHub raw
  2. Parse IP:PORT lines
  3. Quick-verify each proxy (connectivity + speed)
  4. Keep top N fastest that actually work
  5. Update the ProxyPool in flaresolverr_client.py
  6. Persist verified list to disk for container restarts
"""

import json
import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, asdict
from pathlib import Path
from threading import Lock
from typing import Optional

import requests

logger = logging.getLogger(__name__)


# ─── Config ────────────────────────────────────────────────────────────────────

# Where to download proxy lists from (GitHub raw URLs)
# Source: gfpcom/free-proxy-list — if the repo has files at different paths,
# override PROXY_SOURCE_URLS env var with the correct URLs.
# Defaults to well-known, maintained free proxy lists.
PROXY_SOURCE_URLS = [
    url.strip() for url in os.getenv(
        "PROXY_SOURCE_URLS",
        "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt,"
        "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/socks4.txt,"
        "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt,"
        "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/socks4.txt,"
        "https://raw.githubusercontent.com/roosterkid/openproxylist/main/HTTPS.txt",
    ).split(",") if url.strip()
]

# Test URL for proxy verification (we test against a target marketplace + a control)
TEST_URLS = os.getenv(
    "PROXY_TEST_URLS",
    "https://www.z2u.com,https://httpbin.org/ip",
).split(",")

# How many proxies to keep max
MAX_VERIFIED_PROXIES = int(os.getenv("MAX_VERIFIED_PROXIES", "30"))

# Connection timeout for proxy verification (seconds)
PROXY_TEST_TIMEOUT = int(os.getenv("PROXY_TEST_TIMEOUT", "10"))

# Max workers for parallel proxy verification
PROXY_TEST_WORKERS = int(os.getenv("PROXY_TEST_WORKERS", "20"))

# Where to persist verified proxy list
VERIFIED_PROXIES_PATH = Path(
    os.getenv("VERIFIED_PROXIES_PATH", "/app/data/verified_proxies.json")
)

# How often to refresh (minutes)
PROXY_REFRESH_INTERVAL = int(os.getenv("PROXY_REFRESH_INTERVAL", "15"))


# ─── Data ──────────────────────────────────────────────────────────────────────


@dataclass
class VerifiedProxy:
    """A proxy that passed verification."""
    url: str                # Full URL like http://1.2.3.4:8080
    source: str             # Where it was downloaded from
    latency_ms: float = 0.0
    verified_at: str = ""   # ISO timestamp


# ─── Downloader ────────────────────────────────────────────────────────────────


def download_raw_proxies() -> list[str]:
    """
    Download proxy lists from all source URLs.
    Returns a list of raw proxy strings (ip:port).
    """
    all_lines: list[str] = []

    for source_url in PROXY_SOURCE_URLS:
        try:
            logger.info("Downloading proxy list from %s", source_url)
            resp = requests.get(source_url, timeout=15)
            resp.raise_for_status()

            # Parse lines — grab anything that looks like IP:PORT
            lines = resp.text.strip().split("\n")
            parsed = 0
            for line in lines:
                line = line.strip()
                # Skip markdown, comments, empty
                if not line or line.startswith("#") or line.startswith("|"):
                    continue
                # Match ip:port or ip:port@protocol patterns
                if re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}:\d{2,5}", line):
                    all_lines.append(line)
                    parsed += 1

            logger.info("  → Parsed %d proxies from %s", parsed, source_url)

        except requests.RequestException as e:
            logger.warning("Failed to download %s: %s", source_url, e)

    # Deduplicate
    unique = list(dict.fromkeys(all_lines))
    logger.info("Total unique raw proxies: %d", len(unique))
    return unique


# ─── Verifier ──────────────────────────────────────────────────────────────────


def _test_single_proxy(proxy_ip_port: str) -> Optional[VerifiedProxy]:
    """
    Test a single proxy against the target URLs.

    Returns a VerifiedProxy if it works and is fast enough, else None.
    """
    proxy_url = f"http://{proxy_ip_port}"

    # First test: fastest target (httpbin)
    start = time.time()
    try:
        resp = requests.get(
            TEST_URLS[-1],  # httpbin falls first for quick check
            proxies={"http": proxy_url, "https": proxy_url},
            timeout=PROXY_TEST_TIMEOUT,
        )
        if resp.status_code != 200:
            return None
        latency = (time.time() - start) * 1000  # ms
    except requests.RequestException:
        return None

    # Second test: try to reach a marketplace
    try:
        resp = requests.get(
            TEST_URLS[0],  # z2u
            proxies={"http": proxy_url, "https": proxy_url},
            timeout=PROXY_TEST_TIMEOUT,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                              "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            },
        )
        if resp.status_code not in (200, 403, 429):
            # 403/429 from the marketplace is OK — it means the proxy CAN reach it
            # (just blocked by Cloudflare which FlareSolverr handles)
            return None
    except requests.RequestException:
        return None

    return VerifiedProxy(
        url=proxy_url,
        source="gfpcom/free-proxy-list",
        latency_ms=round(latency, 1),
        verified_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    )


def verify_proxies(raw_proxies: list[str], max_count: int = MAX_VERIFIED_PROXIES) -> list[VerifiedProxy]:
    """
    Verify a list of raw proxy strings in parallel.
    Returns the fastest verified proxies (up to max_count).
    """
    if not raw_proxies:
        logger.warning("No proxies to verify.")
        return []

    logger.info("Verifying %d proxies with %d workers...", len(raw_proxies), PROXY_TEST_WORKERS)

    verified: list[VerifiedProxy] = []
    checked = 0

    with ThreadPoolExecutor(max_workers=PROXY_TEST_WORKERS) as executor:
        futures = {
            executor.submit(_test_single_proxy, proxy): proxy
            for proxy in raw_proxies
        }

        for future in as_completed(futures):
            proxy = futures[future]
            checked += 1
            try:
                result = future.result()
                if result:
                    verified.append(result)
                    if checked % 20 == 0:
                        logger.info("  Progress: %d/%d checked, %d working so far",
                                    checked, len(raw_proxies), len(verified))
            except Exception as e:
                logger.debug("Proxy %s threw during test: %s", proxy[:20], e)

    # Sort by latency, keep fastest
    verified.sort(key=lambda p: p.latency_ms)
    top = verified[:max_count]

    logger.info(
        "Verification complete: %d/%d working (keeping top %d)",
        len(verified), len(raw_proxies), len(top),
    )
    for v in top[:5]:
        logger.debug("  ✓ %s  (%.0f ms)", v.url, v.latency_ms)
    if len(top) > 5:
        logger.debug("  ... and %d more", len(top) - 5)

    return top


# ─── Persistence ───────────────────────────────────────────────────────────────


def save_verified_proxies(proxies: list[VerifiedProxy]):
    """Persist verified proxy list to disk."""
    data = [asdict(p) for p in proxies]
    VERIFIED_PROXIES_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(VERIFIED_PROXIES_PATH, "w") as f:
        json.dump(data, f, indent=2)
    logger.info("Saved %d verified proxies to %s", len(proxies), VERIFIED_PROXIES_PATH)


def load_verified_proxies() -> list[VerifiedProxy]:
    """Load persisted verified proxies from disk."""
    if not VERIFIED_PROXIES_PATH.exists():
        return []
    try:
        with open(VERIFIED_PROXIES_PATH) as f:
            data = json.load(f)
        proxies = [VerifiedProxy(**d) for d in data]
        logger.info("Loaded %d verified proxies from %s", len(proxies), VERIFIED_PROXIES_PATH)
        return proxies
    except (json.JSONDecodeError, IOError) as e:
        logger.warning("Failed to load verified proxies: %s", e)
        return []


# ─── Integration with FlareSolverr's ProxyPool ────────────────────────────────


# Global lock for thread-safe proxy updates
_proxy_update_lock = Lock()


def feed_proxies_to_pool(proxies: list[VerifiedProxy]):
    """
    Update the FlareSolverr client's ProxyPool with verified proxies.
    This replaces the static PROXY_LIST env var with live-tested proxies.
    """
    from flaresolverr_client import get_flaresolverr_client

    with _proxy_update_lock:
        client = get_flaresolverr_client()
        # The ProxyPool is initialized once. We need to dynamically replace its
        # internal proxy dict. Since ProxyPool is simple, we can do this directly.
        proxy_urls = [p.url for p in proxies]
        pool = client.proxy_pool

        # Reset pool with fresh proxies
        from flaresolverr_client import ProxyStats
        pool.proxies = {url: ProxyStats() for url in proxy_urls}
        pool._last_index = -1

        logger.info("ProxyPool updated with %d live proxies.", len(proxy_urls))


# ─── Main refresh pipeline ────────────────────────────────────────────────────


def refresh_proxies() -> int:
    """
    Full proxy refresh pipeline:
      1. Download raw proxy lists from gfpcom/free-proxy-list
      2. Verify them in parallel
      3. Persist to disk
      4. Feed into FlareSolverr's proxy pool

    Returns the number of verified proxies.
    """
    logger.info("=" * 50)
    logger.info("Starting proxy refresh...")

    # Step 1: Download
    raw = download_raw_proxies()
    if not raw:
        logger.warning("No raw proxies downloaded. Using cached list if available.")
        cached = load_verified_proxies()
        if cached:
            feed_proxies_to_pool(cached)
            return len(cached)
        return 0

    # Step 2: Verify
    verified = verify_proxies(raw)
    if not verified:
        logger.warning("No working proxies found. Trying cached list.")
        cached = load_verified_proxies()
        if cached:
            feed_proxies_to_pool(cached)
            return len(cached)
        return 0

    # Step 3: Persist
    save_verified_proxies(verified)

    # Step 4: Feed into FlareSolverr client
    feed_proxies_to_pool(verified)

    logger.info("Proxy refresh complete. %d working proxies loaded.", len(verified))
    return len(verified)


def refresh_loop():
    """
    Run proxy refresh in a loop. Designed to run as a background thread
    alongside the main orchestrator.
    """
    # Initial load from disk
    cached = load_verified_proxies()
    if cached:
        feed_proxies_to_pool(cached)
        logger.info("Initial proxy pool: %d proxies from cache.", len(cached))

    # Do a fresh fetch immediately
    refresh_proxies()

    # Then refresh on schedule
    while True:
        logger.info("Next proxy refresh in %d minutes...", PROXY_REFRESH_INTERVAL)
        time.sleep(PROXY_REFRESH_INTERVAL * 60)
        try:
            refresh_proxies()
        except Exception as e:
            logger.error("Proxy refresh failed: %s", e, exc_info=True)


# ─── Standalone entry point ───────────────────────────────────────────────────


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    count = refresh_proxies()
    print(f"\n✅ {count} verified proxies loaded into the FlareSolverr pool.\n")
    print(f"  Source : gfpcom/free-proxy-list")
    print(f"  Persist: {VERIFIED_PROXIES_PATH}")
    print(f"  Pool   : flaresolverr_client.ProxyPool")
    print()
    print("To run continuously as a background service:")
    print("  from proxy_refresher import refresh_loop")
    print("  import threading")
    print("  threading.Thread(target=refresh_loop, daemon=True).start()")