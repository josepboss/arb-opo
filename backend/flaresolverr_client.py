"""
FlareSolverr client with rotating proxy pool.

Handles Cloudflare-bypassed HTTP requests through FlareSolverr,
with proxy rotation, blacklisting, performance tracking, and
automatic fallback to direct Selenium.
"""

import logging
import random
import time
from dataclasses import dataclass, field
from typing import Optional

import requests

from config import (
    FLARESOLVERR_URL,
    FLARESOLVERR_TIMEOUT,
    FLARESOLVERR_MAX_RETRIES,
    PROXY_LIST,
    PROXY_BLACKLIST_THRESHOLD,
)

logger = logging.getLogger(__name__)


# ─── Proxy Pool ────────────────────────────────────────────────────────────────


@dataclass
class ProxyStats:
    """Tracks usage and failure stats for a single proxy."""
    failures: int = 0
    successes: int = 0
    last_used: float = 0.0
    blacklisted: bool = False

    @property
    def total(self) -> int:
        return self.failures + self.successes

    @property
    def fail_rate(self) -> float:
        if self.total == 0:
            return 0.0
        return self.failures / self.total


class ProxyPool:
    """
    Manages a pool of rotating proxies with blacklisting.

    Proxies are supplied via PROXY_LIST env var (comma-separated).
    Each proxy URL should be in the format expected by FlareSolverr:
      http://user:pass@host:port
    If no proxies configured, FlareSolverr will use its own IP (no proxy).
    """

    def __init__(self):
        raw_proxies = [p.strip() for p in PROXY_LIST.split(",") if p.strip()]
        self.proxies: dict[str, ProxyStats] = {
            p: ProxyStats() for p in raw_proxies
        } if raw_proxies else {}
        self._last_index = -1
        logger.info("Proxy pool: %d proxies configured.", len(self.proxies))

    def get_next(self) -> Optional[str]:
        """
        Round-robin across non-blacklisted proxies.
        Returns None if all proxies are blacklisted or pool is empty.
        """
        available = [
            url for url, stats in self.proxies.items()
            if not stats.blacklisted
        ]
        if not available:
            logger.warning("No available proxies (all blacklisted or none configured).")
            return None

        # Round-robin selection
        self._last_index = (self._last_index + 1) % len(available)
        chosen = available[self._last_index]
        self.proxies[chosen].last_used = time.time()
        logger.debug("Selected proxy %s (fail rate: %.0f%%)",
                     chosen[:20], self.proxies[chosen].fail_rate * 100)
        return chosen

    def record_success(self, proxy_url: Optional[str]):
        """Mark a proxy call as successful."""
        if proxy_url and proxy_url in self.proxies:
            self.proxies[proxy_url].successes += 1

    def record_failure(self, proxy_url: Optional[str]):
        """Mark a proxy call as failed; blacklist if threshold exceeded."""
        if proxy_url and proxy_url in self.proxies:
            stats = self.proxies[proxy_url]
            stats.failures += 1
            if stats.failures >= PROXY_BLACKLIST_THRESHOLD:
                stats.blacklisted = True
                logger.warning("Proxy %s blacklisted after %d failures.",
                               proxy_url[:20], stats.failures)

    def get_stats(self) -> list[dict]:
        """Return proxy performance stats for logging/dashboard."""
        return [
            {
                "url": url[:30] + "...",
                "successes": s.successes,
                "failures": s.failures,
                "fail_rate": round(s.fail_rate, 3),
                "blacklisted": s.blacklisted,
            }
            for url, s in self.proxies.items()
        ]


# ─── FlareSolverr Client ──────────────────────────────────────────────────────


class FlareSolverrError(Exception):
    """Raised when FlareSolverr returns an error response."""
    pass


