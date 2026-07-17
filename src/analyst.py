import sqlite3
import pandas as pd
import os
import logging
from pydantic import BaseModel, Field
from typing import List
from google import genai
from google.genai import types
from google.genai.errors import APIError
from src.config import GEMINI_MODEL, DB_PATH

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("AI_Analyst")

class BusinessInsights(BaseModel):
    executive_summary: str = Field(
        description="A concise executive summary of the 6-month e-commerce sales performance. Max 3-4 sentences."
    )
    key_findings: List[str] = Field(
        description="A list of 3 to 5 clear, data-driven key findings (trends, anomalies, spikes, drops in profit margin, etc.)."
    )
    recommended_actions: List[str] = Field(
        description="A list of 3 to 5 concrete, actionable business recommendations directly tied to the findings."
    )

def extract_gold_data_as_text() -> str:
    """Queries the Gold summary table and formats it as a Markdown table for the LLM."""
    from src.db_adapter import DatabaseAdapter
    db = DatabaseAdapter()
    
    conn = db.get_connection()
    df = pd.read_sql_query("SELECT * FROM gold_monthly_metrics", conn)
    conn.close()
    
    if df.empty:
        return "No data available in gold aggregates."
        
    # Sort by the first column (typically the date/grouping column)
    df = df.sort_values(by=df.columns[0], ascending=True)
    
    # Format numbers dynamically based on column name hints
    df_formatted = df.copy()
    for col in df_formatted.columns:
        col_lower = col.lower()
        if any(kw in col_lower for kw in ("revenue", "cost", "salary", "amount", "price", "copay", "fee")):
            try:
                df_formatted[col] = df_formatted[col].apply(lambda x: f"${float(x):,.2f}" if pd.notnull(x) and str(x).strip() != '' else "")
            except Exception:
                pass
        elif any(kw in col_lower for kw in ("margin", "rate", "pct", "percent")):
            try:
                non_nulls = df_formatted[col].dropna()
                first_val = float(non_nulls.iloc[0]) if not non_nulls.empty else None
                # If values are decimals (e.g. 0.402), multiply by 100
                multiplier = 100 if first_val is not None and abs(first_val) <= 1.0 else 1
                df_formatted[col] = df_formatted[col].apply(lambda x: f"{float(x) * multiplier:.2f}%" if pd.notnull(x) and str(x).strip() != '' else "")
            except Exception:
                pass
        elif any(kw in col_lower for kw in ("units", "sold", "count", "qty", "quantity", "id")):
            try:
                df_formatted[col] = df_formatted[col].apply(lambda x: f"{int(float(x)):,}" if pd.notnull(x) and str(x).strip() != '' else "")
            except Exception:
                pass
                
    return df_formatted.to_markdown(index=False)

def run_ai_analysis() -> BusinessInsights:
    """
    Retrieves business insights by calling the unified multi-LLM gateway 
    and parsing the validated JSON response into the Pydantic model.
    """
    logger.info("Extracting Gold data and preparing prompt for LLM Gateway...")
    data_table = extract_gold_data_as_text()
    
    prompt = f"""
    You are a Senior Data Analyst and Strategic Business Advisor.
    Analyze the following 6-month e-commerce performance dataset (aggregated from the database's Gold table):
    
    ### 6-Month Gold Aggregated Sales Summary
    {data_table}
    
    Identify:
    1. Overall revenue trends, including month-over-month growth, dips, or plateaus.
    2. Specific cost/margin anomalies (e.g. months with unusually low margins or high costs).
    3. Product category performance (such as what drove the top performing months).
    4. 3-5 concrete, actionable strategic recommendations to optimize future revenue, control costs, and capture margin opportunities.
    
    Rules:
    - Base all conclusions STRICTLY on the data provided in the table. Do not make up external market trends.
    - Format your response exactly as a JSON object with these keys: "executive_summary", "key_findings" (list of strings), and "recommended_actions" (list of strings).
    """

    try:
        from src.llm_gateway import generate_llm_response
        response_text = generate_llm_response(
            prompt=prompt,
            response_schema=BusinessInsights
        )
        
        # Parse output into the Pydantic model
        insights = BusinessInsights.model_validate_json(response_text)
        logger.info("Successfully validated AI Business Insights.")
        return insights
    except Exception as e:
        logger.error(f"Failed to generate and parse AI Business Insights: {e}")
        raise e
