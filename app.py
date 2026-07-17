import os
import io
import logging
from flask import Flask, jsonify, request, send_from_directory, render_template, Response

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("Web_Dashboard")

app = Flask(__name__, template_folder="templates")

# ─── Rich hardcoded demo data ────────────────────────────────────────────────
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
    ["1",  "2026-01-03", "Electronics",    "2847.50", "1694.26", "12", "1153.24", "40.5"],
    ["2",  "2026-01-04", "Clothing",        "189.45",  "112.17",  "4",   "77.28", "40.8"],
    ["3",  "2026-01-05", "Home & Kitchen",  "723.80",  "432.64",  "9",  "291.16", "40.2"],
    ["4",  "2026-01-06", "Books",            "82.60",   "47.43",  "4",   "35.17", "42.6"],
    ["5",  "2026-01-07", "Sports",          "654.00",  "387.14",  "6",  "266.86", "40.8"],
    ["6",  "2026-01-08", "Electronics",    "3102.75", "1849.14", "13", "1253.61", "40.4"],
    ["7",  "2026-01-09", "Clothing",        "312.75",  "184.22",  "7",  "128.53", "41.1"],
    ["8",  "2026-01-10", "Electronics",    "2614.20", "1558.29", "11", "1055.91", "40.4"],
    ["9",  "2026-01-11", "Sports",          "498.00",  "295.68",  "5",  "202.32", "40.6"],
    ["10", "2026-01-12", "Home & Kitchen",  "850.40",  "504.74", "10",  "345.66", "40.6"],
]

_DEMO_QUARANTINE_COLS = ["id", "date", "category", "revenue", "cost", "units_sold", "rejection_reason"]
_DEMO_QUARANTINE_ROWS = [
    ["1", "2026-03-15", "None",        "120.50", "60.00", "2", "Null value in required column: category"],
    ["2", "2026-04-10", "Electronics",  "-50.00", "30.00", "1", "Negative numeric metric: revenue"],
    ["3", "",           "Books",         "35.00", "18.00", "1", "Null value in required column: date"],
    ["4", "2026-05-20", "Clothing",      "75.00", "40.00", "3", "Duplicate Transaction"],
    ["5", "2026-05-20", "Clothing",      "75.00", "40.00", "3", "Duplicate Transaction"],
]

_DEMO_RESPONSE = {
    "workspace_id": "default",
    "dialect": "duckdb",
    "is_demo": True,
    "kpis": {
        "bronze_count":    1487,
        "silver_count":    1454,
        "quarantine_count": 5,
        "total_revenue":   "$1,133,383.67",
        "avg_margin":      "39.2%",
        "has_chart":       True,
        "has_pptx":        False,
    },
    "tables": {
        "bronze_raw_sales":        ["id","date","category","revenue","cost","units_sold","ingested_at","source_file"],
        "silver_clean_sales":      _DEMO_SILVER_COLS,
        "quarantine_rejected_sales": _DEMO_QUARANTINE_COLS,
        "gold_monthly_metrics":    ["month","total_revenue","total_cost","profit_margin","total_units_sold","top_category"],
    },
    "previews": {
        "silver_clean_sales":        {"columns": _DEMO_SILVER_COLS,     "rows": _DEMO_SILVER_ROWS},
        "quarantine_rejected_sales": {"columns": _DEMO_QUARANTINE_COLS, "rows": _DEMO_QUARANTINE_ROWS},
    },
    "gold_metrics": _DEMO_GOLD,
}

# cache for in-memory chart
_DEMO_CHART_PNG: bytes = b""


def _build_demo_chart() -> bytes:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.ticker as mticker
        from datetime import datetime

        labels  = [datetime.strptime(r[0], "%Y-%m").strftime("%b '%y") for r in _DEMO_GOLD]
        revenue = [float(r[1]) for r in _DEMO_GOLD]
        margins = [float(r[3]) for r in _DEMO_GOLD]

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
        ax2.plot(labels, margins, color="#f59e0b", marker="o", linewidth=2, markersize=6, zorder=4)
        ax2.set_ylabel("Profit Margin %", color="#f59e0b", fontsize=10)
        ax2.tick_params(axis="y", colors="#f59e0b")
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
        ax2.set_facecolor("#0f111a")

        fig.tight_layout(pad=2)
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=140, bbox_inches="tight",
                    facecolor=fig.get_facecolor())
        plt.close(fig)
        buf.seek(0)
        return buf.read()
    except Exception as e:
        logger.warning(f"Chart generation failed: {e}")
        return b""


# ─── Routes ──────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/seed", methods=["POST"])
def trigger_seed():
    """Tries to seed DuckDB; non-fatal on Vercel since demo data is always served."""
    try:
        from src.demo_seeder import seed
        body = request.get_json(silent=True, force=True) or {}
        ok   = seed(body.get("workspace_id", "default"))
        return jsonify({"seeded": ok})
    except Exception as e:
        return jsonify({"seeded": False, "error": str(e), "demo_fallback": True})


