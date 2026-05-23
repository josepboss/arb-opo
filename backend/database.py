"""
Phase 3: SQLite database operations for persisting scraped arbitrage data.
"""

import sqlite3
import logging
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from config import DB_PATH

logger = logging.getLogger(__name__)


@dataclass
class Product:
    """Represents a scraped product listing."""
    platform: str
    category: str
    item_type: str
    title: str
    price_usd: float
    unit_price: float
    quantity: float
    url: str
    scraped_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class ArbitrageRow:
    """Aggregated arbitrage opportunity row — top 10 cheapest per item type."""
    category: str
    item_type: str
    platform: str
    title: str
    price_usd: float
    unit_price: float
    url: str
    rank: int
    scraped_at: str


def get_db_path() -> str:
    """Get the database file path."""
    return DB_PATH


@contextmanager
def get_connection():
    """Context manager for SQLite connections."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    """Initialize database tables and indices."""
    with get_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS products (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                platform        TEXT    NOT NULL,
                category        TEXT    NOT NULL,
                item_type       TEXT    NOT NULL,
                title           TEXT    NOT NULL,
                price_usd       REAL    NOT NULL,
                unit_price      REAL    NOT NULL,
                quantity        REAL    NOT NULL DEFAULT 1.0,
                url             TEXT    NOT NULL,
                scraped_at      TEXT    NOT NULL
            );

            CREATE TABLE IF NOT EXISTS top_arbitrage (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                category        TEXT    NOT NULL,
                item_type       TEXT    NOT NULL,
                platform        TEXT    NOT NULL,
                title           TEXT    NOT NULL,
                price_usd       REAL    NOT NULL,
                unit_price      REAL    NOT NULL,
                url             TEXT    NOT NULL,
                rank            INTEGER NOT NULL,
                scraped_at      TEXT    NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_products_category ON products(category);
            CREATE INDEX IF NOT EXISTS idx_products_item_type ON products(item_type);
            CREATE INDEX IF NOT EXISTS idx_top_category ON top_arbitrage(category);
            CREATE INDEX IF NOT EXISTS idx_top_item_type ON top_arbitrage(item_type);
            CREATE INDEX IF NOT EXISTS idx_top_unit_price ON top_arbitrage(unit_price);
        """)


def clear_all_data():
    """Wipe all data from the previous run to keep fresh actionable items."""
    with get_connection() as conn:
        conn.execute("DELETE FROM products")
        conn.execute("DELETE FROM top_arbitrage")
    logger.info("Cleared all existing data from database.")


def insert_products(products: list[Product]):
    """Bulk insert scraped products."""
    with get_connection() as conn:
        conn.executemany(
            """INSERT INTO products (platform, category, item_type, title,
               price_usd, unit_price, quantity, url, scraped_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (p.platform, p.category, p.item_type, p.title,
                 p.price_usd, p.unit_price, p.quantity, p.url, p.scraped_at)
                for p in products
            ],
        )
    logger.info("Inserted %d products into database.", len(products))


def compute_and_store_top_arbitrage(top_n: int = 10):
    """
    Group products by (category, item_type), sort by unit_price ascending,
    and store the top N cheapest into the top_arbitrage table.
    """
    with get_connection() as conn:
        conn.execute("DELETE FROM top_arbitrage")

        # Get all distinct (category, item_type) groups
        groups = conn.execute(
            "SELECT DISTINCT category, item_type FROM products"
        ).fetchall()

        rows_inserted = 0
        for group in groups:
            category = group["category"]
            item_type = group["item_type"]

            # Get top N cheapest products for this group
            top_products = conn.execute(
                """SELECT platform, title, price_usd, unit_price, url, scraped_at
                   FROM products
                   WHERE category = ? AND item_type = ?
                   ORDER BY unit_price ASC
                   LIMIT ?""",
                (category, item_type, top_n),
            ).fetchall()

            for rank, prod in enumerate(top_products, start=1):
                conn.execute(
                    """INSERT INTO top_arbitrage
                       (category, item_type, platform, title, price_usd,
                        unit_price, url, rank, scraped_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (category, item_type, prod["platform"], prod["title"],
                     prod["price_usd"], prod["unit_price"], prod["url"],
                     rank, prod["scraped_at"]),
                )
                rows_inserted += 1

        logger.info("Stored %d top arbitrage rows.", rows_inserted)


def get_top_arbitrage(category: Optional[str] = None) -> list[ArbitrageRow]:
    """Retrieve top arbitrage opportunities, optionally filtered by category."""
    with get_connection() as conn:
        if category:
            rows = conn.execute(
                """SELECT category, item_type, platform, title, price_usd,
                          unit_price, url, rank, scraped_at
                   FROM top_arbitrage
                   WHERE category = ?
                   ORDER BY category, item_type, rank""",
                (category,),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT category, item_type, platform, title, price_usd,
                          unit_price, url, rank, scraped_at
                   FROM top_arbitrage
                   ORDER BY category, item_type, rank"""
            ).fetchall()

    return [
        ArbitrageRow(
            category=r["category"],
            item_type=r["item_type"],
            platform=r["platform"],
            title=r["title"],
            price_usd=r["price_usd"],
            unit_price=r["unit_price"],
            url=r["url"],
            rank=r["rank"],
            scraped_at=r["scraped_at"],
        )
        for r in rows
    ]


def get_distinct_categories() -> list[str]:
    """Get distinct categories available in the top arbitrage table."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT DISTINCT category FROM top_arbitrage ORDER BY category"
        ).fetchall()
    return [r["category"] for r in rows]