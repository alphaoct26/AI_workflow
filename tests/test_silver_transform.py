import sqlite3
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

CREATE_QUARANTINE_TABLE = """
CREATE TABLE quarantine_rejected_sales (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    raw_date TEXT,
    raw_category TEXT,
    raw_revenue TEXT,
    raw_cost TEXT,
    raw_units_sold TEXT,
    source_file TEXT,
    ingested_at TEXT,
    rejection_reason TEXT,
    quarantined_at TEXT
);
"""

# SQL queries for quarantine extraction
QUARANTINE_TRANSFORM_SQL = """
INSERT INTO quarantine_rejected_sales (
    raw_date, raw_category, raw_revenue, raw_cost, raw_units_sold, 
    source_file, ingested_at, rejection_reason, quarantined_at
)
-- Case 1: Missing Date
SELECT date, category, revenue, cost, units_sold, source_file, ingested_at, 
       'Missing/Invalid Date', datetime('now')
FROM bronze_raw_sales
WHERE date IS NULL OR date = 'None' OR date = ''
UNION ALL
-- Case 2: Missing Category
SELECT date, category, revenue, cost, units_sold, source_file, ingested_at, 
       'Missing/Invalid Category', datetime('now')
FROM bronze_raw_sales
WHERE (date IS NOT NULL AND date != 'None' AND date != '')
  AND (category IS NULL OR category = 'None' OR category = '')
UNION ALL
-- Case 3: Negative Financial Metrics
SELECT date, category, revenue, cost, units_sold, source_file, ingested_at, 
       'Negative Numeric Metric(s)', datetime('now')
FROM bronze_raw_sales
WHERE (date IS NOT NULL AND date != 'None' AND date != '')
  AND (category IS NOT NULL AND category != 'None' AND category != '')
  AND (CAST(revenue AS REAL) < 0 OR CAST(cost AS REAL) < 0 OR CAST(units_sold AS INTEGER) < 0)
UNION ALL
-- Case 4: Duplicate Transactions (rn > 1)
SELECT date, category, revenue, cost, units_sold, source_file, ingested_at, 
       'Duplicate Transaction', datetime('now')
FROM (
    SELECT *,
           ROW_NUMBER() OVER(
               PARTITION BY date, category, units_sold, revenue 
               ORDER BY ingested_at DESC
           ) as rn
    FROM bronze_raw_sales
    WHERE date IS NOT NULL AND date != 'None' AND date != ''
      AND category IS NOT NULL AND category != 'None' AND category != ''
)
WHERE rn > 1 
  AND CAST(revenue AS REAL) >= 0 
  AND CAST(cost AS REAL) >= 0 
  AND CAST(units_sold AS INTEGER) >= 0;
"""

# Active SQL query used for Silver ingestion
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
    """Sets up an in-memory SQLite database with bronze, silver, and quarantine schemas."""
    conn = sqlite3.connect(":memory:")
    cursor = conn.cursor()
    cursor.execute(CREATE_BRONZE_TABLE)
    cursor.execute(CREATE_SILVER_TABLE)
    cursor.execute(CREATE_QUARANTINE_TABLE)
    conn.commit()
    yield conn
    conn.close()

def run_transform(conn):
    """Executes the quarantine and transformation queries on the test database."""
    cursor = conn.cursor()
    cursor.execute(QUARANTINE_TRANSFORM_SQL)
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
    cursor.execute(
        "INSERT INTO bronze_raw_sales (date, category, revenue, cost, units_sold, ingested_at, source_file) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("2026-05-15", "Electronics", "-100.00", "60.00", "2", "2026-05-15 12:00:00", "test.csv")
    )
    cursor.execute(
        "INSERT INTO bronze_raw_sales (date, category, revenue, cost, units_sold, ingested_at, source_file) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("2026-05-15", "Electronics", "100.00", "-60.00", "2", "2026-05-15 12:00:00", "test.csv")
    )
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

def test_quarantine_rejections(test_db):
    """Test that rows failing validations are auto-quarantined with proper rejection reasons."""
    cursor = test_db.cursor()
    # 1. Missing Date
    cursor.execute(
        "INSERT INTO bronze_raw_sales (date, category, revenue, cost, units_sold, ingested_at, source_file) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (None, "Electronics", "100.00", "60.00", "2", "2026-05-15 12:00:00", "test.csv")
    )
    # 2. Missing Category
    cursor.execute(
        "INSERT INTO bronze_raw_sales (date, category, revenue, cost, units_sold, ingested_at, source_file) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("2026-05-15", "", "100.00", "60.00", "2", "2026-05-15 12:00:00", "test.csv")
    )
    # 3. Negative Numeric Metric
    cursor.execute(
        "INSERT INTO bronze_raw_sales (date, category, revenue, cost, units_sold, ingested_at, source_file) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("2026-05-15", "Electronics", "100.00", "-60.00", "2", "2026-05-15 12:00:00", "test.csv")
    )
    # 4. Duplicate rows (We add two identical rows)
    cursor.execute(
        "INSERT INTO bronze_raw_sales (date, category, revenue, cost, units_sold, ingested_at, source_file) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("2026-05-15", "Electronics", "200.00", "120.00", "4", "2026-05-15 12:00:00", "dup.csv")
    )
    cursor.execute(
        "INSERT INTO bronze_raw_sales (date, category, revenue, cost, units_sold, ingested_at, source_file) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("2026-05-15", "Electronics", "200.00", "120.00", "4", "2026-05-15 13:00:00", "dup.csv")
    )
    test_db.commit()
    
    run_transform(test_db)
    
    # Assertions on quarantine rejected rows
    cursor.execute("SELECT rejection_reason, COUNT(*) FROM quarantine_rejected_sales GROUP BY rejection_reason")
    rejections = dict(cursor.fetchall())
    
    assert rejections.get("Missing/Invalid Date") == 1
    assert rejections.get("Missing/Invalid Category") == 1
    assert rejections.get("Negative Numeric Metric(s)") == 1
    assert rejections.get("Duplicate Transaction") == 1
    
    # Verify that exactly 1 row made it to the silver clean table (the deduplicated clean row)
    cursor.execute("SELECT COUNT(*) FROM silver_clean_sales")
    assert cursor.fetchone()[0] == 1
