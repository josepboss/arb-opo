"""
FastAPI Web Dashboard — serves arbitrage data and provides
trigger/scrape-status endpoints. Listens on port 2105.
"""

import logging
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse

from config import HOST, PORT
from database import init_db, get_top_arbitrage, get_distinct_categories
from orchestrator import run_full_pipeline, get_status

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: initialize the database."""
    logger.info("Initializing database...")
    init_db()
    yield
    logger.info("Shutting down.")


app = FastAPI(
    title="Multi-Marketplace Arbitrage Engine",
    description="Real-time arbitrage opportunities across Z2U, FunPay, and G2G.",
    version="1.0.0",
    lifespan=lifespan,
)


# ─── HTML Templates ───────────────────────────────────────────────────────────

BASE_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Arbitrage Dashboard</title>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #0f0f1a;
            color: #e2e2f0;
            min-height: 100vh;
        }}
        .header {{
            background: linear-gradient(135deg, #1a1a2e, #16213e);
            border-bottom: 1px solid #2a2a4a;
            padding: 1.5rem 2rem;
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 1rem;
        }}
        .header h1 {{
            font-size: 1.5rem;
            background: linear-gradient(135deg, #6366f1, #8b5cf6);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }}
        .header .status {{
            font-size: 0.875rem;
            color: #94a3b8;
        }}
        .header .status .badge {{
            display: inline-block;
            padding: 0.25rem 0.75rem;
            border-radius: 9999px;
            font-size: 0.75rem;
            font-weight: 600;
        }}
        .badge-running {{ background: #f59e0b; color: #1a1a2e; }}
        .badge-completed {{ background: #10b981; color: white; }}
        .badge-failed {{ background: #ef4444; color: white; }}
        .badge-idle {{ background: #64748b; color: white; }}
        .controls {{
            padding: 1rem 2rem;
            display: flex;
            gap: 0.75rem;
            flex-wrap: wrap;
        }}
        .btn {{
            padding: 0.5rem 1.25rem;
            border: 1px solid #2a2a4a;
            border-radius: 8px;
            background: #1a1a2e;
            color: #e2e2f0;
            cursor: pointer;
            font-size: 0.875rem;
            transition: all 0.2s;
            text-decoration: none;
            display: inline-flex;
            align-items: center;
            gap: 0.5rem;
        }}
        .btn:hover {{ background: #2a2a4a; border-color: #6366f1; }}
        .btn-primary {{ background: #6366f1; border-color: #6366f1; color: white; }}
        .btn-primary:hover {{ background: #4f46e5; }}
        .btn-danger {{ background: #dc2626; border-color: #dc2626; color: white; }}
        .btn-danger:hover {{ background: #b91c1c; }}
        .container {{ padding: 0 2rem 2rem; }}
        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 1rem;
            margin-bottom: 1.5rem;
        }}
        .stat-card {{
            background: #1a1a2e;
            border: 1px solid #2a2a4a;
            border-radius: 12px;
            padding: 1.25rem;
        }}
        .stat-card .label {{ font-size: 0.75rem; color: #64748b; text-transform: uppercase; letter-spacing: 0.05em; }}
        .stat-card .value {{ font-size: 1.75rem; font-weight: 700; margin-top: 0.25rem; }}
        .category-filter {{
            display: flex;
            gap: 0.5rem;
            flex-wrap: wrap;
            margin-bottom: 1.5rem;
        }}
        .category-filter a {{
            padding: 0.375rem 0.875rem;
            border-radius: 9999px;
            font-size: 0.8125rem;
            background: #1a1a2e;
            border: 1px solid #2a2a4a;
            color: #94a3b8;
            text-decoration: none;
            transition: all 0.2s;
        }}
        .category-filter a:hover, .category-filter a.active {{
            background: #6366f1;
            border-color: #6366f1;
            color: white;
        }}
        table {{
            width: 100%;
            border-collapse: separate;
            border-spacing: 0;
            background: #1a1a2e;
            border: 1px solid #2a2a4a;
            border-radius: 12px;
            overflow: hidden;
        }}
        th {{
            text-align: left;
            padding: 0.75rem 1rem;
            font-size: 0.75rem;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            color: #64748b;
            border-bottom: 1px solid #2a2a4a;
            background: #16213e;
        }}
        td {{
            padding: 0.75rem 1rem;
            font-size: 0.875rem;
            border-bottom: 1px solid #1e1e3a;
        }}
        tr:last-child td {{ border-bottom: none; }}
        tr:hover td {{ background: rgba(99, 102, 241, 0.05); }}
        .platform-badge {{
            display: inline-block;
            padding: 0.2rem 0.6rem;
            border-radius: 6px;
            font-size: 0.75rem;
            font-weight: 600;
        }}
        .platform-z2u {{ background: rgba(99, 102, 241, 0.2); color: #818cf8; }}
        .platform-funpay {{ background: rgba(16, 185, 129, 0.2); color: #34d399; }}
        .platform-g2g {{ background: rgba(245, 158, 11, 0.2); color: #fbbf24; }}
        .rank {{
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 1.75rem;
            height: 1.75rem;
            border-radius: 9999px;
            font-size: 0.75rem;
            font-weight: 700;
        }}
        .rank-1 {{ background: #f59e0b; color: #1a1a2e; }}
        .rank-2 {{ background: #94a3b8; color: #1a1a2e; }}
        .rank-3 {{ background: #b45309; color: white; }}
        .rank-rest {{ background: #2a2a4a; color: #94a3b8; }}
        .price {{ font-family: 'SF Mono', 'Fira Code', monospace; font-weight: 600; }}
        .unit-price {{ font-family: 'SF Mono', 'Fira Code', monospace; color: #94a3b8; font-size: 0.8125rem; }}
        .item-type {{ font-family: 'SF Mono', 'Fira Code', monospace; font-size: 0.8125rem; color: #a5b4fc; }}
        .empty-state {{
            text-align: center;
            padding: 3rem 2rem;
            color: #64748b;
        }}
        .empty-state h2 {{ font-size: 1.25rem; margin-bottom: 0.5rem; }}
        .footer {{
            text-align: center;
            padding: 1.5rem;
            color: #64748b;
            font-size: 0.8125rem;
        }}
        @media (max-width: 768px) {{
            .header {{ flex-direction: column; align-items: flex-start; }}
            .container {{ padding: 0 1rem 1rem; }}
            td, th {{ padding: 0.5rem; }}
        }}
    </style>
</head>
<body>
    <div class="header">
        <div>
            <h1>⚡ Arbitrage Engine</h1>
            <div class="status">
                Status: <span class="badge badge-{status_class}">{status_text}</span>
                &middot; Last run: {last_run}
                &middot; Products: <strong>{product_count}</strong>
            </div>
        </div>
        <div style="display:flex;gap:0.75rem;">
            <a href="/" class="btn">Dashboard</a>
            <a href="/api/status" class="btn">API Status</a>
            <a href="/docs" class="btn">API Docs</a>
        </div>
    </div>
    <div class="controls">
        <a href="/trigger" class="btn btn-primary">🔄 Run Scrape Now</a>
        <a href="/" class="btn">↻ Refresh</a>
    </div>
    <div class="container">
        {category_filters}
        {content}
    </div>
    <div class="footer">
        Multi-Marketplace Arbitrage Engine &middot; Z2U &middot; FunPay &middot; G2G
    </div>
</body>
</html>
"""


