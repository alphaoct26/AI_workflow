import sqlite3
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import logging
from src.config import (
    DB_PATH, LANDING_ZONE_DIR, RAW_CSV_PATH, CLEAN_CSV_PATH, GOLD_CSV_PATH, THEME_HEX
)

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("ETL_Orchestrator")

class ETLPipeline:
    def __init__(self):
        self.db_path = str(DB_PATH)

    def generate_mock_csvs(self):
        """
        Generates 6 months of mock e-commerce transactions (Jan-Jun 2026).
        Intentionally injects duplicate rows and invalid values to test the Silver cleansing step.
        """
        logger.info("Generating mock e-commerce datasets...")
        np.random.seed(42)
        
        categories = ["Electronics", "Clothing", "Home & Kitchen", "Books", "Sports"]
        start_date = datetime(2026, 1, 1)
        end_date = datetime(2026, 6, 30)
        delta = end_date - start_date
        
        # Generate daily records
        data_records = []
        for i in range(delta.days + 1):
            current_date = start_date + timedelta(days=i)
            # 5-10 transactions per day
            num_transactions = np.random.randint(5, 12)
            
            # Add seasonality trend (sales jump 40% in June, and dip 15% in February)
            season_factor = 1.0
            if current_date.month == 6: # June Peak
                season_factor = 1.45
            elif current_date.month == 2: # Feb Dip
                season_factor = 0.85
                
            for _ in range(num_transactions):
                category = np.random.choice(categories)
                units_sold = int(np.random.randint(1, 15) * season_factor)
                
                # Prices vary by category
                base_price = {"Electronics": 250.0, "Clothing": 45.0, "Home & Kitchen": 85.0, "Books": 20.0, "Sports": 120.0}
                avg_price = base_price[category]
                
                revenue = round(units_sold * np.random.uniform(avg_price * 0.9, avg_price * 1.1), 2)
                # Cost is generally 50-70% of revenue
                cost_ratio = np.random.uniform(0.50, 0.70)
                # Specific anomaly: In February, cost ratios spike for Sports, lowering profit margins
                if current_date.month == 2 and category == "Sports":
                    cost_ratio = 0.95
                
                cost = round(revenue * cost_ratio, 2)
                
                data_records.append({
                    "date": current_date.strftime("%Y-%m-%d"),
                    "category": category,
                    "revenue": revenue,
                    "cost": cost,
                    "units_sold": units_sold
                })
        
        df = pd.DataFrame(data_records)
        
        # Ingest artificial dirty data
        # 1. Duplicates
        dup_indices = np.random.choice(df.index, size=15, replace=False)
        dups = df.iloc[dup_indices].copy()
        df = pd.concat([df, dups], ignore_index=True)
        
        # 2. Null categories
        null_cat_indices = np.random.choice(df.index, size=5, replace=False)
        df.loc[null_cat_indices, "category"] = None
        
        # 3. Invalid/negative revenues
        neg_rev_indices = np.random.choice(df.index, size=3, replace=False)
        df.loc[neg_rev_indices, "revenue"] = -50.0
        
        # Split into two batches to simulate dynamic pipeline drops
        # Batch 1: January to May
        batch_1_mask = pd.to_datetime(df["date"]) <= "2026-05-31"
        df_batch_1 = df[batch_1_mask]
        
        # Batch 2: June (latest month data)
        df_batch_2 = df[~batch_1_mask]
        
        # Save files to Landing Zone
        batch_1_file = LANDING_ZONE_DIR / "sales_Q1_Q2.csv"
        batch_2_file = LANDING_ZONE_DIR / "sales_june.csv"
        
        df_batch_1.to_csv(batch_1_file, index=False)
        df_batch_2.to_csv(batch_2_file, index=False)
        
        # Also copy all raw records to data/raw_sales.csv for raw tracking
        df.to_csv(RAW_CSV_PATH, index=False)
        
        logger.info(f"Mock data created. Batch 1: {len(df_batch_1)} rows, Batch 2: {len(df_batch_2)} rows.")
        return [batch_1_file, batch_2_file]

    def create_schema(self):
        """Creates tables for Bronze, Silver, and Gold layers in SQLite database."""
        logger.info("Initializing database schemas...")
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # 1. Bronze: Raw landing layer
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS bronze_raw_sales (
                date TEXT,
                category TEXT,
                revenue TEXT,
                cost TEXT,
                units_sold TEXT,
                ingested_at TIMESTAMP,
                source_file TEXT
            )
        """)
        
        # 2. Silver: Cleaned structured layer
        cursor.execute("""
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
        """)
        
        # 3. Gold: Analytical aggregated metrics
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS gold_monthly_metrics (
                month TEXT PRIMARY KEY,
                revenue REAL,
                cost REAL,
                profit_margin REAL,
                units_sold INTEGER,
                top_category TEXT
            )
        """)
        
        conn.commit()
        conn.close()
        logger.info("Database schemas initialized.")

    def run_bronze_ingest(self, file_path):
        """Loads a raw CSV file into the Bronze layer as-is."""
        filename = file_path.name
        logger.info(f"Bronze Ingestion: Loading raw file '{filename}'...")
        
        df = pd.read_csv(file_path)
        df["ingested_at"] = datetime.now().isoformat()
        df["source_file"] = filename
        
        conn = sqlite3.connect(self.db_path)
        # Convert all to string in Bronze to mimic raw ingestion
        df_str = df.astype(str)
        df_str.to_sql("bronze_raw_sales", conn, if_exists="append", index=False)
        conn.close()
        logger.info(f"Bronze Ingestion: Loaded {len(df)} rows from {filename}.")

    def run_silver_transform(self):
        """
        Executes SQL cleaning queries to transform Bronze -> Silver.
        Deduplicates rows, converts types, strips negative records, and validates category.
        """
        logger.info("Silver Transformation: Cleansing and sorting data...")
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Clear existing Silver table to prevent duplicates on rerun
        cursor.execute("DELETE FROM silver_clean_sales")
        
        # SQL-based ETL transformation utilizing a CTE to deduplicate and clean data
        # Handles date cleaning, filtering null categories, eliminating negative revenue,
        # casting datatypes, and picking the latest ingested duplicate.
        silver_insert_sql = """
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
        
        cursor.execute(silver_insert_sql)
        conn.commit()
        
        # Fetch status
        cursor.execute("SELECT COUNT(*) FROM silver_clean_sales")
        silver_count = cursor.fetchone()[0]
        conn.close()
        
        logger.info(f"Silver Transformation: Completed. Cleaned sales table contains {silver_count} records.")

    def run_gold_aggregation(self):
        """
        Transforms Silver -> Gold.
        Aggregates metrics to monthly level and calculates profit margins and top categories using complex SQL.
        """
        logger.info("Gold Aggregation: Synthesizing monthly business aggregates...")
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Clear existing Gold table
        cursor.execute("DELETE FROM gold_monthly_metrics")
        
        # Gold layer monthly aggregation using CTEs and Window Functions
        gold_aggregation_sql = """
            WITH monthly_category_revenue AS (
                SELECT 
                    strftime('%Y-%m', date) as month,
                    category,
                    SUM(revenue) as cat_revenue,
                    ROW_NUMBER() OVER(
                        PARTITION BY strftime('%Y-%m', date) 
                        ORDER BY SUM(revenue) DESC
                    ) as rn
                FROM silver_clean_sales
                GROUP BY 1, 2
            ),
            top_categories AS (
                SELECT month, category
                FROM monthly_category_revenue
                WHERE rn = 1
            ),
            monthly_aggregates AS (
                SELECT
                    strftime('%Y-%m', date) as month,
                    SUM(revenue) as total_revenue,
                    SUM(cost) as total_cost,
                    SUM(units_sold) as total_units
                FROM silver_clean_sales
                GROUP BY 1
            )
            INSERT INTO gold_monthly_metrics (month, revenue, cost, profit_margin, units_sold, top_category)
            SELECT 
                m.month,
                ROUND(m.total_revenue, 2),
                ROUND(m.total_cost, 2),
                ROUND((m.total_revenue - m.total_cost) / m.total_revenue, 4) as profit_margin,
                m.total_units,
                t.category as top_category
            FROM monthly_aggregates m
            JOIN top_categories t ON m.month = t.month
            ORDER BY m.month ASC;
        """
        
        cursor.execute(gold_aggregation_sql)
        conn.commit()
        
        # Log aggregated months
        cursor.execute("SELECT * FROM gold_monthly_metrics")
        rows = cursor.fetchall()
        for row in rows:
            logger.info(f"Gold Aggregation: Month: {row[0]} | Revenue: ${row[1]:,.2f} | Margin: {row[3]*100:.1f}% | Top Category: {row[5]}")
            
        conn.close()
        logger.info("Gold Aggregation: Completed.")

    def export_gold_to_csv(self):
        """Exports Clean Silver and Gold metrics to CSV for Power BI visualization compatibility."""
        logger.info("Exporting tables to CSV for Power BI compatibility...")
        conn = sqlite3.connect(self.db_path)
        
        # Export Silver clean
        df_silver = pd.read_sql_query("SELECT * FROM silver_clean_sales", conn)
        df_silver.to_csv(CLEAN_CSV_PATH, index=False)
        
        # Export Gold summary
        df_gold = pd.read_sql_query("SELECT * FROM gold_monthly_metrics", conn)
        df_gold.to_csv(GOLD_CSV_PATH, index=False)
        
        conn.close()
        logger.info("CSVs successfully exported to data/ folder.")

    def run_data_quality_checks(self):
        """
        Validates ETL pipeline data integrity.
        Performs audit logs comparing Row Counts, Null Violations, and Total Financial Reconciliation.
        """
        logger.info("Running Data Quality (DQ) Audits...")
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        audit_results = {}
        
        # Check 1: Record counts
        cursor.execute("SELECT COUNT(*) FROM bronze_raw_sales")
        bronze_rows = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM silver_clean_sales")
        silver_rows = cursor.fetchone()[0]
        audit_results["bronze_row_count"] = bronze_rows
        audit_results["silver_row_count"] = silver_rows
        
        # Check 2: Null values check in Silver (should be 0)
        cursor.execute("""
            SELECT COUNT(*) FROM silver_clean_sales 
            WHERE date IS NULL OR category IS NULL OR revenue IS NULL OR cost IS NULL OR units_sold IS NULL
        """)
        nulls_in_silver = cursor.fetchone()[0]
        audit_results["null_violations_in_silver"] = nulls_in_silver
        
        # Check 3: Reconciliation check (Total Revenue of Silver vs Gold monthly totals)
        cursor.execute("SELECT SUM(revenue) FROM silver_clean_sales")
        silver_revenue = round(cursor.fetchone()[0] or 0.0, 2)
        cursor.execute("SELECT SUM(revenue) FROM gold_monthly_metrics")
        gold_revenue = round(cursor.fetchone()[0] or 0.0, 2)
        
        audit_results["silver_total_revenue"] = silver_revenue
        audit_results["gold_total_revenue"] = gold_revenue
        audit_results["financial_discrepancy"] = round(abs(silver_revenue - gold_revenue), 2)
        
        # Output audit report
        logger.info("============= DATA QUALITY AUDIT REPORT =============")
        logger.info(f"Bronze Raw Records: {bronze_rows}")
        logger.info(f"Silver Cleaned Records: {silver_rows} (Discarded/Filtered: {bronze_rows - silver_rows})")
        logger.info(f"Null Violations in Silver: {nulls_in_silver} {'[PASSED]' if nulls_in_silver == 0 else '[FAILED]'}")
        logger.info(f"Silver Total Revenue: ${silver_revenue:,.2f}")
        logger.info(f"Gold Total Revenue: ${gold_revenue:,.2f}")
        logger.info(f"Financial Reconciliation Discrepancy: ${audit_results['financial_discrepancy']:,.2f} "
                    f"{'[PASSED]' if audit_results['financial_discrepancy'] == 0 else '[WARNING]'}")
        logger.info("=====================================================")
        
        conn.close()
        return audit_results
