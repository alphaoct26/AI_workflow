import pytest
from src.sql_agent import is_safe_query

def test_safe_select_query():
    """Verify that normal SELECT and WITH queries pass the safety check."""
    safe, err = is_safe_query("SELECT date, category, revenue FROM silver_clean_sales;")
    assert safe is True
    assert err == ""
    
    safe_with, err_with = is_safe_query("""
        WITH sales_summary AS (
            SELECT date, revenue FROM silver_clean_sales
        )
        SELECT * FROM sales_summary;
    """)
    assert safe_with is True

def test_blocked_drop_query():
    """Verify that DROP TABLE statements are rejected because they do not start with SELECT or WITH."""
    safe, err = is_safe_query("DROP TABLE silver_clean_sales;")
    assert safe is False
    assert "select or with" in err.lower()

def test_blocked_delete_query():
    """Verify that DELETE statements are rejected because they do not start with SELECT or WITH."""
    safe, err = is_safe_query("DELETE FROM silver_clean_sales WHERE revenue < 0;")
    assert safe is False
    assert "select or with" in err.lower()

def test_blocked_update_query():
    """Verify that UPDATE statements are rejected because they do not start with SELECT or WITH."""
    safe, err = is_safe_query("UPDATE silver_clean_sales SET category = 'Other';")
    assert safe is False
    assert "select or with" in err.lower()

def test_blocked_insert_query():
    """Verify that INSERT statements are rejected because they do not start with SELECT or WITH."""
    safe, err = is_safe_query("INSERT INTO silver_clean_sales (date) VALUES ('2026-01-01');")
    assert safe is False
    assert "select or with" in err.lower()

def test_blocked_alter_query():
    """Verify that ALTER statements are rejected because they do not start with SELECT or WITH."""
    safe, err = is_safe_query("ALTER TABLE silver_clean_sales ADD COLUMN test INTEGER;")
    assert safe is False
    assert "select or with" in err.lower()

def test_non_select_start():
    """Verify that general non-read-only starting commands are rejected."""
    safe, err = is_safe_query("SHOW TABLES;")
    assert safe is False
    assert "select or with" in err.lower()

def test_blocked_chained_write_keyword():
    """Verify that queries starting with SELECT but containing chained forbidden keywords are caught by the keyword scanner."""
    safe, err = is_safe_query("SELECT * FROM silver_clean_sales; DROP TABLE silver_clean_sales;")
    assert safe is False
    assert "forbidden write/modify keyword" in err.lower()
    assert "drop" in err.lower()
    
    safe_nested, err_nested = is_safe_query("SELECT * FROM (DELETE FROM silver_clean_sales);")
    assert safe_nested is False
    assert "forbidden write/modify keyword" in err_nested.lower()
    assert "delete" in err_nested.lower()

def test_execute_query_schema_mismatch():
    """Verify that execute_query raises a sqlite3.Error when checking an invalid column or table schema via EXPLAIN."""
    import sqlite3
    from src.sql_agent import execute_query
    
    # Executing a query with an invalid column name should raise a sqlite3.Error via EXPLAIN validation
    with pytest.raises(sqlite3.Error) as exc_info:
        execute_query("SELECT non_existent_column_abc FROM silver_clean_sales LIMIT 1;")
    assert "SQL Plan Validation Failed" in str(exc_info.value)
    assert "no such column" in str(exc_info.value).lower()