def _status_badge(status: str) -> str:
    mapping = {
        "running": "running",
        "completed": "completed",
        "failed": "failed",
        "no_categories": "idle",
        "no_products": "idle",
    }
    return mapping.get(status, "idle")


def _status_text(status: str) -> str:
    mapping = {
        "running": "Running",
        "completed": "Completed",
        "failed": "Failed",
        "no_categories": "No Categories Found",
        "no_products": "No Products Found",
    }
    return mapping.get(status, "Idle")


def _platform_class(platform: str) -> str:
    return f"platform-{platform}"


def _rank_class(rank: int) -> str:
    if rank == 1:
        return "rank-1"
    elif rank == 2:
        return "rank-2"
    elif rank == 3:
        return "rank-3"
    return "rank-rest"


def _render_page(content_html: str, selected_category: Optional[str] = None) -> str:
    status = get_status()
    status_val = status.get("status", "idle")
    last_run = status.get("last_run", "Never")
    if last_run and last_run != "Never":
        try:
            dt = datetime.fromisoformat(last_run)
            last_run = dt.strftime("%Y-%m-%d %H:%M UTC")
        except ValueError:
            pass

    categories = get_distinct_categories()

    cat_links = ['<a href="/" class="{}">All</a>'.format("active" if not selected_category else "")]
    for cat in categories:
        cls = "active" if selected_category == cat else ""
        cat_links.append(f'<a href="/?category={cat}" class="{cls}">{cat.title()}</a>')

    category_filters_html = f'<div class="category-filter">{"".join(cat_links)}</div>'

    return BASE_HTML.format(
        status_class=_status_badge(status_val),
        status_text=_status_text(status_val),
        last_run=last_run,
        product_count=status.get("products_found", 0),
        category_filters=category_filters_html,
        content=content_html,
    )


