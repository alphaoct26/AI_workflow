import pytest
import shutil
import pandas as pd
from pathlib import Path
from src.etl_orchestrator import ETLPipeline
from src.sql_agent import execute_query
from src.config import get_workspace_dir, get_workspace_file_paths

def test_v3_multi_tenant_isolation():
    """Verify that multiple tenants (workspaces) remain completely isolated in databases, schema profiles, and file structures."""
    workspace_1 = "tesla-finance"
    workspace_2 = "ford-hr"
    
    # 1. Clean up any previous test workspace directories to start fresh
    for ws in (workspace_1, workspace_2):
        w_dir = get_workspace_dir(ws)
        if w_dir.exists():
            shutil.rmtree(w_dir)
            
    # 2. Run ETL pipeline for Workspace 1 (Tesla)
    tesla_paths = get_workspace_file_paths(workspace_1)
    tesla_dir = get_workspace_dir(workspace_1)
    
    tesla_profile = {
        "transaction_date": {"dtype": "str", "role": "date"},
        "segment": {"dtype": "str", "role": "dimension"},
        "value": {"dtype": "float", "role": "measure"},
        "units": {"dtype": "int", "role": "measure"}
    }
    
    # Write a test CSV for Tesla matching this schema
    tesla_csv = tesla_dir / "tesla_raw.csv"
    df_tesla = pd.DataFrame([
        {"transaction_date": "2026-01-15", "segment": "Automotive", "value": 50000.0, "units": 1},
        {"transaction_date": "2026-02-15", "segment": "Energy", "value": 15000.0, "units": 3},
        {"transaction_date": "2026-02-15", "segment": "Energy", "value": 15000.0, "units": 3} # duplicate
    ])
    df_tesla.to_csv(tesla_csv, index=False)
    
    pipeline_tesla = ETLPipeline(workspace_id=workspace_1)
    pipeline_tesla.db.load_profile(tesla_profile)
    
    # Force schema creation and ingest
    pipeline_tesla.create_schema(str(tesla_csv))
    pipeline_tesla.run_bronze_ingest(str(tesla_csv))
    pipeline_tesla.run_silver_transform()
    
    pipeline_tesla.db.set_gold_query(
        "SELECT segment, SUM(value) as total_value, SUM(units) as total_units FROM silver_clean_sales GROUP BY segment"
    )
    pipeline_tesla.run_gold_aggregation()
    pipeline_tesla.export_gold_to_csv()
    
    # 3. Run ETL pipeline for Workspace 2 (Ford)
    ford_paths = get_workspace_file_paths(workspace_2)
    ford_dir = get_workspace_dir(workspace_2)
    
    ford_profile = {
        "pay_date": {"dtype": "str", "role": "date"},
        "department": {"dtype": "str", "role": "dimension"},
        "salary": {"dtype": "float", "role": "measure"}
    }
    
    ford_csv = ford_dir / "ford_raw.csv"
    df_ford = pd.DataFrame([
        {"pay_date": "2026-01-01", "department": "Engineering", "salary": 9500.0},
        {"pay_date": "2026-01-01", "department": "HR", "salary": 6000.0}
    ])
    df_ford.to_csv(ford_csv, index=False)
    
    pipeline_ford = ETLPipeline(workspace_id=workspace_2)
    pipeline_ford.db.load_profile(ford_profile)
    
    pipeline_ford.create_schema(str(ford_csv))
    pipeline_ford.run_bronze_ingest(str(ford_csv))
    pipeline_ford.run_silver_transform()
    
    pipeline_ford.db.set_gold_query(
        "SELECT department, SUM(salary) as total_salary FROM silver_clean_sales GROUP BY department"
    )
    pipeline_ford.run_gold_aggregation()
    pipeline_ford.export_gold_to_csv()
    
    # 4. Assert file-system isolation
    assert tesla_paths["raw_csv"].parent != ford_paths["raw_csv"].parent
    assert Path(pipeline_tesla.db_path).exists()
    assert Path(pipeline_ford.db_path).exists()
    assert tesla_paths["clean_csv"].exists()
    assert ford_paths["clean_csv"].exists()
    
    # 5. Assert database data isolation via execution query scoping
    cols_tesla, rows_tesla = execute_query("SELECT * FROM silver_clean_sales;", workspace_id=workspace_1)
    cols_ford, rows_ford = execute_query("SELECT * FROM silver_clean_sales;", workspace_id=workspace_2)
    
    assert "segment" in cols_tesla
    assert "value" in cols_tesla
    assert "department" not in cols_tesla
    assert len(rows_tesla) == 2
    
    assert "department" in cols_ford
    assert "salary" in cols_ford
    assert "segment" not in cols_ford
    assert len(rows_ford) == 2
    
    # 6. Verify that SQL Agent queries for Tesla cannot read Ford tables/columns
    with pytest.raises(Exception) as exc_info:
        execute_query("SELECT salary FROM silver_clean_sales;", workspace_id=workspace_1)
    assert any(kw in str(exc_info.value).lower() for kw in ("not found", "does not exist", "no such column"))
    
    # Clean up workspace test directories
    shutil.rmtree(tesla_dir)
    shutil.rmtree(ford_dir)
