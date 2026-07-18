"""
Auto-Analyst SaaS — Web Dashboard (Vercel-compatible)
Self-contained Flask app: demo data is hardcoded in-memory.
All src.* imports are deferred and wrapped so any import failure
gracefully falls back to demo data without crashing the server.
"""
import os
import logging
from flask import Flask, jsonify, request, send_from_directory, render_template, Response

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("AutoAnalyst")

app = Flask(__name__, template_folder="templates")

# ─── Hardcoded demo dataset ──────────────────────────────────────────────────

DEMO_GOLD = [
    ["2026-01", "189242.94", "113032.18", "40.27", "1243", "Electronics"],
    ["2026-02", "148119.77", "100721.44", "32.00", "1087", "Electronics"],
    ["2026-03", "172384.52", "101106.83", "41.33", "1198", "Electronics"],
    ["2026-04", "165903.18",  "97881.47", "40.99", "1156", "Clothing"],
    ["2026-05", "181247.63", "107635.28", "40.64", "1219", "Electronics"],
    ["2026-06", "276485.63", "165891.37", "40.02", "1841", "Electronics"],
]

DEMO_SILVER_COLS = ["id","date","category","revenue","cost","units_sold","profit","margin_pct"]
DEMO_SILVER_ROWS = [
    ["1",  "2026-01-03","Electronics",   "2847.50","1694.26","12","1153.24","40.5"],
    ["2",  "2026-01-04","Clothing",       "189.45", "112.17", "4",  "77.28","40.8"],
    ["3",  "2026-01-05","Home & Kitchen", "723.80", "432.64", "9", "291.16","40.2"],
    ["4",  "2026-01-06","Books",           "82.60",  "47.43", "4",  "35.17","42.6"],
    ["5",  "2026-01-07","Sports",         "654.00", "387.14", "6", "266.86","40.8"],
    ["6",  "2026-01-08","Electronics",   "3102.75","1849.14","13","1253.61","40.4"],
    ["7",  "2026-01-09","Clothing",       "312.75", "184.22", "7", "128.53","41.1"],
    ["8",  "2026-01-10","Electronics",   "2614.20","1558.29","11","1055.91","40.4"],
    ["9",  "2026-01-11","Sports",         "498.00", "295.68", "5", "202.32","40.6"],
    ["10", "2026-01-12","Home & Kitchen", "850.40", "504.74","10", "345.66","40.6"],
]

DEMO_Q_COLS = ["id","date","category","revenue","cost","units_sold","rejection_reason"]
DEMO_Q_ROWS = [
    ["1","2026-03-15","None",        "120.50","60.00","2","Null value in required column: category"],
    ["2","2026-04-10","Electronics",  "-50.00","30.00","1","Negative numeric metric: revenue"],
    ["3","",          "Books",         "35.00","18.00","1","Null value in required column: date"],
    ["4","2026-05-20","Clothing",      "75.00","40.00","3","Duplicate Transaction"],
    ["5","2026-05-20","Clothing",      "75.00","40.00","3","Duplicate Transaction"],
]

DEMO_PAYLOAD = {
    "workspace_id": "default",
    "dialect":  "duckdb",
    "is_demo":  True,
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
        "bronze_raw_sales":          ["id","date","category","revenue","cost","units_sold","ingested_at","source_file"],
        "silver_clean_sales":        DEMO_SILVER_COLS,
        "quarantine_rejected_sales": DEMO_Q_COLS,
        "gold_monthly_metrics":      ["month","total_revenue","total_cost","profit_margin","total_units_sold","top_category"],
    },
    "previews": {
        "silver_clean_sales":        {"columns": DEMO_SILVER_COLS, "rows": DEMO_SILVER_ROWS},
        "quarantine_rejected_sales": {"columns": DEMO_Q_COLS,      "rows": DEMO_Q_ROWS},
    },
    "gold_metrics": DEMO_GOLD,
}


_chart_cache: bytes = b""


