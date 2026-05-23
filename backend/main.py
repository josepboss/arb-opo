"""
Main entry point — runs the FastAPI dashboard and the scheduled scraper
concurrently using threading.
"""

import logging
import threading

import uvicorn

from config import HOST, PORT
from database import init_db
from orchestrator import run_full_pipeline, scheduler_worker, get_status

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
    """Main entry point — init DB, run an initial scrape, then start the server."""
    init_db()

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