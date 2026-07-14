import sqlite3
import os
import re
import logging
import pandas as pd
from google import genai
from google.genai import types
from google.genai.errors import APIError
from src.config import GEMINI_MODEL, DB_PATH

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("SQL_Agent")

def get_database_schema() -> str:
    """
    Connects to the SQLite DB and extracts creation schemas and sample rows 
    for Bronze, Silver, and Gold tables to provide schema context to the LLM.
    """
    if not DB_PATH.exists():
        return "Database does not exist. Please run the ETL pipeline first."
        
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()
    
    # Query sqlite_master for table definitions
    cursor.execute("""
        SELECT name, sql 
        FROM sqlite_master 
        WHERE type='table' AND name NOT LIKE 'sqlite_%';
    """)
    tables = cursor.fetchall()
    
    schema_details = []
    for table_name, create_sql in tables:
        # Get sample rows
        try:
            cursor.execute(f"SELECT * FROM {table_name} LIMIT 3")
            columns = [col[0] for col in cursor.description]
            samples = cursor.fetchall()
            
            sample_str = f"Columns: {', '.join(columns)}\nSample Rows:\n"
            for row in samples:
                sample_str += f"  {dict(zip(columns, row))}\n"
        except Exception as e:
            sample_str = f"Error retrieving samples: {e}\n"
            
        schema_details.append(
            f"### Table: {table_name}\n"
            f"SQL Schema:\n```sql\n{create_sql}\n```\n"
            f"{sample_str}"
        )
        
    conn.close()
    return "\n\n".join(schema_details)

def clean_sql_query(raw_query: str) -> str:
    """Cleans up markdown code fences or backticks from generated SQL query."""
    # Find block of SQL if enclosed in ```sql ... ```
    match = re.search(r"```sql(.*?)```", raw_query, re.DOTALL | re.IGNORECASE)
    if match:
        query = match.group(1).strip()
    else:
        # Check for plain ``` ... ```
        match_plain = re.search(r"```(.*?)```", raw_query, re.DOTALL)
        if match_plain:
            query = match_plain.group(1).strip()
        else:
            query = raw_query.strip()
            
    # Remove any stray comments or trailing semicolons that sqlite3 might complain about
    query = query.replace("\\n", "\n").replace("\\t", "\t")
    return query

def ask_llm_for_sql(client, question: str, schema_info: str, error_msg: str = None) -> str:
    """Asks the LLM to generate an SQL query. Feeds back errors for auto-correction if provided."""
    system_instruction = (
        "You are an expert SQL Translator for SQLite. "
        "Your task is to convert the user's natural language question into a valid, executable SQLite SELECT query."
    )
    
    prompt = f"""
    Below is the schema of the SQLite database containing e-commerce sales:
    
    {schema_info}
    
    User Question: "{question}"
    
    Provide a single valid SQLite query to answer the user's question.
    """
    
    if error_msg:
        prompt += f"""
        
        [WARNING] The query you generated previously failed with the following database error:
        "{error_msg}"
        
        Please analyze the error, review the table schemas, correct your syntax, and output ONLY the corrected SQL query.
        """
        
    prompt += """
    
    Rules:
    - ONLY output the SQL code block. Do NOT write explanations.
    - Write only SELECT statements. Never write modifying statements (INSERT, UPDATE, DELETE).
    - Limit results to 50 rows maximum unless specified.
    - Do not use functions or syntax that SQLite doesn't support.
    """
    
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.0,  # Deterministic SQL generation
            system_instruction=system_instruction
        )
    )
    return clean_sql_query(response.text)

def execute_query(sql_query: str):
    """Executes SQL against SQLite and returns column names and rows, or raises an exception."""
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()
    try:
        cursor.execute(sql_query)
        columns = [col[0] for col in cursor.description]
        rows = cursor.fetchall()
        conn.close()
        return columns, rows
    except Exception as e:
        conn.close()
        raise e

def ask_llm_to_explain_results(client, question: str, sql_query: str, columns: list, rows: list) -> str:
    """Sends the raw SQL query, columns, and rows back to Gemini to explain in natural language."""
    formatted_results = "Empty Result Set"
    if rows:
        df = pd.DataFrame(rows, columns=columns)
        formatted_results = df.to_markdown(index=False)
        
    prompt = f"""
    You are a helpful Senior Business Analyst chatbot.
    The user asked: "{question}"
    
    To answer this, we executed the following SQLite query:
    ```sql
    {sql_query}
    ```
    
    And got these results:
    {formatted_results}
    
    Please explain these results clearly to the user in conversational, professional English. 
    State the exact figures and summarize what they mean for the business. Keep it concise.
    """
    
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(temperature=0.3)
    )
    return response.text

def process_agent_query(client, user_question: str, schema_info: str) -> str:
    """Orchestrates Text-to-SQL generation, execution, self-correction, and synthesis."""
    error_msg = None
    sql_query = None
    
    # Try up to 3 times to correct SQL syntax if it errors
    for attempt in range(3):
        try:
            sql_query = ask_llm_for_sql(client, user_question, schema_info, error_msg)
            logger.info(f"Agent generated SQL (Attempt {attempt+1}):\n{sql_query}")
            
            # Execute
            columns, rows = execute_query(sql_query)
            logger.info(f"Query succeeded. Returned {len(rows)} rows.")
            
            # Synthesize final answer
            answer = ask_llm_to_explain_results(client, user_question, sql_query, columns, rows)
            return f"\n[SQL Executed]\n```sql\n{sql_query}\n```\n\n[AI Answer]\n{answer}"
            
        except sqlite3.Error as db_err:
            error_msg = str(db_err)
            logger.warning(f"SQL execution failed on attempt {attempt+1} with error: {error_msg}")
        except Exception as e:
            logger.error(f"Unexpected query error on attempt {attempt+1}: {e}")
            return f"Error executing query: {e}"
            
    return f"Unable to generate valid SQL query after 3 attempts.\nLast error: {error_msg}\nLast SQL: {sql_query}"

def start_chat_loop():
    """Starts the interactive CLI session allowing the user to talk directly to the SQLite database."""
    import sys
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(line_buffering=True)
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(line_buffering=True)
        
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("\n[WARNING] GEMINI_API_KEY environment variable is not set.")
        print("Please set GEMINI_API_KEY to start chatting with your database.")
        return

    client = genai.Client(http_options=types.HttpOptions(timeout=30000))
    
    print("\n" + "="*60)
    print("      Welcome to the Interactive SQL Analytics Agent")
    print("      You can ask questions about Bronze, Silver, or Gold tables.")
    print("      Type 'exit', 'quit', or 'q' to end the session.")
    print("="*60)
    
    print("Scanning database schemas...")
    schema_info = get_database_schema()
    print("Schemas scanned. Agent is ready!")
    print("-"*60)
    
    while True:
        try:
            user_input = input("\nAsk about your data > ").strip()
            if not user_input:
                continue
                
            if user_input.lower() in ["exit", "quit", "q"]:
                print("Ending analytics agent session. Goodbye!")
                break
                
            print("Thinking...")
            response = process_agent_query(client, user_input, schema_info)
            print(response)
            print("-"*60)
            
        except KeyboardInterrupt:
            print("\nEnding session. Goodbye!")
            break
        except Exception as e:
            print(f"\nAn error occurred in the agent loop: {e}")
            print("-"*60)
