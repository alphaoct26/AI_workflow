import os
import io
import base64
import logging
from pathlib import Path
from flask import Flask, jsonify, request, send_from_directory, render_template, Response

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("Web_Dashboard")

IS_VERCEL = bool(os.environ.get("VERCEL") or os.environ.get("NOW_BUILDER"))

app = Flask(__name__, template_folder="templates")

# ─── Rich hardcoded demo data (always shown on Vercel) ─────────────────────────
_DEMO_GOLD = [
    ["2026-01", "189242.94", "113032.18", "40.27", "1243", "Electronics"],
    ["2026-02", "148119.77", "100721.44", "32.00", "1087", "Electronics"],
    ["2026-03", "172384.52", "101106.83", "41.33", "1198", "Electronics"],
    ["2026-04", "165903.18",  "97881.47", "40.99", "1156", "Clothing"],
    ["2026-05", "181247.63", "107635.28", "40.64", "1219", "Electronics"],
    ["2026-06", "276485.63", "165891.37", "40.02", "1841", "Electronics"],
]

_DEMO_SILVER_COLS = ["id", "date", "category", "revenue", "cost", "units_sold", "profit", "margin_pct"]
_DEMO_SILVER_ROWS = [
    ["1", "2026-01-03", "Electronics", "2847.50", "1694.26", "12", "1153.24", "40.5"],
    ["2", "2026-01-04", "Clothing",     "189.45",   "112.17",  "4",   "77.28", "40.8"],
    ["3", "2026-01-05", "Home & Kitchen","723.80",  "432.64",  "9",  "291.16", "40.2"],
    ["4", "2026-01-06", "Books",          "82.60",   "47.43",  "4",   "35.17", "42.6"],
    ["5", "2026-01-07", "Sports",        "654.00",  "387.14",  "6",  "266.86", "40.8"],
    ["6", "2026-01-08", "Electronics",  "3102.75", "1849.14", "13", "1253.61", "40.4"],
    ["7", "2026-01-09", "Clothing",      "312.75",  "184.22",  "7",  "128.53", "41.1"],
    ["8", "2026-01-10", "Electronics",  "2614.20", "1558.29", "11", "1055.91", "40.4"],
    ["9", "2026-01-11", "Sports",        "498.00",  "295.68",  "5",  "202.32", "40.6"],
    ["10","2026-01-12", "Home & Kitchen","850.40",  "504.74", "10",  "345.66", "40.6"],
]

_DEMO_QUARANTINE_COLS = ["id", "date", "category", "revenue", "cost", "units_sold", "rejection_reason"]
_DEMO_QUARANTINE_ROWS = [
    ["1", "2026-03-15", "None",        "120.50",  "60.00",  "2", "Null value in required column: category"],
    ["2", "2026-04-10", "Electronics", "-50.00",  "30.00",  "1", "Negative numeric metric: revenue"],
    ["3", "",           "Books",        "35.00",   "18.00",  "1", "Null value in required column: date"],
    ["4", "2026-05-20", "Clothing",     "75.00",   "40.00",  "3", "Duplicate Transaction"],
    ["5", "2026-05-20", "Clothing",     "75.00",   "40.00",  "3", "Duplicate Transaction"],
]

_DEMO_RESPONSE = {
    "workspace_id": "default",
    "dialect": "duckdb",
    "is_demo": True,
    "kpis": {
        "bronze_count": 1487,
        "silver_count": 1454,
        "quarantine_count": 5,
        "total_revenue": "$1,133,383.67",
        "avg_margin": "39.2%",
        "has_chart": True,
        "has_pptx": False,
    },
    "tables": {
        "bronze_raw_sales": ["id", "date", "category", "revenue", "cost", "units_sold", "ingested_at", "source_file"],
        "silver_clean_sales": _DEMO_SILVER_COLS,
        "quarantine_rejected_sales": _DEMO_QUARANTINE_COLS,
        "gold_monthly_metrics": ["month", "total_revenue", "total_cost", "profit_margin", "total_units_sold", "top_category"],
    },
    "previews": {
        "silver_clean_sales":        {"columns": _DEMO_SILVER_COLS,     "rows": _DEMO_SILVER_ROWS},
        "quarantine_rejected_sales": {"columns": _DEMO_QUARANTINE_COLS, "rows": _DEMO_QUARANTINE_ROWS},
    },
    "gold_metrics": _DEMO_GOLD,
}

