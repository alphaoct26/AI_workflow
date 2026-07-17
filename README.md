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

### 2. Secure API Credentials Setup (`.env`)
The pipeline uses `python-dotenv` to securely load API credentials. Create a file named `.env` at the root of the workspace directory (`d:\AI_workflow_project`) and populate it with your keys:

```env
# Google Gemini API Keys (Supports comma-separated fallback lists)
GEMINI_API_KEYS="your-gemini-key-1,your-gemini-key-2"

# Anthropic Claude API Key (Optional fallback)
# ANTHROPIC_API_KEY="your-claude-key"

# NVIDIA NIM Llama API Key (Optional fallback)
# NVIDIA_API_KEY="your-nvidia-key"

# OpenAI GPT API Key (Optional fallback)
# OPENAI_API_KEY="your-openai-key"
```

*(The `.env` file is already listed in `.gitignore` to prevent any credentials from being pushed to public source control repositories).*

---

## 🏃 Running the Pipeline (Docker Compose)

To build the environment, initialize the PostgreSQL database, execute all data processing layers, generate Power BI/PowerPoint reports, and start the SQL chat agent:

1. Ensure **Docker Desktop** is running.
2. Verify that your `.env` contains:
   - `DATABASE_URL="postgresql://postgres:postgres@db:5432/ecommerce"`
   - `HOST_WORKSPACE_PATH="d:\AI_workflow_project"` (pointing to your workspace on Windows)
3. Launch the services:
   ```bash
   docker-compose up --build
   ```

### What Happens When You Run `docker-compose up --build`:
1. **Mock Data Drop**: Generates mock e-commerce CSV batches (including anomalies/duplicates) in the `landing_zone/` folder.
2. **Bronze Ingest**: Ingests files into the PostgreSQL database.
3. **Silver ETL & Auto-Quarantine**: Cleanses, deduplicates, and separates rejected records into `quarantine_rejected_sales` for review.
4. **Gold Aggregations**: Builds business-tier metrics using advanced window functions.
5. **Data Quality Audits**: Validates record counts, null violations, quarantine statistics, and reconciles revenue.
6. **Matplotlib Visuals**: Saves a stylized bar chart of revenue performance to `data/monthly_revenue.png`.
7. **Power BI Project Creation**: Generates a `.pbip` folder structure with absolute data links customized for your machine.
8. **AI Business Analysis & Insights**: Extracts high-level findings and recommendations using the failover LLM gateway (Google Gemini, fallbacks to NVIDIA Llama 3.1 NIM or OpenAI GPT).
9. **PowerPoint Automation**: Creates a widescreen PowerPoint deck in `data/ecommerce_report.pptx`.
10. **Interactive Agent Loop**: Starts an interactive conversational SQL Agent CLI loop inside the terminal container.

---

## 🌐 Browser-Based Display Dashboard & AI Chat

We have built a premium, dark glassmorphic web dashboard that allows recruiters, users, and stakeholders to visualize ETL pipeline outcomes and query data using natural language directly from their browser.

![Web Dashboard Interface](data/dashboard_mockup.png)

### Features:
1. **Multi-Tenant Workspaces**: Switch between different active workspaces (e.g. `default`, `tesla-finance`) from the left sidebar to load separate databases.
2. **KPI Metrics Cards**: Track raw Bronze row counts, Silver cleaned sales, Quarantined rejections, total revenue, and average profit margins in real-time.
3. **Dynamic Visuals**: View the Matplotlib monthly revenue trend chart generated dynamically for the selected workspace.
4. **Interactive SQL Chat Agent Shell**: Ask questions in natural language, view the SQL generated by the Text-to-SQL compiler, and browse the resulting rows formatted in a clean table alongside friendly AI explanations.
5. **Data Preview**: Toggle tabs at the bottom to inspect raw/cleaned data records.
6. **Deck Downloads**: Download the programmatically generated presentation slides (`ecommerce_report.pptx`) with a single click.

### How to Run Locally:
1. Ensure your dependencies are installed (`pip install -r requirements.txt`).
2. Run the Flask server:
   ```bash
   python app.py
   ```
3. Open your browser and navigate to: **[http://127.0.0.1:5000](http://127.0.0.1:5000)**

### Host & Deploy Publicly (for Recruiters):
To launch the dashboard live so anyone (or a recruiter) can look at it instantly without running command lines:
1. **Fork** this repository.
2. Sign up on **[Render](https://render.com/)** or **[Railway](https://railway.app/)** (free hosting).
3. Create a new **Web Service** and connect your forked repository.
4. Set the build parameters:
   - **Environment**: Python
   - **Start Command**: `python app.py` (or install `gunicorn` and run `gunicorn app:app`)
5. Configure Environment Variables in settings:
   - `GEMINI_API_KEYS` / `NVIDIA_API_KEY` / `OPENAI_API_KEY` (to enable the SQL Chat Agent).
6. Click Deploy! Your dashboard will be live at a public `.onrender.com` URL.

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

---

## 🛡️ Production Security, SQL Guard & Plan Compiler Validation

To prevent malicious database actions (like SQL injection) via generated LLM queries, the SQL agent enforces a strict **SQL Guard & Validation** layer before execution:
- **Read-Only Enforcements**: The query is validated using regex and must begin strictly with `SELECT` or `WITH` (for CTEs).
- **Modification Guard**: The query is scanned for forbidden keywords: `DROP`, `DELETE`, `UPDATE`, `INSERT`, `ALTER`, `CREATE`, `REPLACE`, `TRUNCATE`, `GRANT`, `REVOKE`, `PRAGMA`, `ATTACH`, `DETACH`, `WRITE`, `EXEC` (case-insensitive).
- **LLM Output Validation Layer (Query Plan Compilation)**: Before executing the SQL, the script runs `EXPLAIN QUERY PLAN <sql_query>`. This validates the syntax and schema mapping against the active database without executing potentially expensive data-access operations. If SQLite fails to compile the query plan (e.g. referencing a non-existent column), the compiler error is raised, caught, and fed back to the AI for self-correction.
- **Self-Correction Loop**: If a safety violation or syntax plan error is caught, the pipeline raises an exception which triggers the AI's auto-correction loop, instructing it to rewrite a safe, syntactically valid query.

---

## 🧪 Automated Unit Testing (pytest)

The database transformation rules, auto-quarantine remediation path, and SQL Guard are fully verified by a test suite using `pytest`. The tests run against an isolated in-memory SQLite database.

### What is tested:
1. **Deduplication**: Validates that identical raw transactions are deduplicated, keeping the latest one based on ingestion timestamp.
2. **Standardization**: Checks that date strings are standardized to ISO `YYYY-MM-DD` date formats.
3. **Anomaly Filtering**: Verifies that rows with negative revenue, cost, or units are discarded.
4. **Data Integrity & Quarantine**: Checks that rows with missing, null, or empty categories/dates are filtered out, classified by rejection reason, and auto-quarantined.
5. **SQL Guard**: Validates read-only SELECT permissions and catches forbidden write queries (including chained write commands).
6. **Query Plan Compiler**: Tests that queries with invalid columns or syntax are successfully detected and blocked via the `EXPLAIN` compiler validation.

### Run the tests:
To execute the tests inside the Docker container, run:
```bash
docker-compose run app pytest -v
```
