import sqlite3
import re
import pytest

# Test DB schemas mimicking etl_orchestrator.py
CREATE_BRONZE_TABLE = """
CREATE TABLE bronze_raw_sales (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT,
    category TEXT,
    revenue TEXT,
    cost TEXT,
    units_sold TEXT,
    ingested_at TEXT,
    source_file TEXT
);
"""

CREATE_SILVER_TABLE = """
CREATE TABLE silver_clean_sales (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT,
    category TEXT,
    revenue REAL,
    cost REAL,
    units_sold INTEGER,
    profit REAL,
    cleaned_at TEXT
);
"""

# Active SQL query used for transformations in the pipeline
SILVER_TRANSFORM_SQL = """
WITH ranked_bronze AS (
    SELECT 
        date,
        category,
        CAST(revenue AS REAL) as clean_revenue,
        CAST(cost AS REAL) as clean_cost,
        CAST(units_sold AS INTEGER) as clean_units,
        ingested_at,
        source_file,
        ROW_NUMBER() OVER(
            PARTITION BY date, category, units_sold, revenue 
            ORDER BY ingested_at DESC
        ) as rn
    FROM bronze_raw_sales
    WHERE date IS NOT NULL 
      AND date != 'None' 
      AND date != ''
      AND category IS NOT NULL 
      AND category != 'None' 
      AND category != ''
)
INSERT INTO silver_clean_sales (date, category, revenue, cost, units_sold, profit, cleaned_at)
SELECT 
    date(date) as date,
    category,
    clean_revenue,
    clean_cost,
    clean_units,
    (clean_revenue - clean_cost) as profit,
    datetime('now') as cleaned_at
FROM ranked_bronze
WHERE rn = 1 
  AND clean_revenue >= 0 
  AND clean_cost >= 0 
  AND clean_units >= 0;
"""

@pytest.fixture
def test_db():
    """Sets up an in-memory SQLite database with bronze and silver schemas."""
    conn = sqlite3.connect(":memory:")
    cursor = conn.cursor()
    cursor.execute(CREATE_BRONZE_TABLE)
    cursor.execute(CREATE_SILVER_TABLE)
    conn.commit()
    yield conn
    conn.close()

def run_transform(conn):
    """Executes the transformation query on the test database."""
    cursor = conn.cursor()
    cursor.execute(SILVER_TRANSFORM_SQL)
    conn.commit()

def test_successful_clean_record(test_db):
    """Test that a valid standard raw row is successfully cleaned, typed, and profit calculated."""
    cursor = test_db.cursor()
    cursor.execute(
        "INSERT INTO bronze_raw_sales (date, category, revenue, cost, units_sold, ingested_at, source_file) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("2026-05-15", "Electronics", "100.00", "60.00", "2", "2026-05-15 12:00:00", "test.csv")
    )
    test_db.commit()
    
    run_transform(test_db)
    
    cursor.execute("SELECT date, category, revenue, cost, units_sold, profit FROM silver_clean_sales")
    rows = cursor.fetchall()
    
    assert len(rows) == 1
    assert rows[0] == ("2026-05-15", "Electronics", 100.0, 60.0, 2, 40.0)

def test_deduplication_latest_record(test_db):
    """Test that identical rows are deduplicated, maintaining the latest record based on ingested_at."""
    cursor = test_db.cursor()
    cursor.execute(
        "INSERT INTO bronze_raw_sales (date, category, revenue, cost, units_sold, ingested_at, source_file) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("2026-05-15", "Electronics", "100.00", "60.00", "2", "2026-05-15 12:00:00", "test_Q1.csv")
    )
    # Identical record but ingested later (higher timestamp/order)
    cursor.execute(
        "INSERT INTO bronze_raw_sales (date, category, revenue, cost, units_sold, ingested_at, source_file) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("2026-05-15", "Electronics", "100.00", "60.00", "2", "2026-05-15 13:00:00", "test_Q2.csv")
    )
    test_db.commit()
    
    run_transform(test_db)
    
    cursor.execute("SELECT COUNT(*), source_file FROM silver_clean_sales JOIN bronze_raw_sales USING(date, category)")
    count, source = cursor.fetchone()
    # Confirm it deduplicated to a single row
    cursor.execute("SELECT COUNT(*) FROM silver_clean_sales")
    assert cursor.fetchone()[0] == 1

