import os
import logging
from pathlib import Path
from flask import Flask, jsonify, request, send_from_directory, render_template

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("Web_Dashboard")

app = Flask(__name__, template_folder="templates")

@app.route('/')
def index():
    """Serves the dashboard index page."""
    return render_template('index.html')

@app.route('/api/workspaces')
def list_workspaces():
    """Scans and returns the list of all registered workspace IDs."""
    from src.config import DATA_DIR, DB_PATH
    workspaces = []
    
    # Check if default database exists
    if DB_PATH.exists():
        workspaces.append("default")
        
    # Check custom workspaces
    workspaces_dir = DATA_DIR / "workspaces"
    if workspaces_dir.exists():
        for path in workspaces_dir.iterdir():
            if path.is_dir() and (path / "analytics.duckdb").exists():
                workspaces.append(path.name)
                
    # Ensure always at least default
    if not workspaces:
        workspaces.append("default")
        
    return jsonify(workspaces)

@app.route('/api/workspace/<workspace_id>')
def workspace_details(workspace_id):
    """Fetches details, schema definitions, table previews, and KPIs for a specific workspace."""
    from src.db_adapter import DatabaseAdapter
    from src.config import get_workspace_file_paths
    
    db = DatabaseAdapter(workspace_id)
    paths = get_workspace_file_paths(workspace_id)
    
    kpis = {
        "bronze_count": 0,
        "silver_count": 0,
        "quarantine_count": 0,
        "total_revenue": "$0.00",
        "avg_margin": "0.0%",
        "has_chart": paths["chart_png"].exists(),
        "has_pptx": paths["pptx_report"].exists()
    }
    
    tables_schema = {}
    previews = {}
    
    try:
        conn = db.get_connection()
        cursor = conn.cursor()
        
        # 1. Fetch Row Counts
        try:
            cursor.execute("SELECT COUNT(*) FROM bronze_raw_sales")
            kpis["bronze_count"] = cursor.fetchone()[0]
        except Exception:
            pass
            
        try:
            cursor.execute("SELECT COUNT(*) FROM silver_clean_sales")
            kpis["silver_count"] = cursor.fetchone()[0]
        except Exception:
            pass
            
        try:
            cursor.execute("SELECT COUNT(*) FROM quarantine_rejected_sales")
            kpis["quarantine_count"] = cursor.fetchone()[0]
        except Exception:
            pass
            
        # 2. Financial Metrics Estimation (Dynamic Columns check)
        try:
            revenue_col = "revenue"
            cost_col = "cost"
            
            if db.profile:
                for col, details in db.profile.items():
                    role = details["role"]
                    if role == "currency" or col.lower() == "revenue":
                        revenue_col = col
                    elif col.lower() == "cost":
                        cost_col = col
            
            cursor.execute(f'SELECT SUM("{revenue_col}") FROM silver_clean_sales')
            total_rev = cursor.fetchone()[0] or 0.0
            kpis["total_revenue"] = f"${total_rev:,.2f}"
            
            try:
                cursor.execute(f'SELECT AVG(("{revenue_col}" - "{cost_col}") / NULLIF("{revenue_col}", 0)) FROM silver_clean_sales')
                avg_mar = cursor.fetchone()[0] or 0.0
                kpis["avg_margin"] = f"{avg_mar * 100:.1f}%"
            except Exception:
                pass
        except Exception:
            pass
            
        # 3. Dynamic Column Schema Scanning
        for table in ("bronze_raw_sales", "silver_clean_sales", "quarantine_rejected_sales", "gold_monthly_metrics"):
            try:
                if db.dialect == "postgres":
                    cursor.execute(f"SELECT column_name FROM information_schema.columns WHERE table_name = '{table}' AND table_schema = 'workspace_{workspace_id}'")
                    cols = [row[0] for row in cursor.fetchall()]
                else:
                    cursor.execute(f"PRAGMA table_info({table})")
                    cols = [row[1] for row in cursor.fetchall()]
                if cols:
                    tables_schema[table] = cols
            except Exception:
                pass
                
        # 4. Preview Data (Latest 10 rows)
        for table in ("silver_clean_sales", "quarantine_rejected_sales"):
            if table in tables_schema:
                try:
                    cols = tables_schema[table]
                    cols_str = ", ".join([f'"{c}"' for c in cols])
                    cursor.execute(f"SELECT {cols_str} FROM {table} LIMIT 10")
                    rows = cursor.fetchall()
                    previews[table] = {
                        "columns": cols,
                        "rows": [[str(cell) for cell in row] for row in rows]
                    }
                except Exception:
                    pass
                    
        conn.close()
    except Exception as e:
        logger.error(f"Failed to fetch details for workspace {workspace_id}: {e}")
        return jsonify({"error": str(e)}), 500
        
    return jsonify({
        "workspace_id": workspace_id,
        "dialect": db.dialect,
        "kpis": kpis,
        "tables": tables_schema,
        "previews": previews
    })

@app.route('/api/workspace/<workspace_id>/chart')
def workspace_chart(workspace_id):
    """Serves the generated chart image for a workspace."""
    from src.config import get_workspace_file_paths
    paths = get_workspace_file_paths(workspace_id)
    chart_path = paths["chart_png"]
    if chart_path.exists():
        return send_from_directory(chart_path.parent, chart_path.name)
    return "Chart not found", 404

@app.route('/api/workspace/<workspace_id>/pptx')
def workspace_pptx(workspace_id):
    """Downloads the PowerPoint presentation for a workspace."""
    from src.config import get_workspace_file_paths
    paths = get_workspace_file_paths(workspace_id)
    pptx_path = paths["pptx_report"]
    if pptx_path.exists():
        return send_from_directory(pptx_path.parent, pptx_path.name, as_attachment=True)
    return "Presentation not found", 404

@app.route('/api/workspace/<workspace_id>/chat', methods=['POST'])
def workspace_chat(workspace_id):
    """Processes a natural language query against the workspace's schema using the Text-to-SQL agent."""
    data = request.get_json() or {}
    question = data.get("question", "").strip()
    if not question:
        return jsonify({"error": "No question provided"}), 400
        
    from src.sql_agent import get_database_schema, process_web_agent_query
    try:
        schema_info = get_database_schema(workspace_id)
        result = process_web_agent_query(question, schema_info, workspace_id)
        return jsonify(result)
    except Exception as e:
        logger.error(f"Error executing chat for workspace {workspace_id}: {e}")
        return jsonify({"success": False, "error": str(e), "answer": f"An error occurred while answering your question: {e}"}), 500

if __name__ == '__main__':
    # Run server on port 5000
    app.run(host="0.0.0.0", port=5000, debug=True)
