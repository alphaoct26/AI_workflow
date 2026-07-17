import os
import json
import sqlite3
import pytest
import pandas as pd
from pathlib import Path
from unittest.mock import patch, MagicMock
from src.etl_orchestrator import ETLPipeline
from src.db_adapter import DatabaseAdapter
from src.schema_profiler import SchemaProfiler

# Define mock CSV file paths inside workspace landing zone
TEST_DIR = Path("d:/AI_workflow_project/data/test_runs")
TEST_DIR.mkdir(parents=True, exist_ok=True)

CSV_ECOMMERCE = TEST_DIR / "ecommerce.csv"
CSV_HR = TEST_DIR / "hr_payroll.csv"
CSV_HEALTHCARE = TEST_DIR / "healthcare_claims.csv"

# 1. Dataset Mock Data
DATA_ECOMMERCE = [
    {"date": "2026-01-05", "category": "Electronics", "revenue": "1500.00", "cost": "900.00", "units_sold": "5"},
    {"date": "2026-01-05", "category": "Electronics", "revenue": "1500.00", "cost": "900.00", "units_sold": "5"}, # Duplicate
    {"date": "2026-02-14", "category": None, "revenue": "45.00", "cost": "30.00", "units_sold": "1"},          # Null Category
    {"date": "2026-03-20", "category": "Clothing", "revenue": "-10.00", "cost": "5.00", "units_sold": "2"},    # Negative revenue
    {"date": "2026-04-10", "category": "Home", "revenue": "300.00", "cost": "150.00", "units_sold": "3"},
]

DATA_HR = [
    {"employee_id": "EMP101", "name": "Alice Smith", "department": "Engineering", "salary": "95000.00", "hire_date": "2026-01-10"},
    {"employee_id": "EMP101", "name": "Alice Smith", "department": "Engineering", "salary": "95000.00", "hire_date": "2026-01-10"}, # Duplicate
    {"employee_id": "EMP102", "name": "Bob Jones", "department": None, "salary": "82000.00", "hire_date": "2026-01-15"},          # Null Dept
    {"employee_id": "EMP103", "name": "Charlie", "department": "HR", "salary": "-5000.00", "hire_date": "2026-02-01"},             # Negative salary
    {"employee_id": "EMP104", "name": "Dana White", "department": "Sales", "salary": "60000.00", "hire_date": "2026-03-12"},
]

DATA_HEALTHCARE = [
    {"patient_id": "P001", "claim_id": "C9001", "claim_date": "2026-05-01", "diagnosis_code": "E11.9", "claim_amount": "250.00", "copay": "20.00"},
    {"patient_id": "P001", "claim_id": "C9001", "claim_date": "2026-05-01", "diagnosis_code": "E11.9", "claim_amount": "250.00", "copay": "20.00"}, # Duplicate
    {"patient_id": "P002", "claim_id": "C9002", "claim_date": "2026-05-02", "diagnosis_code": None, "claim_amount": "120.00", "copay": "15.00"},    # Null code
    {"patient_id": "P003", "claim_id": "C9003", "claim_date": "2026-05-03", "diagnosis_code": "J45.9", "claim_amount": "-80.00", "copay": "10.00"},   # Negative claim
    {"patient_id": "P004", "claim_id": "C9004", "claim_date": "2026-05-04", "diagnosis_code": "I10", "claim_amount": "400.00", "copay": "0.00"},
]

# 2. LLM Classifications Mock Responses
MOCK_CLASSIFICATION_ECOMMERCE = {
    "columns": [
        {"column_name": "date", "role": "date", "reason": "Transaction date calendar column"},
        {"column_name": "category", "role": "dimension", "reason": "Categorical product groups"},
        {"column_name": "revenue", "role": "measure", "reason": "Quantitative sales value"},
        {"column_name": "cost", "role": "measure", "reason": "Quantitative cost value"},
        {"column_name": "units_sold", "role": "measure", "reason": "Quantity metric"}
    ]
}

MOCK_CLASSIFICATION_HR = {
    "columns": [
        {"column_name": "employee_id", "role": "id", "reason": "Unique identifier of employee"},
        {"column_name": "name", "role": "text", "reason": "Employee name string"},
        {"column_name": "department", "role": "dimension", "reason": "Employee organizational segment"},
        {"column_name": "salary", "role": "measure", "reason": "Quantifiable compensation"},
        {"column_name": "hire_date", "role": "date", "reason": "Employment date calendar column"}
    ]
}

