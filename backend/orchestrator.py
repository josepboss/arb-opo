"""
Orchestration layer — ties together discovery, scraping, and storage
with an internal scheduler for periodic updates.
"""

import logging
import signal
import sys
import threading
import time
from datetime import datetime, timezone
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler

from config import SCRAPE_INTERVAL_MINUTES, DB_PATH
from database import (
    init_db, clear_all_data, insert_products,
    compute_and_store_top_arbitrage, Product, get_db_path,
)
from matcher import discover_and_filter
from scraper import deep_scrape_categories, process_listings

logger = logging.getLogger(__name__)

# Global to control the main loop
_running = True
_current_status = {"last_run": None, "status": "idle", "products_found": 0}


def get_status() -> dict:
    """Return current orchestrator status."""
    return dict(_current_status)


def run_full_pipeline() -> int:
    """
    Execute the full arbitrage pipeline:
    1. Category discovery & intersection filtering
    2. Deep scraping of qualified categories
    3. Normalization, unit pricing
    4. Aggregation, sorting, and storage

    Returns the number of products inserted.
    """
    global _current_status
    _current_status["status"] = "running"
    _current_status["last_run"] = datetime.now(timezone.utc).isoformat()

    logger.info("=" * 60)
    logger.info("Starting arbitrage pipeline run at %s", _current_status["last_run"])
    logger.info("=" * 60)

    try:
        # Phase 1: Category mapping & intersection
        logger.info("[Phase 1] Discovering and filtering categories...")
        qualified = discover_and_filter()

        if not qualified:
            logger.warning("No qualified overlapping categories found. Skipping scrape.")
            _current_status["status"] = "no_categories"
            _current_status["products_found"] = 0
            return 0

        logger.info("[Phase 1] Found %d qualified category groups.", len(qualified))

        # Phase 2 & 3: Deep scrape + normalization
        logger.info("[Phase 2] Deep scraping qualified categories...")
        all_products = deep_scrape_categories(qualified)

        if not all_products:
            logger.warning("No products scraped. Skipping storage.")
            _current_status["status"] = "no_products"
            _current_status["products_found"] = 0
            return 0

        # Phase 3: Wipe old data and store new
        logger.info("[Phase 3] Wiping old data and storing new products...")
        clear_all_data()

        product_objs = [
            Product(
                platform=p["platform"],
                category=p["category"],
                item_type=p["item_type"],
                title=p["title"],
                price_usd=p["price_usd"],
                unit_price=p["unit_price"],
                quantity=p["quantity"],
                url=p["url"],
            )
            for p in all_products
        ]

        insert_products(product_objs)

        # Compute top arbitrage opportunities
        logger.info("[Phase 3] Computing top arbitrage rankings...")
        compute_and_store_top_arbitrage()

        total = len(product_objs)
        _current_status["status"] = "completed"
        _current_status["products_found"] = total

        logger.info("Pipeline completed successfully. %d products stored.", total)
        return total

    except Exception as e:
        logger.error("Pipeline run failed: %s", e, exc_info=True)
        _current_status["status"] = "failed"
        _current_status["error"] = str(e)
        return 0


def scheduler_worker():
    """Run the pipeline on a schedule using APScheduler."""
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        run_full_pipeline,
        "interval",
        minutes=SCRAPE_INTERVAL_MINUTES,
        id="arbitrage_scrape",
        next_run_time=None,  # Don't start automatically; wait for first trigger
    )
    scheduler.start()
    logger.info("Scheduler started. Interval: %d minutes.", SCRAPE_INTERVAL_MINUTES)

    # Keep the scheduler alive in a separate thread
    while _running:
        time.sleep(1)

    scheduler.shutdown(wait=False)
    logger.info("Scheduler shut down.")


def run_once_and_exit():
    """Run pipeline once and exit (useful for Docker CMD with cron)."""
    count = run_full_pipeline()
    logger.info("Run complete. %d products saved. Exiting.", count)
    return count


def signal_handler(signum, frame):
    """Handle shutdown signals gracefully."""
    global _running
    logger.info("Received signal %s. Shutting down...", signum)
    _running = False
    sys.exit(0)


signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGINT, signal_handler)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    init_db()
    run_once_and_exit()