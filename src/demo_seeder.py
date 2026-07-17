"""
demo_seeder.py
Populates a DuckDB workspace with rich, realistic e-commerce dummy data
so the Vercel-hosted dashboard shows fully populated KPIs, charts, and
data tables on first load — without requiring the full ETL pipeline run.
"""

import duckdb
import numpy as np
import logging
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger("DemoSeeder")


def is_seeded(db_path: Path) -> bool:
    """Returns True if the demo database already has Silver data loaded."""
    try:
        if not db_path.exists():
            return False
        conn = duckdb.connect(str(db_path))
        result = conn.execute("SELECT COUNT(*) FROM silver_clean_sales").fetchone()
        conn.close()
        return result[0] > 0
    except Exception:
        return False


def seed(workspace_id: str = "default") -> bool:
    """
    Generates and loads 6 months of e-commerce data across Bronze, Silver,
    Gold, and Quarantine layers for the given workspace. Also generates a
    Matplotlib chart PNG. Returns True on success.
    """
    from src.config import get_workspace_db_path, get_workspace_file_paths, get_workspace_dir

    db_path = get_workspace_db_path(workspace_id)
    paths = get_workspace_file_paths(workspace_id)
    get_workspace_dir(workspace_id)  # ensures directory exists

    if is_seeded(db_path):
        logger.info(f"Demo workspace '{workspace_id}' already seeded — skipping.")
        return True

    logger.info(f"Seeding demo data for workspace '{workspace_id}' into {db_path} ...")

    try:
        conn = duckdb.connect(str(db_path))
        _create_tables(conn)
        raw_rows, clean_rows, quarantine_rows, gold_rows = _generate_data()
        _insert_bronze(conn, raw_rows)
        _insert_silver(conn, clean_rows)
        _insert_quarantine(conn, quarantine_rows)
        _insert_gold(conn, gold_rows)
        conn.close()

        _generate_chart(gold_rows, paths["chart_png"])

        logger.info(f"Demo seeding complete: {len(clean_rows)} silver rows, {len(gold_rows)} gold rows.")
        return True

    except Exception as e:
        logger.error(f"Demo seeding failed: {e}", exc_info=True)
        return False


# ─── Schema ───────────────────────────────────────────────────────────────────

def _create_tables(conn):
    conn.execute("""
        CREATE SEQUENCE IF NOT EXISTS bronze_seq START 1;
        CREATE TABLE IF NOT EXISTS bronze_raw_sales (
            id         INTEGER DEFAULT nextval('bronze_seq') PRIMARY KEY,
            date       VARCHAR,
            category   VARCHAR,
            revenue    DOUBLE,
            cost       DOUBLE,
            units_sold INTEGER,
            ingested_at TIMESTAMP DEFAULT now(),
            source_file VARCHAR
        )
    """)
    conn.execute("""
        CREATE SEQUENCE IF NOT EXISTS silver_seq START 1;
        CREATE TABLE IF NOT EXISTS silver_clean_sales (
            id          INTEGER DEFAULT nextval('silver_seq') PRIMARY KEY,
            date        DATE,
            category    VARCHAR,
            revenue     DOUBLE,
            cost        DOUBLE,
            units_sold  INTEGER,
            profit      DOUBLE,
            margin_pct  DOUBLE,
            ingested_at TIMESTAMP DEFAULT now(),
            source_file VARCHAR
        )
    """)
    conn.execute("""
        CREATE SEQUENCE IF NOT EXISTS quarantine_seq START 1;
        CREATE TABLE IF NOT EXISTS quarantine_rejected_sales (
            id               INTEGER DEFAULT nextval('quarantine_seq') PRIMARY KEY,
            date             VARCHAR,
            category         VARCHAR,
            revenue          DOUBLE,
            cost             DOUBLE,
            units_sold       INTEGER,
            rejection_reason VARCHAR,
            ingested_at      TIMESTAMP DEFAULT now(),
            source_file      VARCHAR
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS gold_monthly_metrics (
            month            VARCHAR PRIMARY KEY,
            total_revenue    DOUBLE,
            total_cost       DOUBLE,
            profit_margin    DOUBLE,
            total_units_sold INTEGER,
            top_category     VARCHAR
        )
    """)


