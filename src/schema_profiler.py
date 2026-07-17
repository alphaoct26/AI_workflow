import os
import json
import logging
import pandas as pd
from pathlib import Path
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from src.llm_gateway import generate_llm_response

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("SchemaProfiler")

class ColumnRole(BaseModel):
    column_name: str = Field(description="The exact name of the column in the CSV.")
    role: str = Field(description="The semantic role classification: must be one of: 'date', 'id', 'measure', 'dimension', 'text', 'currency'")
    reason: str = Field(description="Short rationale for choosing this semantic role.")

class DatasetProfile(BaseModel):
    columns: List[ColumnRole] = Field(description="List of classified columns in the dataset.")

class GoldQueryOption(BaseModel):
    description: str = Field(description="What business metric or report this query aggregates (e.g. Monthly Revenue by Category).")
    sql: str = Field(description="The SQL SELECT query that extracts and groups columns from 'silver_clean_sales'. Format it for the target dialect. Do not include CREATE/INSERT, only the SELECT statement.")

class GoldQueryOptions(BaseModel):
    options: List[GoldQueryOption] = Field(description="List of 3 to 5 logical aggregation query options.")

class SchemaProfiler:
    """Profiles any CSV/DataFrame and identifies columns roles and candidate analytical queries."""
    
    def __init__(self, cache_path: Optional[Path] = None):
        if cache_path is None:
            from src.config import BASE_DIR
            self.cache_path = Path(BASE_DIR) / "data" / "schema_profile.json"
        else:
            self.cache_path = Path(cache_path)
            
    def profile_file(self, file_path: Path) -> Dict[str, Any]:
        """Analyzes a CSV file, generates semantic classifications via LLM, and caches the result."""
        logger.info(f"Profiling dataset: {file_path.name}")
        df = pd.read_csv(file_path)
        return self.profile_dataframe(df)

    def profile_dataframe(self, df: pd.DataFrame) -> Dict[str, Any]:
        """Analyzes a pandas DataFrame and generates classifications."""
        stats = {}
        for col in df.columns:
            non_null_series = df[col].dropna()
            cardinality = int(non_null_series.nunique())
            null_pct = float((len(df) - len(non_null_series)) / len(df))
            
            # Try to get min/max if numeric
            min_val = None
            max_val = None
            try:
                numeric_series = pd.to_numeric(non_null_series, errors='raise')
                min_val = float(numeric_series.min())
                max_val = float(numeric_series.max())
            except (ValueError, TypeError):
                pass
                
            # Get up to 5 unique sample values
            samples = [str(x) for x in non_null_series.unique()[:5]]
            
            stats[col] = {
                "dtype": str(df[col].dtype),
                "null_pct": f"{null_pct * 100:.2f}%",
                "cardinality": cardinality,
                "min_val": min_val,
                "max_val": max_val,
                "samples": samples
            }
            
        logger.info("Sending column metadata to LLM for role classification...")
        
        prompt = f"""
        You are a Senior Data Engineer. Classify the semantic role of each column in the dataset based on its profile statistics.
        Valid roles are:
        - 'date': calendar dates, time stamps, year-month identifiers.
        - 'id': primary keys, transaction reference IDs, customer IDs.
        - 'measure': numeric fields meant for quantitative aggregates (prices, costs, quantity sold, salaries, counts).
        - 'dimension': categorical variables used to group, filter, or slice data (category, gender, country, department, status).
        - 'text': verbose descriptive text, descriptions, unstructured notes.
        - 'currency': ISO currency codes or symbols if isolated.
        
        Dataset Statistics:
        {json.dumps(stats, indent=2)}
        
        Classify all columns. Make sure to choose roles logically.
        """
        
        response_text = generate_llm_response(prompt=prompt, response_schema=DatasetProfile)
        profile_data = DatasetProfile.model_validate_json(response_text)
        
        # Save cache
        profile_dict = profile_data.model_dump()
        
        # Merge stats with classifications for detailed caching
        columns_mapping = {}
        for col_role in profile_dict["columns"]:
            col_name = col_role["column_name"]
            columns_mapping[col_name] = {
                "role": col_role["role"],
                "reason": col_role["reason"],
                "stats": stats.get(col_name, {})
            }
            
        # Ensure parent directories exist
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.cache_path, "w") as f:
            json.dump(columns_mapping, f, indent=2)
            
        logger.info(f"Schema profile successfully cached to {self.cache_path}")
        return columns_mapping

    def get_cached_profile(self) -> Optional[Dict[str, Any]]:
        """Reads schema profile cache if it exists."""
        if self.cache_path.exists():
            try:
                with open(self.cache_path, "r") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Failed to read cached schema profile: {e}")
        return None

    def generate_gold_aggregation_options(self, profile: Dict[str, Any], dialect: str) -> List[Dict[str, Any]]:
        """Asks the LLM to suggest 3-5 aggregation queries grouping measure values by dates/dimensions."""
        logger.info(f"Generating candidate Gold aggregation queries for {dialect}...")
        
        # Format a minimal version of the profile for the LLM prompt
        columns_summary = []
        for name, details in profile.items():
            columns_summary.append({
                "column_name": name,
                "role": details["role"],
                "dtype": details["stats"].get("dtype")
            })
            
        prompt = f"""
        Given the following database schema profile for 'silver_clean_sales', propose 3 to 5 sensible business aggregation queries.
        
        Table name: silver_clean_sales
        Columns:
        {json.dumps(columns_summary, indent=2)}
        
        Target Database SQL Dialect: {dialect}
        
        Rules:
        - Each query must group by a parsed calendar date (e.g. extracted as month 'YYYY-MM') and 1 or 2 relevant 'dimension' columns.
        - Each query must aggregate at least one 'measure' (using SUM or AVG).
        - SQLite monthly date format: use `strftime('%Y-%m', date)`.
        - PostgreSQL monthly date format: use `TO_CHAR(date, 'YYYY-MM')`.
        - Do not output table creation or insertion logic. Output only raw, executable SELECT statements.
        """
        
        response_text = generate_llm_response(prompt=prompt, response_schema=GoldQueryOptions)
        options_data = GoldQueryOptions.model_validate_json(response_text)
        return options_data.model_dump()["options"]