class FlareSolverrClient:
    """
    HTTP client that routes requests through FlareSolverr to bypass
    Cloudflare/Cloudfront challenges.

    Uses a rotating proxy pool and falls back to direct requests
    (with Selenium) on failure.
    """

    def __init__(self):
        self.base_url = FLARESOLVERR_URL.rstrip("/")
        self.proxy_pool = ProxyPool()
        self.timeout = FLARESOLVERR_TIMEOUT
        self.max_retries = FLARESOLVERR_MAX_RETRIES
        self._session_stats = {"flare_requests": 0, "flare_failures": 0, "fallbacks": 0}
        logger.info("FlareSolverr client initialized (endpoint: %s)", self.base_url)

    def is_available(self) -> bool:
        """Check if the FlareSolverr service is reachable."""
        try:
            resp = requests.post(
                f"{self.base_url}/v1",
                json={
                    "cmd": "sessions.list",
                },
                timeout=5,
            )
            return resp.status_code == 200
        except requests.RequestException as e:
            logger.warning("FlareSolverr not available: %s", e)
            return False

    def fetch_html(
        self,
        url: str,
        platform: str = "unknown",
        use_proxy: bool = True,
        session_ttl_minutes: int = 5,
    ) -> str:
        """
        Fetch HTML from a URL via FlareSolverr, bypassing Cloudflare.

        Retries with different proxies on failure. Returns the HTML string.
        Raises FlareSolverrError if all retries exhausted.
        """
        last_error: Optional[str] = None

        for attempt in range(1, self.max_retries + 1):
            proxy_url = None
            if use_proxy and self.proxy_pool.proxies:
                proxy_url = self.proxy_pool.get_next()

            payload = {
                "cmd": "request.get",
                "url": url,
                "maxTimeout": int(self.timeout * 1000),
                "sessionTtlMinutes": session_ttl_minutes,
            }

            if proxy_url:
                payload["proxy"] = {"url": proxy_url}

            logger.info(
                "[%s] FlareSolverr request attempt %d/%d (proxy: %s)",
                platform, attempt, self.max_retries,
                proxy_url[:25] + "..." if proxy_url else "none",
            )

            try:
                self._session_stats["flare_requests"] += 1
                resp = requests.post(
                    f"{self.base_url}/v1",
                    json=payload,
                    timeout=self.timeout + 5,
                    headers={"Content-Type": "application/json"},
                )

                if resp.status_code != 200:
                    msg = f"FlareSolverr returned HTTP {resp.status_code}: {resp.text[:200]}"
                    logger.warning(msg)
                    self.proxy_pool.record_failure(proxy_url)
                    self._session_stats["flare_failures"] += 1
                    last_error = msg
                    time.sleep(2 * attempt)  # Backoff
                    continue

                data = resp.json()

                if data.get("status") != "ok":
                    msg = data.get("message", data.get("error", "Unknown FlareSolverr error"))
                    logger.warning("FlareSolverr error: %s", msg)
                    self.proxy_pool.record_failure(proxy_url)
                    self._session_stats["flare_failures"] += 1
                    last_error = msg
                    time.sleep(2 * attempt)
                    continue

                solution = data.get("solution", {})
                html = solution.get("response", "")

                if not html:
                    logger.warning("FlareSolverr returned empty response body")
                    self.proxy_pool.record_failure(proxy_url)
                    last_error = "Empty response body"
                    time.sleep(2 * attempt)
                    continue

                self.proxy_pool.record_success(proxy_url)
                logger.info(
                    "[%s] FlareSolverr success (%d bytes, proxy: %s)",
                    platform, len(html),
                    "yes" if proxy_url else "no",
                )
                return html

            except requests.Timeout:
                msg = f"FlareSolverr timeout after {self.timeout}s"
                logger.warning("[%s] %s (attempt %d)", platform, msg, attempt)
                self.proxy_pool.record_failure(proxy_url)
                self._session_stats["flare_failures"] += 1
                last_error = msg
                time.sleep(3 * attempt)

            except requests.RequestException as e:
                msg = f"FlareSolverr request failed: {e}"
                logger.warning("[%s] %s (attempt %d)", platform, msg, attempt)
                self.proxy_pool.record_failure(proxy_url)
                self._session_stats["flare_failures"] += 1
                last_error = msg
                time.sleep(3 * attempt)

        # All retries exhausted
        self._session_stats["fallbacks"] += 1
        raise FlareSolverrError(
            f"Failed to fetch {url} after {self.max_retries} attempts. Last error: {last_error}"
        )

    def get_stats(self) -> dict:
        """Return client and proxy pool statistics."""
        return {
            **self._session_stats,
            "proxies": self.proxy_pool.get_stats(),
            "available": self.is_available(),
        }


# ─── Singleton ─────────────────────────────────────────────────────────────────

_client: Optional[FlareSolverrClient] = None


def get_flaresolverr_client() -> FlareSolverrClient:
    """Get or create the global FlareSolverr client singleton."""
    global _client
    if _client is None:
        _client = FlareSolverrClient()
    return _client


def fetch_via_flaresolverr(
    url: str,
    platform: str = "unknown",
    use_proxy: bool = True,
    session_ttl_minutes: int = 5,
) -> Optional[str]:
    """
    Convenience function: fetch HTML via FlareSolverr.
    Returns HTML string or None if unavailable/failed.
    """
    try:
        client = get_flaresolverr_client()
        if not client.is_available():
            logger.warning("FlareSolverr unavailable, returning None.")
            return None
        return client.fetch_html(url, platform, use_proxy, session_ttl_minutes)
    except Exception as e:
        logger.error("FlareSolverr fetch failed: %s", e)
        return None