# ─── Data Generation ──────────────────────────────────────────────────────────

def _generate_data():
    np.random.seed(42)

    categories   = ["Electronics", "Clothing", "Home & Kitchen", "Books", "Sports"]
    base_price   = {"Electronics": 250.0, "Clothing": 45.0,
                    "Home & Kitchen": 85.0, "Books": 20.0, "Sports": 120.0}
    start        = datetime(2026, 1, 1)
    end          = datetime(2026, 6, 30)

    raw_rows        = []
    clean_rows      = []
    quarantine_rows = []

    for day_offset in range((end - start).days + 1):
        current_date = start + timedelta(days=day_offset)
        date_str     = current_date.strftime("%Y-%m-%d")
        month        = current_date.month

        # Seasonality
        season = 1.45 if month == 6 else (0.85 if month == 2 else 1.0)

        for _ in range(np.random.randint(5, 12)):
            cat      = np.random.choice(categories)
            units    = int(np.random.randint(1, 15) * season)
            avg_p    = base_price[cat]
            revenue  = round(units * np.random.uniform(avg_p * 0.9, avg_p * 1.1), 2)
            cost_r   = 0.95 if (month == 2 and cat == "Sports") else np.random.uniform(0.50, 0.70)
            cost     = round(revenue * cost_r, 2)

            raw_rows.append((date_str, cat, revenue, cost, units, "batch1.csv"))
            clean_rows.append((date_str, cat, revenue, cost, units,
                               round(revenue - cost, 2),
                               round((revenue - cost) / revenue * 100, 2)))

    # Inject dirty rows into bronze / quarantine
    dirty = [
        ("2026-03-15", None,          120.50, 60.00, 2,  "Null value in required column: category"),
        ("2026-04-10", "Electronics",  -50.00, 30.00, 1,  "Negative numeric metric: revenue"),
        ("",           "Books",         35.00, 18.00, 1,  "Null value in required column: date"),
        ("2026-05-20", "Clothing",      75.00, 40.00, 3,  "Duplicate Transaction"),
        ("2026-05-20", "Clothing",      75.00, 40.00, 3,  "Duplicate Transaction"),
    ]
    for d in dirty:
        date_, cat, rev, cost, units, reason = d
        raw_rows.append((date_, cat, rev, cost, units, "batch1.csv"))
        quarantine_rows.append((date_, cat, rev, cost, units, reason, "batch1.csv"))

    # Build Gold aggregates
    from collections import defaultdict
    monthly_revenue  = defaultdict(float)
    monthly_cost     = defaultdict(float)
    monthly_units    = defaultdict(int)
    monthly_cat_rev  = defaultdict(lambda: defaultdict(float))

    for (date_str, cat, rev, cost, units, *_) in clean_rows:
        m = date_str[:7]  # "YYYY-MM"
        monthly_revenue[m] += rev
        monthly_cost[m]    += cost
        monthly_units[m]   += units
        monthly_cat_rev[m][cat] += rev

    gold_rows = []
    for month in sorted(monthly_revenue):
        rev   = round(monthly_revenue[month], 2)
        cost  = round(monthly_cost[month], 2)
        margin = round((rev - cost) / rev * 100, 2) if rev else 0.0
        units  = monthly_units[month]
        top_cat = max(monthly_cat_rev[month], key=monthly_cat_rev[month].get)
        gold_rows.append((month, rev, cost, margin, units, top_cat))

    return raw_rows, clean_rows, quarantine_rows, gold_rows


# ─── Insertion Helpers ────────────────────────────────────────────────────────