MOCK_CLASSIFICATION_HEALTHCARE = {
    "columns": [
        {"column_name": "patient_id", "role": "id", "reason": "Identifies the patient"},
        {"column_name": "claim_id", "role": "id", "reason": "Unique transaction key"},
        {"column_name": "claim_date", "role": "date", "reason": "Date of service entry"},
        {"column_name": "diagnosis_code", "role": "dimension", "reason": "ICD-10 clinical class"},
        {"column_name": "claim_amount", "role": "measure", "reason": "Billed financial aggregate"},
        {"column_name": "copay", "role": "measure", "reason": "Patient numeric share"}
    ]
}

# 3. Gold Aggregation Mock Responses
MOCK_GOLD_ECOMMERCE = {
    "options": [
        {
            "description": "Monthly revenue and units by product category",
            "sql": "SELECT strftime('%Y-%m', date) as month, category, SUM(revenue) as revenue, SUM(units_sold) as units_sold FROM silver_clean_sales GROUP BY month, category"
        }
    ]
}

MOCK_GOLD_HR = {
    "options": [
        {
            "description": "Monthly average salary by department",
            "sql": "SELECT strftime('%Y-%m', hire_date) as month, department, AVG(salary) as salary, COUNT(employee_id) as employee_count FROM silver_clean_sales GROUP BY month, department"
        }
    ]
}

MOCK_GOLD_HEALTHCARE = {
    "options": [
        {
            "description": "Monthly healthcare claims sum by clinical code",
            "sql": "SELECT strftime('%Y-%m', claim_date) as month, diagnosis_code, SUM(claim_amount) as claim_amount, AVG(copay) as copay FROM silver_clean_sales GROUP BY month, diagnosis_code"
        }
    ]
}

@pytest.fixture(autouse=True)
def setup_test_files():
    # Save CSV datasets
    pd.DataFrame(DATA_ECOMMERCE).to_csv(CSV_ECOMMERCE, index=False)
    pd.DataFrame(DATA_HR).to_csv(CSV_HR, index=False)
    pd.DataFrame(DATA_HEALTHCARE).to_csv(CSV_HEALTHCARE, index=False)
    yield
    # Cleanup CSV datasets
    for f in (CSV_ECOMMERCE, CSV_HR, CSV_HEALTHCARE):
        if f.exists():
            f.unlink()

@pytest.fixture
def test_db_path(tmp_path):
    # Returns a temporary database path for isolation
    return tmp_path / "generic_test.db"