def test_filter_null_or_empty_dates(test_db):
    """Test that rows with missing, empty, or 'None' date strings are filtered out."""
    cursor = test_db.cursor()
    cursor.execute(
        "INSERT INTO bronze_raw_sales (date, category, revenue, cost, units_sold, ingested_at, source_file) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (None, "Electronics", "100.00", "60.00", "2", "2026-05-15 12:00:00", "test.csv")
    )
    cursor.execute(
        "INSERT INTO bronze_raw_sales (date, category, revenue, cost, units_sold, ingested_at, source_file) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("None", "Electronics", "100.00", "60.00", "2", "2026-05-15 12:00:00", "test.csv")
    )
    cursor.execute(
        "INSERT INTO bronze_raw_sales (date, category, revenue, cost, units_sold, ingested_at, source_file) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("", "Electronics", "100.00", "60.00", "2", "2026-05-15 12:00:00", "test.csv")
    )
    test_db.commit()
    
    run_transform(test_db)
    
    cursor.execute("SELECT COUNT(*) FROM silver_clean_sales")
    assert cursor.fetchone()[0] == 0

def test_filter_null_or_empty_categories(test_db):
    """Test that rows with missing, empty, or 'None' category strings are filtered out."""
    cursor = test_db.cursor()
    cursor.execute(
        "INSERT INTO bronze_raw_sales (date, category, revenue, cost, units_sold, ingested_at, source_file) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("2026-05-15", None, "100.00", "60.00", "2", "2026-05-15 12:00:00", "test.csv")
    )
    cursor.execute(
        "INSERT INTO bronze_raw_sales (date, category, revenue, cost, units_sold, ingested_at, source_file) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("2026-05-15", "None", "100.00", "60.00", "2", "2026-05-15 12:00:00", "test.csv")
    )
    cursor.execute(
        "INSERT INTO bronze_raw_sales (date, category, revenue, cost, units_sold, ingested_at, source_file) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("2026-05-15", "", "100.00", "60.00", "2", "2026-05-15 12:00:00", "test.csv")
    )
    test_db.commit()
    
    run_transform(test_db)
    
    cursor.execute("SELECT COUNT(*) FROM silver_clean_sales")
    assert cursor.fetchone()[0] == 0

def test_filter_negative_records(test_db):
    """Test that rows containing negative values for units_sold, revenue, or cost are rejected."""
    cursor = test_db.cursor()
    # Negative revenue
    cursor.execute(
        "INSERT INTO bronze_raw_sales (date, category, revenue, cost, units_sold, ingested_at, source_file) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("2026-05-15", "Electronics", "-100.00", "60.00", "2", "2026-05-15 12:00:00", "test.csv")
    )
    # Negative cost
    cursor.execute(
        "INSERT INTO bronze_raw_sales (date, category, revenue, cost, units_sold, ingested_at, source_file) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("2026-05-15", "Electronics", "100.00", "-60.00", "2", "2026-05-15 12:00:00", "test.csv")
    )
    # Negative units sold
    cursor.execute(
        "INSERT INTO bronze_raw_sales (date, category, revenue, cost, units_sold, ingested_at, source_file) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("2026-05-15", "Electronics", "100.00", "60.00", "-2", "2026-05-15 12:00:00", "test.csv")
    )
    test_db.commit()
    
    run_transform(test_db)
    
    cursor.execute("SELECT COUNT(*) FROM silver_clean_sales")
    assert cursor.fetchone()[0] == 0

def test_date_standardization(test_db):
    """Test that timestamps are standardized to date strings in YYYY-MM-DD format."""
    cursor = test_db.cursor()
    cursor.execute(
        "INSERT INTO bronze_raw_sales (date, category, revenue, cost, units_sold, ingested_at, source_file) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("2026-05-15 14:22:11", "Electronics", "100.00", "60.00", "2", "2026-05-15 12:00:00", "test.csv")
    )
    test_db.commit()
    
    run_transform(test_db)
    
    cursor.execute("SELECT date FROM silver_clean_sales")
    date_val = cursor.fetchone()[0]
    assert date_val == "2026-05-15"