def _insert_bronze(conn, rows):
    conn.executemany(
        "INSERT INTO bronze_raw_sales (date, category, revenue, cost, units_sold, source_file) VALUES (?, ?, ?, ?, ?, ?)",
        rows
    )

def _insert_silver(conn, rows):
    conn.executemany(
        "INSERT INTO silver_clean_sales (date, category, revenue, cost, units_sold, profit, margin_pct, source_file) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [(r[0], r[1], r[2], r[3], r[4], r[5], r[6], "batch1.csv") for r in rows]
    )

def _insert_quarantine(conn, rows):
    conn.executemany(
        "INSERT INTO quarantine_rejected_sales (date, category, revenue, cost, units_sold, rejection_reason, source_file) VALUES (?, ?, ?, ?, ?, ?, ?)",
        rows
    )

def _insert_gold(conn, rows):
    conn.executemany(
        "INSERT OR REPLACE INTO gold_monthly_metrics VALUES (?, ?, ?, ?, ?, ?)",
        rows
    )


# ─── Chart Generation ─────────────────────────────────────────────────────────

def _generate_chart(gold_rows: list, chart_path: Path):
    """Renders a bar chart of monthly revenue and saves it to disk."""
    try:
        import matplotlib
        matplotlib.use("Agg")  # non-interactive backend — required on Vercel
        import matplotlib.pyplot as plt
        import matplotlib.ticker as mticker

        months  = [r[0] for r in gold_rows]
        revenue = [r[1] for r in gold_rows]
        margins = [r[3] for r in gold_rows]

        # Short month labels e.g. "Jan", "Feb"
        labels = [datetime.strptime(m, "%Y-%m").strftime("%b '%y") for m in months]

        fig, ax1 = plt.subplots(figsize=(11, 5))
        fig.patch.set_facecolor("#0f111a")
        ax1.set_facecolor("#0f111a")

        colors = ["#6366f1" if i != len(revenue) - 1 else "#0d9488" for i in range(len(revenue))]
        bars   = ax1.bar(labels, revenue, color=colors, width=0.6, zorder=3)

        # Value labels on bars
        for bar, val in zip(bars, revenue):
            ax1.text(bar.get_x() + bar.get_width() / 2,
                     bar.get_height() + max(revenue) * 0.01,
                     f"${val:,.0f}", ha="center", va="bottom",
                     fontsize=9, color="#f3f4f6", fontweight="bold")

        # Margin line on secondary axis
        ax2 = ax1.twinx()
        ax2.plot(labels, margins, color="#f59e0b", marker="o",
                 linewidth=2, markersize=6, zorder=4, label="Profit Margin %")
        ax2.set_ylabel("Profit Margin %", color="#f59e0b", fontsize=10)
        ax2.tick_params(axis="y", colors="#f59e0b")
        ax2.set_facecolor("#0f111a")
        ax2.spines[:].set_color("none")
        ax2.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.1f%%"))

        ax1.set_title("Monthly Revenue & Profit Margin — Auto-Analyst Demo",
                       color="#f3f4f6", fontsize=13, fontweight="bold", pad=16)
        ax1.set_ylabel("Total Revenue (USD)", color="#9ca3af", fontsize=10)
        ax1.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"${x:,.0f}"))
        ax1.tick_params(axis="x", colors="#9ca3af")
        ax1.tick_params(axis="y", colors="#9ca3af")
        ax1.spines[:].set_color("none")
        ax1.grid(axis="y", color="rgba(255,255,255,0.05)", linestyle="--", zorder=0)

        fig.tight_layout(pad=2)
        chart_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(str(chart_path), dpi=140, bbox_inches="tight",
                    facecolor=fig.get_facecolor())
        plt.close(fig)
        logger.info(f"Demo chart saved to {chart_path}")
    except Exception as e:
        logger.warning(f"Chart generation failed (non-fatal): {e}")