@app.route("/api/workspaces")
def list_workspaces():
    """Always returns at least ['default']. Never crashes."""
    workspaces = []
    try:
        from src.config import DATA_DIR, DB_PATH
        if DB_PATH.exists():
            workspaces.append("default")
        ws_dir = DATA_DIR / "workspaces"
        if ws_dir.exists():
            for p in ws_dir.iterdir():
                if p.is_dir() and (p / "analytics.duckdb").exists():
                    workspaces.append(p.name)
    except Exception:
        pass
    return jsonify(workspaces or ["default"])


@app.route("/api/workspace/<workspace_id>")
def workspace_details(workspace_id):
    """Returns workspace KPIs, tables, previews and Gold metrics.
    Always returns valid JSON — falls back to demo data on any failure."""
    try:
        from src.db_adapter import DatabaseAdapter
        from src.config import get_workspace_file_paths

        db    = DatabaseAdapter(workspace_id)
        paths = get_workspace_file_paths(workspace_id)
        conn  = db.get_connection()
        cur   = conn.cursor()

        counts = {"bronze": 0, "silver": 0, "quarantine": 0}
        for table, key in [("bronze_raw_sales", "bronze"),
                           ("silver_clean_sales", "silver"),
                           ("quarantine_rejected_sales", "quarantine")]:
            try:
                cur.execute(f"SELECT COUNT(*) FROM {table}")
                counts[key] = cur.fetchone()[0]
            except Exception:
                pass

        if counts["silver"] == 0:
            conn.close()
            raise ValueError("empty_db")

        total_rev = avg_mar = 0.0
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

        tables_schema, previews, gold_metrics = {}, {}, []
        for table in ("bronze_raw_sales","silver_clean_sales","quarantine_rejected_sales","gold_monthly_metrics"):
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
                    cols_str = ", ".join(f'"{c}"' for c in tables_schema[table])
                    cur.execute(f"SELECT {cols_str} FROM {table} LIMIT 10")
                    previews[table] = {
                        "columns": tables_schema[table],
                        "rows":    [[str(c) for c in row] for row in cur.fetchall()],
                    }
                except Exception:
                    pass

        try:
            cur.execute("SELECT month, total_revenue, total_cost, profit_margin, total_units_sold, top_category FROM gold_monthly_metrics ORDER BY month")
            gold_metrics = [[str(c) for c in row] for row in cur.fetchall()]
        except Exception:
            pass

        conn.close()
        return jsonify({
            "workspace_id": workspace_id,
            "dialect":  db.dialect,
            "is_demo":  False,
            "kpis": {
                "bronze_count":    counts["bronze"],
                "silver_count":    counts["silver"],
                "quarantine_count": counts["quarantine"],
                "total_revenue":   f"${total_rev:,.2f}",
                "avg_margin":      f"{avg_mar * 100:.1f}%",
                "has_chart":       paths["chart_png"].exists(),
                "has_pptx":        paths["pptx_report"].exists(),
            },
            "tables":       tables_schema,
            "previews":     previews,
            "gold_metrics": gold_metrics,
        })

    except Exception as exc:
        if "empty_db" not in str(exc):
            logger.warning(f"Demo fallback for '{workspace_id}': {exc}")
        resp = dict(_DEMO_RESPONSE)
        resp["workspace_id"] = workspace_id
        return jsonify(resp)


@app.route("/api/workspace/<workspace_id>/chart")
def workspace_chart(workspace_id):
    """Serves chart PNG — generates in-memory demo chart as fallback."""
    global _DEMO_CHART_PNG
    try:
        from src.config import get_workspace_file_paths
        p = get_workspace_file_paths(workspace_id)["chart_png"]
        if p.exists():
            return send_from_directory(p.parent, p.name)
    except Exception:
        pass
    if not _DEMO_CHART_PNG:
        _DEMO_CHART_PNG = _build_demo_chart()
    if _DEMO_CHART_PNG:
        return Response(_DEMO_CHART_PNG, mimetype="image/png")
    return "Chart not available", 404


@app.route("/api/workspace/<workspace_id>/pptx")
def workspace_pptx(workspace_id):
    try:
        from src.config import get_workspace_file_paths
        p = get_workspace_file_paths(workspace_id)["pptx_report"]
        if p.exists():
            return send_from_directory(p.parent, p.name, as_attachment=True)
    except Exception:
        pass
    return jsonify({"error": "No presentation found. Run main.py to generate it."}), 404


@app.route("/api/workspace/<workspace_id>/chat", methods=["POST"])
def workspace_chat(workspace_id):
    """Text-to-SQL agent chat. Always returns JSON."""
    try:
        data     = request.get_json(force=True, silent=True) or {}
        question = data.get("question", "").strip()
        if not question:
            return jsonify({"success": False, "answer": "Please type a question."}), 400
        from src.sql_agent import get_database_schema, process_web_agent_query
        schema_info = get_database_schema(workspace_id)
        return jsonify(process_web_agent_query(question, schema_info, workspace_id))
    except Exception as e:
        logger.error(f"Chat error: {e}", exc_info=True)
        return jsonify({
            "success": False,
            "sql": None, "columns": [], "rows": [],
            "answer": (
                "The AI SQL Agent requires LLM API keys configured in environment variables "
                "(GEMINI_API_KEYS or OPENAI_API_KEY). Set these in your Vercel project settings "
                "to enable live natural language queries against the demo database."
            ),
        })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