def _make_demo_chart() -> bytes:
    """Generate a bar+line chart as an SVG — zero dependencies."""
    months  = ["Jan '26", "Feb '26", "Mar '26", "Apr '26", "May '26", "Jun '26"]
    revenue = [189242, 148119, 172384, 165903, 181247, 276485]
    margins = [40.27, 32.00, 41.33, 40.99, 40.64, 40.02]

    W, H = 900, 400
    pad_l, pad_r, pad_t, pad_b = 80, 40, 40, 60
    chart_w = W - pad_l - pad_r
    chart_h = H - pad_t - pad_b

    max_rev = max(revenue)
    min_mar, max_mar = min(margins) - 2, max(margins) + 2

    bar_w = chart_w / len(revenue) * 0.55
    bar_gap = chart_w / len(revenue)

    def rx(i):  # bar center x
        return pad_l + i * bar_gap + bar_gap / 2

    def ry(v):  # revenue → y
        return pad_t + chart_h - (v / max_rev) * chart_h

    def my(v):  # margin → y
        return pad_t + chart_h - ((v - min_mar) / (max_mar - min_mar)) * chart_h

    bars = ""
    for i, (rev, label) in enumerate(zip(revenue, months)):
        x = rx(i) - bar_w / 2
        y = ry(rev)
        h = chart_h - (y - pad_t)
        color = "#0d9488" if i == len(revenue) - 1 else "#6366f1"
        bars += f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" height="{h:.1f}" fill="{color}" rx="4"/>\n'
        bars += f'<text x="{rx(i):.1f}" y="{y - 6:.1f}" fill="#f3f4f6" font-size="11" text-anchor="middle" font-weight="bold">${rev//1000}K</text>\n'
        bars += f'<text x="{rx(i):.1f}" y="{H - 18:.1f}" fill="#9ca3af" font-size="11" text-anchor="middle">{label}</text>\n'

    points = " ".join(f"{rx(i):.1f},{my(m):.1f}" for i, m in enumerate(margins))
    dots = "".join(f'<circle cx="{rx(i):.1f}" cy="{my(m):.1f}" r="5" fill="#f59e0b"/>' for i, m in enumerate(margins))
    margin_labels = "".join(
        f'<text x="{rx(i):.1f}" y="{my(m) - 9:.1f}" fill="#f59e0b" font-size="10" text-anchor="middle">{m:.1f}%</text>'
        for i, m in enumerate(margins)
    )

    # Y-axis labels (revenue)
    y_labels = ""
    for tick in [0, 50000, 100000, 150000, 200000, 250000]:
        y = ry(tick)
        y_labels += f'<line x1="{pad_l}" y1="{y:.1f}" x2="{W - pad_r}" y2="{y:.1f}" stroke="#ffffff0d" stroke-width="1"/>\n'
        y_labels += f'<text x="{pad_l - 6}" y="{y + 4:.1f}" fill="#9ca3af" font-size="10" text-anchor="end">${tick//1000}K</text>\n'

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">
  <rect width="{W}" height="{H}" fill="#0f111a" rx="12"/>
  <text x="{W//2}" y="24" fill="#f3f4f6" font-size="14" font-weight="bold" text-anchor="middle" font-family="sans-serif">
    Monthly Revenue &amp; Profit Margin — Auto-Analyst Demo
  </text>
  <g font-family="sans-serif">
    {y_labels}
    {bars}
    <polyline points="{points}" fill="none" stroke="#f59e0b" stroke-width="2.5" stroke-linejoin="round"/>
    {dots}
    {margin_labels}
  </g>
