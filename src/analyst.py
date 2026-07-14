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
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Database not found at {DB_PATH}. Run the ETL pipeline first.")
        
    conn = sqlite3.connect(str(DB_PATH))
    df = pd.read_sql_query("SELECT * FROM gold_monthly_metrics ORDER BY month ASC", conn)
    conn.close()
    
    # Format numbers for better readability
    df_formatted = df.copy()
    df_formatted["revenue"] = df_formatted["revenue"].apply(lambda x: f"${x:,.2f}")
    df_formatted["cost"] = df_formatted["cost"].apply(lambda x: f"${x:,.2f}")
    df_formatted["profit_margin"] = df_formatted["profit_margin"].apply(lambda x: f"{x * 100:.2f}%")
    df_formatted["units_sold"] = df_formatted["units_sold"].apply(lambda x: f"{x:,}")
    
    return df_formatted.to_markdown(index=False)

def run_ai_analysis() -> BusinessInsights:
    """
    Connects to Gemini, sends the Gold-tier aggregate table, and returns 
    structured JSON business insights using strict Pydantic parsing.
    """
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        logger.error("GEMINI_API_KEY environment variable is not set!")
        raise ValueError("GEMINI_API_KEY environment variable is missing. Please set it to run the AI analysis.")

    logger.info("Extracting Gold data and preparing prompt for Gemini...")
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
    - Format your response exactly to fit the requested JSON schema.
    """

    logger.info(f"Sending prompt to Gemini using model '{GEMINI_MODEL}'...")
    try:
        # Initialize the official Google GenAI Client
        client = genai.Client(http_options=types.HttpOptions(timeout=30000))
        
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=BusinessInsights,
                temperature=0.1,  # Low temperature for highly analytical factual output
            ),
        )
        
        logger.info("Successfully received response from Gemini API.")
        
        # Parse output into the Pydantic model
        insights = BusinessInsights.model_validate_json(response.text)
        
        logger.info("Successfully parsed and validated Business Insights JSON.")
        return insights
        
    except APIError as e:
        logger.error(f"Gemini API Error occurred: {e}")
        raise e
    except Exception as e:
        logger.error(f"An unexpected error occurred during LLM invocation: {e}")
        raise e
