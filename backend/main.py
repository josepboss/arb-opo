"""
Main entry point — runs the FastAPI dashboard, the scheduled scraper,
and the proxy refresher concurrently using threading.
"""

import logging
import threading

import uvicorn

from config import HOST, PORT
from database import init_db
from orchestrator import run_full_pipeline, scheduler_worker, get_status
from proxy_refresher import refresh_loop

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def start_dashboard():
    """Start the FastAPI dashboard server."""
    logger.info("Starting dashboard on %s:%s", HOST, PORT)
    uvicorn.run(
        "app:app",
        host=HOST,
        port=PORT,
        log_level="info",
        reload=False,
    )


def main():
    """Main entry point — init DB, run initial scrape, proxy refresh, then serve."""
    init_db()

    # Start proxy refresher (downloads + verifies free proxies every 15 min)
    logger.info("Starting proxy refresher...")
    proxy_thread = threading.Thread(target=refresh_loop, daemon=True)
    proxy_thread.start()

    # Wait a moment for the proxy pool to have at least a few working proxies
    import time
    time.sleep(3)

    # Run an initial scrape in a background thread
    logger.info("Running initial scrape...")
    scrape_thread = threading.Thread(target=run_full_pipeline, daemon=True)
    scrape_thread.start()

    # Start the scheduler in background
    sched_thread = threading.Thread(target=scheduler_worker, daemon=True)
    sched_thread.start()

    # Start the dashboard (blocks)
    start_dashboard()


if __name__ == "__main__":
    main()