</svg>"""
    return svg.encode("utf-8")


# ─── Helpers ────────────────────────────────────────────────────────────────

def _demo(workspace_id: str) -> dict:
    p = dict(DEMO_PAYLOAD)
    p["workspace_id"] = workspace_id
    return p


def _try_db_details(workspace_id: str) -> dict | None:
    """Try to read real DuckDB data. Returns None on any failure or empty DB."""
    try:
        from src.db_adapter import DatabaseAdapter
        from src.config import get_workspace_file_paths

        db    = DatabaseAdapter(workspace_id)
        paths = get_workspace_file_paths(workspace_id)
        conn  = db.get_connection()
        cur   = conn.cursor()

        counts = {}
        for tbl, k in [("bronze_raw_sales","b"),("silver_clean_sales","s"),("quarantine_rejected_sales","q")]:
            try:
                cur.execute(f"SELECT COUNT(*) FROM {tbl}")
                counts[k] = cur.fetchone()[0]
            except Exception:
                counts[k] = 0

        if counts.get("s", 0) == 0:
            conn.close()
            return None

        rev = mar = 0.0
        try:
            cur.execute('SELECT SUM("revenue") FROM silver_clean_sales')
            rev = cur.fetchone()[0] or 0.0
        except Exception:
            pass
        try:
            cur.execute('SELECT AVG(("revenue"-"cost")/NULLIF("revenue",0)) FROM silver_clean_sales')
            mar = cur.fetchone()[0] or 0.0
        except Exception:
            pass

        schema, previews, gold = {}, {}, []
        for tbl in ("bronze_raw_sales","silver_clean_sales","quarantine_rejected_sales","gold_monthly_metrics"):
            try:
                cur.execute(f"PRAGMA table_info({tbl})")
                cols = [r[1] for r in cur.fetchall()]
                if cols:
                    schema[tbl] = cols
            except Exception:
                pass

        for tbl in ("silver_clean_sales","quarantine_rejected_sales"):
            if tbl in schema:
                try:
                    cs = ", ".join(f'"{c}"' for c in schema[tbl])
                    cur.execute(f"SELECT {cs} FROM {tbl} LIMIT 10")
                    previews[tbl] = {"columns": schema[tbl],
                                     "rows": [[str(c) for c in r] for r in cur.fetchall()]}
                except Exception:
                    pass

        try:
            cur.execute("SELECT month,total_revenue,total_cost,profit_margin,total_units_sold,top_category FROM gold_monthly_metrics ORDER BY month")
            gold = [[str(c) for c in r] for r in cur.fetchall()]
        except Exception:
            pass

        conn.close()
        return {
            "workspace_id": workspace_id,
            "dialect":  db.dialect,
            "is_demo":  False,
            "kpis": {
                "bronze_count":    counts["b"],
                "silver_count":    counts["s"],
                "quarantine_count": counts["q"],
                "total_revenue":   f"${rev:,.2f}",
                "avg_margin":      f"{mar * 100:.1f}%",
                "has_chart":       paths["chart_png"].exists(),
                "has_pptx":        paths["pptx_report"].exists(),
            },
            "tables":       schema,
            "previews":     previews,
            "gold_metrics": gold,
        }
    except Exception as e:
        logger.warning(f"DB read failed ({workspace_id}): {e}")
        return None


# ─── Routes ─────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/workspaces")
def list_workspaces():
    try:
        from src.config import DATA_DIR, DB_PATH
        ws = []
        if DB_PATH.exists():
            ws.append("default")
        d = DATA_DIR / "workspaces"
        if d.exists():
            for p in d.iterdir():
                if p.is_dir() and (p / "analytics.duckdb").exists():
                    ws.append(p.name)
        return jsonify(ws or ["default"])
    except Exception:
        return jsonify(["default"])


@app.route("/api/workspace/<workspace_id>")
def workspace_details(workspace_id):
    result = _try_db_details(workspace_id)
    if result:
        return jsonify(result)
    return jsonify(_demo(workspace_id))


@app.route("/api/seed", methods=["POST"])
def trigger_seed():
    try:
        from src.demo_seeder import seed
        body = request.get_json(silent=True, force=True) or {}
        ok   = seed(body.get("workspace_id", "default"))
        return jsonify({"seeded": ok})
    except Exception as e:
        return jsonify({"seeded": False, "error": str(e), "demo_fallback": True})


@app.route("/api/workspace/<workspace_id>/chart")
def workspace_chart(workspace_id):
    global _chart_cache
    # Try real file first
    try:
        from src.config import get_workspace_file_paths
        p = get_workspace_file_paths(workspace_id)["chart_png"]
        if p.exists():
            return send_from_directory(p.parent, p.name)
    except Exception:
        pass
    # Fall back to in-memory SVG demo chart
    if not _chart_cache:
        _chart_cache = _make_demo_chart()
    if _chart_cache:
        return Response(_chart_cache, mimetype="image/svg+xml",
                        headers={"Cache-Control": "public, max-age=3600"})
    return "", 404


@app.route("/api/workspace/<workspace_id>/pptx")
def workspace_pptx(workspace_id):
    try:
        from src.config import get_workspace_file_paths
        p = get_workspace_file_paths(workspace_id)["pptx_report"]
        if p.exists():
            return send_from_directory(p.parent, p.name, as_attachment=True)
    except Exception:
        pass
    return jsonify({"error": "Run main.py first to generate the presentation."}), 404


@app.route("/api/workspace/<workspace_id>/chat", methods=["POST"])
def workspace_chat(workspace_id):
    try:
        data     = request.get_json(force=True, silent=True) or {}
        question = data.get("question", "").strip()
        if not question:
            return jsonify({"success": False, "answer": "Please type a question."}), 400
        from src.sql_agent import get_database_schema, process_web_agent_query
        schema = get_database_schema(workspace_id)
        return jsonify(process_web_agent_query(question, schema, workspace_id))
    except Exception as e:
        logger.error(f"Chat error: {e}")
        return jsonify({
            "success": False, "sql": None, "columns": [], "rows": [],
            "answer": (
                "The AI SQL Agent needs LLM API keys (GEMINI_API_KEYS or OPENAI_API_KEY) "
                "set as environment variables in Vercel project settings to answer questions."
            ),
        })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