# ─── Demo chart generated in-memory (served as /api/workspace/default/chart) ───
def _build_demo_chart_png() -> bytes:
    """Render the demo revenue+margin chart into an in-memory PNG buffer."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.ticker as mticker
        from datetime import datetime

        gold    = _DEMO_GOLD
        labels  = [datetime.strptime(r[0], "%Y-%m").strftime("%b '%y") for r in gold]
        revenue = [float(r[1]) for r in gold]
        margins = [float(r[3]) for r in gold]

        fig, ax1 = plt.subplots(figsize=(11, 5))
        fig.patch.set_facecolor("#0f111a")
        ax1.set_facecolor("#0f111a")

        colors = ["#6366f1"] * (len(revenue) - 1) + ["#0d9488"]
        bars   = ax1.bar(labels, revenue, color=colors, width=0.6, zorder=3)

        for bar, val in zip(bars, revenue):
            ax1.text(bar.get_x() + bar.get_width() / 2,
                     bar.get_height() + max(revenue) * 0.01,
                     f"${val:,.0f}", ha="center", va="bottom",
                     fontsize=9, color="#f3f4f6", fontweight="bold")

        ax2 = ax1.twinx()
        ax2.plot(labels, margins, color="#f59e0b", marker="o",
                 linewidth=2, markersize=6, zorder=4)
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
        ax1.grid(axis="y", color="#ffffff0d", linestyle="--", zorder=0)

        fig.tight_layout(pad=2)
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=140, bbox_inches="tight",
                    facecolor=fig.get_facecolor())
        plt.close(fig)
        buf.seek(0)
        return buf.read()
    except Exception as e:
        logger.warning(f"Demo chart generation failed: {e}")
        return b""

_DEMO_CHART_PNG: bytes = b""  # populated lazily on first request


# ─── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    """Serves the dashboard index page."""
    return render_template("index.html")


@app.route("/api/seed", methods=["POST"])
def trigger_seed():
    """Manually triggers demo data seeding for a workspace."""
    body        = request.get_json(silent=True, force=True) or {}
    workspace_id = body.get("workspace_id", "default")
    try:
        from src.demo_seeder import seed
        ok = seed(workspace_id)
        return jsonify({"seeded": ok, "workspace_id": workspace_id})
    except Exception as e:
        # Non-fatal — demo fallback will still serve data
        return jsonify({"seeded": False, "error": str(e), "demo_fallback": True})


@app.route("/api/workspaces")
def list_workspaces():
    """Returns the list of registered workspace IDs."""
    workspaces = []
    try:
        from src.config import DATA_DIR, DB_PATH
        if DB_PATH.exists():
            workspaces.append("default")
        workspaces_dir = DATA_DIR / "workspaces"
        if workspaces_dir.exists():
            for path in workspaces_dir.iterdir():
                if path.is_dir() and (path / "analytics.duckdb").exists():
                    workspaces.append(path.name)
    except Exception:
        pass
    if not workspaces:
        workspaces.append("default")
    return jsonify(workspaces)


@app.route("/api/workspace/<workspace_id>")
def workspace_details(workspace_id):
    """Returns KPIs, schema, table previews, and Gold metrics for a workspace.
    Falls back to rich hardcoded demo data when the database is empty or unavailable.
    """
    # ── Try real DB first ──
    try:
        from src.db_adapter import DatabaseAdapter
        from src.config import get_workspace_file_paths

        db    = DatabaseAdapter(workspace_id)
        paths = get_workspace_file_paths(workspace_id)
        conn  = db.get_connection()
        cur   = conn.cursor()

        bronze_count = quarantine_count = silver_count = 0
        total_rev    = 0.0
        avg_mar      = 0.0
        tables_schema, previews, gold_metrics = {}, {}, []

        try:
            cur.execute("SELECT COUNT(*) FROM bronze_raw_sales")
            bronze_count = cur.fetchone()[0]
        except Exception:
            pass
        try:
            cur.execute("SELECT COUNT(*) FROM silver_clean_sales")
            silver_count = cur.fetchone()[0]
        except Exception:
            pass
        try:
            cur.execute("SELECT COUNT(*) FROM quarantine_rejected_sales")
            quarantine_count = cur.fetchone()[0]
        except Exception:
            pass

        # If no real data → fall through to demo fallback
        if silver_count == 0:
            conn.close()
            raise ValueError("empty_db")

        try:
            cur.execute('SELECT SUM("revenue") FROM silver_clean_sales')
            total_rev = cur.fetchone()[0] or 0.0
        except Exception:
            pass
        try:
            cur.execute('SELECT AVG(("revenue"-"cost")/NULLIF("revenue",0)) FROM silver_clean_sales')
            avg_mar = cur.fetchone()[0] or 0.0
        except Exception:
            pass

        for table in ("bronze_raw_sales", "silver_clean_sales",
                      "quarantine_rejected_sales", "gold_monthly_metrics"):
            try:
                cur.execute(f"PRAGMA table_info({table})")
                cols = [r[1] for r in cur.fetchall()]
                if cols:
                    tables_schema[table] = cols
            except Exception:
                pass

        for table in ("silver_clean_sales", "quarantine_rejected_sales"):
            if table in tables_schema:
                try:
                    cols     = tables_schema[table]
                    cols_str = ", ".join([f'"{c}"' for c in cols])
                    cur.execute(f"SELECT {cols_str} FROM {table} LIMIT 10")
                    rows = cur.fetchall()
                    previews[table] = {
                        "columns": cols,
                        "rows": [[str(c) for c in row] for row in rows],
                    }
                except Exception:
                    pass

        try:
            cur.execute(
                "SELECT month, total_revenue, total_cost, profit_margin, "
                "total_units_sold, top_category FROM gold_monthly_metrics ORDER BY month"
            )
            gold_metrics = [[str(c) for c in row] for row in cur.fetchall()]
        except Exception:
            pass

        conn.close()

        return jsonify({
            "workspace_id": workspace_id,
            "dialect":      db.dialect,
            "is_demo":      False,
            "kpis": {
                "bronze_count":    bronze_count,
                "silver_count":    silver_count,
                "quarantine_count": quarantine_count,
                "total_revenue":   f"${total_rev:,.2f}",
                "avg_margin":      f"{avg_mar * 100:.1f}%",
                "has_chart":       paths["chart_png"].exists(),
                "has_pptx":        paths["pptx_report"].exists(),
            },
            "tables":       tables_schema,
            "previews":     previews,
            "gold_metrics": gold_metrics,
        })

    except Exception as e:
        if "empty_db" not in str(e):
            logger.warning(f"DB unavailable for '{workspace_id}', serving demo data: {e}")
        # ── Demo fallback ──
        resp            = dict(_DEMO_RESPONSE)
        resp["workspace_id"] = workspace_id
        return jsonify(resp)


@app.route("/api/workspace/<workspace_id>/chart")
def workspace_chart(workspace_id):
    """Serves the workspace chart PNG. Falls back to an in-memory demo chart."""
    global _DEMO_CHART_PNG
    try:
        from src.config import get_workspace_file_paths
        paths      = get_workspace_file_paths(workspace_id)
        chart_path = paths["chart_png"]
        if chart_path.exists():
            return send_from_directory(chart_path.parent, chart_path.name)
    except Exception:
        pass

    # Generate demo chart on first request, cache for the process lifetime
    if not _DEMO_CHART_PNG:
        _DEMO_CHART_PNG = _build_demo_chart_png()
    if _DEMO_CHART_PNG:
        return Response(_DEMO_CHART_PNG, mimetype="image/png")
    return "Chart not found", 404


@app.route("/api/workspace/<workspace_id>/pptx")
def workspace_pptx(workspace_id):
    """Downloads the PowerPoint presentation for a workspace."""
    try:
        from src.config import get_workspace_file_paths
        paths     = get_workspace_file_paths(workspace_id)
        pptx_path = paths["pptx_report"]
        if pptx_path.exists():
            return send_from_directory(pptx_path.parent, pptx_path.name,
                                       as_attachment=True)
    except Exception:
        pass
    return jsonify({"error": "Presentation not yet generated. Run main.py first."}), 404


@app.route("/api/workspace/<workspace_id>/chat", methods=["POST"])
def workspace_chat(workspace_id):
    """Processes a natural language query using the Text-to-SQL agent.
    Returns a structured JSON response always — never HTML.
    """
    try:
        data     = request.get_json(force=True, silent=True) or {}
        question = data.get("question", "").strip()
        if not question:
            return jsonify({"success": False, "error": "No question provided",
                            "answer": "Please type a question."}), 400

        from src.sql_agent import get_database_schema, process_web_agent_query
        schema_info = get_database_schema(workspace_id)
        result      = process_web_agent_query(question, schema_info, workspace_id)
        return jsonify(result)

    except Exception as e:
        logger.error(f"Chat error for workspace '{workspace_id}': {e}", exc_info=True)
        return jsonify({
            "success": False,
            "sql":     None,
            "columns": [],
            "rows":    [],
            "error":   str(e),
            "answer":  (
                "⚠️ The AI SQL Agent requires an active database connection and LLM API "
                "keys configured in environment variables. In this live demo the agent "
                "runs against the demo database — please ensure GEMINI_API_KEYS or "
                "OPENAI_API_KEY are set in Vercel's project settings."
            ),
        })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