# ─── Routes ────────────────────────────────────────────────────────────────────


@app.get("/", response_class=HTMLResponse)
async def dashboard(category: Optional[str] = Query(None)):
    """Main dashboard page."""
    rows = get_top_arbitrage(category)

    if not rows:
        content = """\
        <div class="empty-state">
            <h2>No arbitrage data yet</h2>
            <p>Click "Run Scrape Now" to discover opportunities across Z2U, FunPay, and G2G.</p>
        </div>"""
        return _render_page(content, category)

    # Group by category for display
    grouped: dict[str, list] = {}
    for row in rows:
        grouped.setdefault(row.category, []).append(row)

    table_parts = []
    for cat_name, items in grouped.items():
        table_parts.append(f'<h3 style="margin:1.5rem 0 0.75rem;color:#a5b4fc;">📁 {cat_name.title()}</h3>')
        table_parts.append("""\
        <table>
            <thead>
                <tr>
                    <th>Rank</th>
                    <th>Platform</th>
                    <th>Item Type</th>
                    <th>Title</th>
                    <th>Price</th>
                    <th>Unit Price</th>
                </tr>
            </thead>
            <tbody>""")

        for item in items:
            table_parts.append(f"""\
                <tr>
                    <td><span class="rank {_rank_class(item.rank)}">{item.rank}</span></td>
                    <td><span class="platform-badge {_platform_class(item.platform)}">{item.platform}</span></td>
                    <td><span class="item-type">{item.item_type}</span></td>
                    <td><a href="{item.url}" target="_blank" style="color:#818cf8;text-decoration:none;">{item.title}</a></td>
                    <td class="price">${item.price_usd:.2f}</td>
                    <td class="unit-price">${item.unit_price:.6f} / unit</td>
                </tr>""")

        table_parts.append("</tbody></table>")

    content = "\n".join(table_parts)
    return _render_page(content, category)


@app.get("/trigger")
async def trigger_scrape(background_tasks: BackgroundTasks):
    """Manually trigger a scrape run."""
    status = get_status()
    if status.get("status") == "running":
        return HTMLResponse(
            content=_render_page(
                '<div class="empty-state"><h2>Scrape already running</h2><p>Please wait for the current run to complete.</p></div>'
            ),
            status_code=429,
        )

    # Run in a background thread so the request doesn't block
    thread = threading.Thread(target=run_full_pipeline, daemon=True)
    thread.start()

    return HTMLResponse(
        content=_render_page(
            """\
            <div class="empty-state">
                <h2>🔄 Scrape triggered</h2>
                <p>The scraper is now running. Refresh the page to see results once complete.</p>
                <p style="margin-top:1rem;"><a href="/" class="btn btn-primary">↻ Refresh Dashboard</a></p>
            </div>"""
        ),
    )


# ─── JSON API Endpoints ────────────────────────────────────────────────────────


@app.get("/api/status")
async def api_status():
    """Return current pipeline status as JSON."""
    return JSONResponse(get_status())


@app.get("/api/arbitrage")
async def api_arbitrage(
    category: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
):
    """Return arbitrage opportunities as JSON."""
    rows = get_top_arbitrage(category)
    return JSONResponse(
        content=[{
            "category": r.category,
            "item_type": r.item_type,
            "platform": r.platform,
            "title": r.title,
            "price_usd": round(r.price_usd, 2),
            "unit_price": round(r.unit_price, 6),
            "url": r.url,
            "rank": r.rank,
            "scraped_at": r.scraped_at,
        } for r in rows[:limit]]
    )


@app.get("/api/categories")
async def api_categories():
    """Return distinct categories available in the data."""
    return JSONResponse({"categories": get_distinct_categories()})


@app.get("/health")
async def health():
    """Health check endpoint."""
    return JSONResponse({"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()})


# ─── Entry Point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    logger.info("Starting arbitrage dashboard on %s:%s", HOST, PORT)
    uvicorn.run(app, host=HOST, port=PORT, log_level="info")