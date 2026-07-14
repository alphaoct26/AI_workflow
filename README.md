# E-Commerce Auto-Analyst ETL Pipeline & Interactive SQL Agent

This repository contains a modular, production-grade Data Engineering and Business Intelligence pipeline. It implements a complete **Medallion Architecture (Bronze -> Silver -> Gold)** using Python and SQLite, integrates **Gemini AI** for structured insights extraction, automatically compiles a styled **PowerPoint Presentation**, generates a local **Power BI Project (`.pbip`)** connected to the clean metrics, and drops the user into an **Interactive SQL Agent CLI Chat** to query the database using natural language.

---

## 🏗️ Architecture Overview

```
                        LANDING ZONE
                             │
                             ▼
                    (Batch 1 & Batch 2 CSVs)
                             │
            ┌────────────────┴────────────────┐
            │   BRONZE LAYER (Raw Staging)    │
            │   - Table: bronze_raw_sales     │
            └────────────────┬────────────────┘
                             │ (SQL Clean, Convert Types,
                             ▼  Deduplicate via ROW_NUMBER CTE)
            ┌─────────────────────────────────┐
            │   SILVER LAYER (Clean & Trust)  │
            │   - Table: silver_clean_sales   │
            └────────────────┬────────────────┘
                             │ (SQL Aggregation, Margin calc,
                             ▼  Top Category window functions)
            ┌─────────────────────────────────┐
            │    GOLD LAYER (Presentation)    │
            │   - Table: gold_monthly_metrics │
            └──────┬───────────────────┬──────┘
                   │                   │
                   ▼                   ▼
           [PRESENTATION LAYER]   [INTERACTIVE CHAT LAYER]
             - Matplotlib Chart     - Text-to-SQL AI Agent
             - PowerPoint Deck      - Natural Language Query
             - Power BI Project     - Error Self-Correction Loop
```

1. **Bronze Layer (`bronze_raw_sales`)**: Stores an exact raw copy of incoming transaction CSVs with metadata (`ingested_at`, `source_file`) for audit tracing.
2. **Silver Layer (`silver_clean_sales`)**: Removes duplicate keys, filters invalid values (e.g., negative revenues), cleans/standardizes string dates to actual dates, and formats float types.
3. **Gold Layer (`gold_monthly_metrics`)**: Summarizes total revenue, total cost, profit margins, and computes the top-selling category per month using window functions.
4. **Interactive Chat Layer**: An agentic AI loop that receives user questions, writes SQLite SQL queries, runs them against the database, catches execution errors, corrects them via a feedback loop, and synthesizes text answers.

---

## 🛠️ Tech Stack & Requirements

- **Language**: Python (v3.10+)
- **Database**: SQLite (Zero-Setup, serverless portability)
- **Data Engineering**: Pandas, SQL
- **AI Integration**: Google GenAI SDK (`google-genai`)
- **Reporting & Visuals**: `python-pptx`, `matplotlib`

---

## 🚀 Step-by-Step Environment Setup

### 1. Install Dependencies
Ensure you are in the workspace folder and install the required libraries:
```bash
pip install -r requirements.txt
```

### 2. Configure Gemini API Key
The pipeline uses the official Google GenAI library. Set your API Key in your terminal environment:

**In PowerShell (Windows):**
```powershell
$env:GEMINI_API_KEY="your-actual-api-key-here"
```

**In CMD (Windows):**
```cmd
set GEMINI_API_KEY=your-actual-api-key-here
```

**In Linux/macOS:**
```bash
export GEMINI_API_KEY="your-actual-api-key-here"
```

---

## 🏃 Running the Pipeline

To execute the data ingestion, ETL processing, AI analysis, PowerPoint/Power BI compilation, and the SQL Chat agent, run:
```bash
python main.py
```

### What Happens When You Run `main.py`:
1. **Mock Data Drop**: Generates mock e-commerce CSV batches (including anomalies/duplicates) in the `landing_zone/` folder.
2. **Bronze Ingest**: Ingests files into the SQLite database.
3. **Silver ETL & Clean**: Executes standard SQL scripts to clean and deduplicate data.
4. **Gold Aggregations**: Builds business-tier metrics using advanced window functions.
5. **Data Quality Audits**: Validates record counts, null violations, and reconciles revenue numbers across layers.
6. **Matplotlib Visuals**: Saves a stylized bar chart of revenue performance to `data/monthly_revenue.png`.
7. **Power BI Project Creation**: Generates a `.pbip` folder structure with absolute data links customized for your machine.
8. **Gemini Insights Generation**: Extracts high-level findings and recommendations from the Gold metrics.
9. **PowerPoint Automation**: Creates a gorgeous 3-slide slide deck in `data/ecommerce_report.pptx`.
10. **Interactive Agent Loop**: Starts a chat loop in your terminal (`Ask about your data > `) where you can ask any question.

---

## 💬 Talking to Your Data: Sample SQL Agent Queries

Once the pipeline completes, try typing these questions in the terminal:
- *“What was the total revenue by category?”*
- *“Compare January revenue with June revenue.”*
- *“Are there any months where profit margin was below 15%?”*
- *“Show me the raw transactions in June for the Electronics category limit 5.”*
- *“Which category has the highest average profit in the Silver layer?”*

The AI will output the SQL it generated, execute it, and provide a textual explanation of the numbers.

---

## 📊 Opening the Power BI Project (`.pbip`)

The programmatically created `PowerBI_Report/AutoAnalyst.pbip` launcher file is pre-configured to read from the generated CSV files directly from their absolute folder paths on your machine.

### Prerequisites to open `.pbip` in Power BI Desktop:
1. Ensure you have **Power BI Desktop** (Windows) installed.
2. Open Power BI Desktop, navigate to **File > Options and settings > Options > Preview features**, and check:
   - **Power BI Project (.pbip) save option**
   - **Store Semantic Model using TMDL format** (or legacy PBIR)
3. Double-click `PowerBI_Report/AutoAnalyst.pbip` to open the report.
4. Go to **Home > Refresh** to load/update data. The model loaded into your data panel will contain `CleanSales` and `GoldSummary` with all schemas, columns, and numeric formats pre-aligned!