@patch("src.schema_profiler.generate_llm_response")
def test_v1_generic_pipeline(mock_llm, test_db_path, monkeypatch):
    # Apply temporary SQLite path
    monkeypatch.setattr("src.db_adapter.DB_PATH", test_db_path)
    monkeypatch.setattr("src.etl_orchestrator.DB_PATH", test_db_path)
    
    # ------------------------------------------------------------
    # 1. RUN AND VERIFY E-COMMERCE DOMAIN
    # ------------------------------------------------------------
    # Setup Mock Returns for E-commerce profiling
    def side_effect_ecommerce(prompt, response_schema=None):
        if "propose 3 to 5 sensible business aggregation queries" in prompt:
            return json.dumps(MOCK_GOLD_ECOMMERCE)
        return json.dumps(MOCK_CLASSIFICATION_ECOMMERCE)
    
    mock_llm.side_effect = side_effect_ecommerce
    
    # Clean previous cached profile files if any
    profile_cache = test_db_path.parent / "schema_profile.json"
    if profile_cache.exists():
        profile_cache.unlink()
        
    # Monkeypatch the config BASE_DIR globally
    monkeypatch.setattr("src.config.BASE_DIR", test_db_path.parent)
    
    # Run pipeline
    pipeline = ETLPipeline()
    pipeline.db.db_path = test_db_path
    pipeline.schema_profiler.cache_path = profile_cache
    
    # run ingest (triggers schema profiling)
    pipeline.run_bronze_ingest(CSV_ECOMMERCE)
    pipeline.run_silver_transform()
    pipeline.run_gold_aggregation()
    dq = pipeline.run_data_quality_checks()
    
    # Validate e-commerce row outcomes
    assert dq["bronze_row_count"] == 5
    assert dq["silver_row_count"] == 2 # 1 duplicate, 1 null category, 1 negative revenue filtered
    assert dq["quarantine_row_count"] == 3
    
    # Check Gold aggregation structure
    conn = sqlite3.connect(str(test_db_path))
    df_gold = pd.read_sql_query("SELECT * FROM gold_monthly_metrics", conn)
    conn.close()
    assert "month" in df_gold.columns
    assert "category" in df_gold.columns
    assert "revenue" in df_gold.columns
    
    # ------------------------------------------------------------
    # 2. RUN AND VERIFY HR / PAYROLL DOMAIN
    # ------------------------------------------------------------
    if profile_cache.exists():
        profile_cache.unlink()
        
    # Setup Mock Returns for HR profiling
    def side_effect_hr(prompt, response_schema=None):
        if "propose 3 to 5 sensible business aggregation queries" in prompt:
            return json.dumps(MOCK_GOLD_HR)
        return json.dumps(MOCK_CLASSIFICATION_HR)
    
    mock_llm.side_effect = side_effect_hr
    
    # Initialize clean pipeline
    pipeline_hr = ETLPipeline()
    pipeline_hr.db.db_path = test_db_path
    pipeline_hr.schema_profiler.cache_path = profile_cache
    pipeline_hr.db.profile = None # Clear loaded profile
    
    pipeline_hr.run_bronze_ingest(CSV_HR)
    pipeline_hr.run_silver_transform()
    pipeline_hr.run_gold_aggregation()
    dq_hr = pipeline_hr.run_data_quality_checks()
    
    # Validate HR row outcomes
    assert dq_hr["bronze_row_count"] == 5
    assert dq_hr["silver_row_count"] == 2 # 1 duplicate, 1 null department, 1 negative salary filtered
    assert dq_hr["quarantine_row_count"] == 3
    
    # Check Gold aggregated schema
    conn = sqlite3.connect(str(test_db_path))
    df_gold_hr = pd.read_sql_query("SELECT * FROM gold_monthly_metrics", conn)
    conn.close()
    assert "month" in df_gold_hr.columns
    assert "department" in df_gold_hr.columns
    assert "salary" in df_gold_hr.columns
    
    # ------------------------------------------------------------
    # 3. RUN AND VERIFY HEALTHCARE CLAIMS DOMAIN
    # ------------------------------------------------------------
    if profile_cache.exists():
        profile_cache.unlink()
        
    # Setup Mock Returns for Healthcare profiling
    def side_effect_healthcare(prompt, response_schema=None):
        if "propose 3 to 5 sensible business aggregation queries" in prompt:
            return json.dumps(MOCK_GOLD_HEALTHCARE)
        return json.dumps(MOCK_CLASSIFICATION_HEALTHCARE)
    
    mock_llm.side_effect = side_effect_healthcare
    
    # Initialize clean pipeline
    pipeline_hc = ETLPipeline()
    pipeline_hc.db.db_path = test_db_path
    pipeline_hc.schema_profiler.cache_path = profile_cache
    pipeline_hc.db.profile = None # Clear loaded profile
    
    pipeline_hc.run_bronze_ingest(CSV_HEALTHCARE)
    pipeline_hc.run_silver_transform()
    pipeline_hc.run_gold_aggregation()
    dq_hc = pipeline_hc.run_data_quality_checks()
    
    # Validate healthcare claims row outcomes
    assert dq_hc["bronze_row_count"] == 5
    assert dq_hc["silver_row_count"] == 2 # 1 duplicate, 1 null diagnosis, 1 negative claim filtered
    assert dq_hc["quarantine_row_count"] == 3
    
    # Check Gold aggregates
    conn = sqlite3.connect(str(test_db_path))
    df_gold_hc = pd.read_sql_query("SELECT * FROM gold_monthly_metrics", conn)
    conn.close()
    assert "month" in df_gold_hc.columns
    assert "diagnosis_code" in df_gold_hc.columns
    assert "claim_amount" in df_gold_hc.columns
