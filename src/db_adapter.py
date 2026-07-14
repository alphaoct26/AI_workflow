import os
import sqlite3
import logging
from pathlib import Path
from src.config import BASE_DIR, DB_PATH

logger = logging.getLogger("DB_Adapter")

class DatabaseAdapter:
    """
    Abstracts database connection and dialect-specific queries 
    supporting both SQLite (local/fallback) and PostgreSQL (production).
    """
    def __init__(self):
        # Read from environment
        self.database_url = os.environ.get("DATABASE_URL")
        self.dialect = "sqlite"
        self.db_path = DB_PATH
        
        if self.database_url and (self.database_url.startswith("postgresql://") or self.database_url.startswith("postgres://")):
            # Normalize database URL scheme for psycopg2 (replace postgres:// with postgresql://)
            if self.database_url.startswith("postgres://"):
                self.database_url = self.database_url.replace("postgres://", "postgresql://", 1)
            
            # Verify if PostgreSQL is reachable
            try:
                import psycopg2
                # Attempt to establish connection with a short timeout
                conn = psycopg2.connect(self.database_url, connect_timeout=3)
                conn.close()
                self.dialect = "postgres"
                logger.info("Database Adapter: Successfully connected to PostgreSQL.")
            except Exception as e:
                logger.warning(
                    f"\n{'!'*60}\n"
                    f" [WARNING] PostgreSQL connection failed: {e}\n"
                    f" Falling back to local SQLite database.\n"
                    f"{'!'*60}\n"
                )
                self.dialect = "sqlite"
                self.db_path = DB_PATH
        else:
            self.dialect = "sqlite"
            self.db_path = DB_PATH
            logger.info(f"Database Adapter: Operating with SQLite. Path: {self.db_path}")

    def get_connection(self):
        """Returns a native database connection based on the dialect."""
        if self.dialect == "postgres":
            import psycopg2
            return psycopg2.connect(self.database_url)
        else:
            return sqlite3.connect(str(self.db_path))

    def get_schema_queries(self) -> list[str]:
        """Returns dialect-specific DDL queries for initializing tables."""
        if self.dialect == "postgres":
            return [
                # Bronze Raw Layer
                """
                CREATE TABLE IF NOT EXISTS bronze_raw_sales (
                    id SERIAL PRIMARY KEY,
                    date TEXT,
                    category TEXT,
                    revenue TEXT,
                    cost TEXT,
                    units_sold TEXT,
                    ingested_at TIMESTAMP,
                    source_file TEXT
                );
                """,
                # Silver Cleaned Layer
                """
                CREATE TABLE IF NOT EXISTS silver_clean_sales (
                    id SERIAL PRIMARY KEY,
                    date DATE,
                    category TEXT,
                    revenue REAL,
                    cost REAL,
                    units_sold INTEGER,
                    profit REAL,
                    cleaned_at TIMESTAMP
                );
                """,
                # Quarantine Rejected Layer
                """
                CREATE TABLE IF NOT EXISTS quarantine_rejected_sales (
                    id SERIAL PRIMARY KEY,
                    raw_date TEXT,
                    raw_category TEXT,
                    raw_revenue TEXT,
                    raw_cost TEXT,
                    raw_units_sold TEXT,
                    source_file TEXT,
                    ingested_at TEXT,
                    rejection_reason TEXT,
                    quarantined_at TIMESTAMP
                );
                """,
                # Gold Analytical Layer
                """
                CREATE TABLE IF NOT EXISTS gold_monthly_metrics (
                    month TEXT PRIMARY KEY,
                    revenue REAL,
                    cost REAL,
                    profit_margin REAL,
                    units_sold INTEGER,
                    top_category TEXT
                );
                """
            ]
        else:
            return [
                # Bronze Raw Layer
                """
                CREATE TABLE IF NOT EXISTS bronze_raw_sales (
                    date TEXT,
                    category TEXT,
                    revenue TEXT,
                    cost TEXT,
                    units_sold TEXT,
                    ingested_at TIMESTAMP,
                    source_file TEXT
                );
                """,
                # Silver Cleaned Layer
                """
                CREATE TABLE IF NOT EXISTS silver_clean_sales (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date DATE,
                    category TEXT,
                    revenue REAL,
                    cost REAL,
                    units_sold INTEGER,
                    profit REAL,
                    cleaned_at TIMESTAMP
                )
                """,
                # Quarantine Rejected Layer
                """
                CREATE TABLE IF NOT EXISTS quarantine_rejected_sales (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    raw_date TEXT,
                    raw_category TEXT,
                    raw_revenue TEXT,
                    raw_cost TEXT,
                    raw_units_sold TEXT,
                    source_file TEXT,
                    ingested_at TEXT,
                    rejection_reason TEXT,
                    quarantined_at TIMESTAMP
                )
                """,
                # Gold Analytical Layer
                """
                CREATE TABLE IF NOT EXISTS gold_monthly_metrics (
                    month TEXT PRIMARY KEY,
                    revenue REAL,
                    cost REAL,
                    profit_margin REAL,
                    units_sold INTEGER,
                    top_category TEXT
                )
                """
            ]

    def get_quarantine_transform_query(self) -> str:
        """Returns dialect-specific query to extract rejections into the quarantine table."""
        # Use CURRENT_TIMESTAMP for timezone compatibility
        timestamp_func = "CURRENT_TIMESTAMP" if self.dialect == "postgres" else "datetime('now')"
        
        return f"""
            INSERT INTO quarantine_rejected_sales (
                raw_date, raw_category, raw_revenue, raw_cost, raw_units_sold, 
                source_file, ingested_at, rejection_reason, quarantined_at
            )
            -- Case 1: Missing Date
            SELECT date, category, revenue, cost, units_sold, source_file, ingested_at, 
                   'Missing/Invalid Date', {timestamp_func}
            FROM bronze_raw_sales
            WHERE date IS NULL OR date = 'None' OR date = ''
            UNION ALL
            -- Case 2: Missing Category
            SELECT date, category, revenue, cost, units_sold, source_file, ingested_at, 
                   'Missing/Invalid Category', {timestamp_func}
            FROM bronze_raw_sales
            WHERE (date IS NOT NULL AND date != 'None' AND date != '')
              AND (category IS NULL OR category = 'None' OR category = '')
            UNION ALL
            -- Case 3: Negative Financial Metrics
            SELECT date, category, revenue, cost, units_sold, source_file, ingested_at, 
                   'Negative Numeric Metric(s)', {timestamp_func}
            FROM bronze_raw_sales
            WHERE (date IS NOT NULL AND date != 'None' AND date != '')
              AND (category IS NOT NULL AND category != 'None' AND category != '')
              AND (CAST(revenue AS REAL) < 0 OR CAST(cost AS REAL) < 0 OR CAST(units_sold AS INTEGER) < 0)
            UNION ALL
            -- Case 4: Duplicate Transactions (rn > 1)
            SELECT date, category, revenue, cost, units_sold, source_file, ingested_at, 
                   'Duplicate Transaction', {timestamp_func}
            FROM (
                SELECT *,
                       ROW_NUMBER() OVER(
                           PARTITION BY date, category, units_sold, revenue 
                           ORDER BY ingested_at DESC
                       ) as rn
                FROM bronze_raw_sales
                WHERE date IS NOT NULL AND date != 'None' AND date != ''
                  AND category IS NOT NULL AND category != 'None' AND category != ''
            ) AS dups
            WHERE rn > 1 
              AND CAST(revenue AS REAL) >= 0 
              AND CAST(cost AS REAL) >= 0 
              AND CAST(units_sold AS INTEGER) >= 0;
        """

    def get_silver_transform_query(self) -> str:
        """Returns dialect-specific query to populate the silver_clean_sales layer."""
        timestamp_func = "CURRENT_TIMESTAMP" if self.dialect == "postgres" else "datetime('now')"
        
        # SQLite uses date(date); PostgreSQL uses CAST(date AS DATE)
        date_cast = "CAST(date AS DATE)" if self.dialect == "postgres" else "date(date)"
        
        return f"""
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
                {date_cast} as date,
                category,
                clean_revenue,
                clean_cost,
                clean_units,
                (clean_revenue - clean_cost) as profit,
                {timestamp_func} as cleaned_at
            FROM ranked_bronze
            WHERE rn = 1 
              AND clean_revenue >= 0 
              AND clean_cost >= 0 
              AND clean_units >= 0;
        """

    def get_gold_aggregation_query(self) -> str:
        """Returns dialect-specific query to populate the gold_monthly_metrics aggregates."""
        # SQLite uses strftime('%Y-%m', date); PostgreSQL uses TO_CHAR(date, 'YYYY-MM')
        month_func = "TO_CHAR(date, 'YYYY-MM')" if self.dialect == "postgres" else "strftime('%Y-%m', date)"
        
        return f"""
            WITH monthly_sales AS (
                SELECT 
                    {month_func} as month,
                    category,
                    SUM(revenue) as category_revenue,
                    SUM(units_sold) as category_units
                FROM silver_clean_sales
                GROUP BY month, category
            ),
            ranked_categories AS (
                SELECT 
                    month,
                    category,
                    ROW_NUMBER() OVER (PARTITION BY month ORDER BY category_revenue DESC) as rk
                FROM monthly_sales
            ),
            monthly_aggregates AS (
                SELECT 
                    {month_func} as month,
                    ROUND(SUM(revenue), 2) as revenue,
                    ROUND(SUM(cost), 2) as cost,
                    ROUND((SUM(revenue) - SUM(cost)) / SUM(revenue), 4) as profit_margin,
                    SUM(units_sold) as units_sold
                FROM silver_clean_sales
                GROUP BY month
            )
            INSERT INTO gold_monthly_metrics (month, revenue, cost, profit_margin, units_sold, top_category)
            SELECT 
                ma.month,
                ma.revenue,
                ma.cost,
                ma.profit_margin,
                ma.units_sold,
                rc.category as top_category
            FROM monthly_aggregates ma
            JOIN ranked_categories rc ON ma.month = rc.month AND rc.rk = 1
            ORDER BY ma.month ASC;
        """
