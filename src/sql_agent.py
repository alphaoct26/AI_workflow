import duckdb
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

def get_database_schema(workspace_id: str = "default") -> str:
    """
    Connects to the database and extracts table schemas and sample rows 
    for Bronze, Silver, and Gold tables to provide schema context to the LLM.
    """
    from src.db_adapter import DatabaseAdapter
    db = DatabaseAdapter(workspace_id)
    
    conn = db.get_connection()
    cursor = conn.cursor()
    
    schema_details = []
    
    if db.dialect in ("postgres", "duckdb"):
        # Get list of public/main tables
        cursor.execute("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema IN ('public', 'main') 
              AND table_name NOT LIKE 'pg_%';
        """)
        tables = [row[0] for row in cursor.fetchall()]
        
        for table_name in tables:
            # Query column details for CREATE TABLE simulation
            cursor.execute(f"""
                SELECT column_name, data_type 
                FROM information_schema.columns 
                WHERE table_name = '{table_name}'
                ORDER BY ordinal_position;
            """)
            cols = cursor.fetchall()
            create_sql = f"CREATE TABLE {table_name} (\n    " + ",\n    ".join([f"{col[0]} {col[1].upper()}" for col in cols]) + "\n);"
            
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
    else:
        # Query sqlite_master for SQLite table definitions
        cursor.execute("""
            SELECT name, sql 
            FROM sqlite_master 
            WHERE type='table' AND name NOT LIKE 'sqlite_%';
        """)
        tables = cursor.fetchall()
        
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

def ask_llm_for_sql(question: str, schema_info: str, error_msg: str = None) -> str:
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
    
    from src.llm_gateway import generate_llm_response
    response_text = generate_llm_response(prompt, system_instruction=system_instruction)
    return clean_sql_query(response_text)

def is_safe_query(sql_query: str) -> tuple[bool, str]:
    """
    Checks if the SQL query is read-only (SELECT/WITH) and does not
    contain any modification keywords (DROP, DELETE, UPDATE, INSERT, ALTER, etc.).
    Returns (is_safe, error_message).
    """
    # Clean query: strip comments and whitespace
    clean_sql = re.sub(r'--.*$', '', sql_query, flags=re.MULTILINE)
    clean_sql = re.sub(r'/\*.*?\*/', '', clean_sql, flags=re.DOTALL)
    clean_sql = clean_sql.strip()
    
    # Must start with SELECT or WITH
    if not re.match(r'^(select|with)\b', clean_sql, re.IGNORECASE):
        return False, "Query must be a read-only SELECT or WITH statement."
        
    # Check for forbidden keywords as whole words
    forbidden_pattern = r'\b(drop|delete|update|insert|alter|create|replace|truncate|grant|revoke|pragma|attach|detach|write|exec)\b'
    matches = re.findall(forbidden_pattern, clean_sql, re.IGNORECASE)
    if matches:
        return False, f"Query contains forbidden write/modify keyword(s): {', '.join(set(matches))}"
        
    return True, ""

def execute_query(sql_query: str, workspace_id: str = "default"):
    """Executes SQL against the database and returns column names and rows, or raises an exception."""
    # 1. Check SQL safety
    is_safe, err_msg = is_safe_query(sql_query)
    if not is_safe:
        raise PermissionError(f"SQL Guard Blocked Query: {err_msg}")
        
    from src.db_adapter import DatabaseAdapter
    db = DatabaseAdapter(workspace_id)
    conn = db.get_connection()
    
    # 2. LLM Output Validation Layer: Compile/Verify execution plan before running the query
    try:
        explain_cursor = conn.cursor()
        explain_query = f"EXPLAIN {sql_query}" if db.dialect in ("postgres", "duckdb") else f"EXPLAIN QUERY PLAN {sql_query}"
        explain_cursor.execute(explain_query)
        explain_cursor.close()
    except Exception as explain_err:
        conn.close()
        raise Exception(f"SQL Plan Validation Failed (Syntax or Table/Column schema mismatch): {explain_err}")
        
    # 3. Execute query
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

def ask_llm_to_explain_results(question: str, sql_query: str, columns: list, rows: list) -> str:
    """Sends the raw SQL query, columns, and rows back to the LLM to explain in natural language."""
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
    
    from src.llm_gateway import generate_llm_response
    return generate_llm_response(prompt)

def process_agent_query(user_question: str, schema_info: str, workspace_id: str = "default") -> str:
    """Orchestrates Text-to-SQL generation, execution, self-correction, and synthesis."""
    error_msg = None
    sql_query = None
    
    # Try up to 3 times to correct SQL syntax if it errors
    for attempt in range(3):
        try:
            sql_query = ask_llm_for_sql(user_question, schema_info, error_msg)
            logger.info(f"Agent generated SQL (Attempt {attempt+1}):\n{sql_query}")
            
            # Execute
            columns, rows = execute_query(sql_query, workspace_id)
            logger.info(f"Query succeeded. Returned {len(rows)} rows.")
            
            # Synthesize final answer
            answer = ask_llm_to_explain_results(user_question, sql_query, columns, rows)
            return f"\n[SQL Executed]\n```sql\n{sql_query}\n```\n\n[AI Answer]\n{answer}"
            
        except Exception as db_err:
            error_msg = str(db_err)
            logger.warning(f"SQL execution failed on attempt {attempt+1} with error: {error_msg}")
            
    return f"Unable to generate valid SQL query after 3 attempts.\nLast error: {error_msg}\nLast SQL: {sql_query}"

def start_chat_loop(workspace_id: str = "default"):
    """Starts the interactive CLI session allowing the user to talk directly to the database."""
    import sys
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(line_buffering=True)
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(line_buffering=True)
        
    from src.llm_gateway import get_llm_providers
    providers = get_llm_providers()
    if not providers:
        print("\n[WARNING] No LLM provider credentials configured. Please edit llm_keys.txt or set environment variables.")
        return

    print("\n" + "="*60)
    print("      Welcome to the Interactive SQL Analytics Agent")
    print("      You can ask questions about Bronze, Silver, or Gold tables.")
    print("      Type 'exit', 'quit', or 'q' to end the session.")
    print("="*60)
    
    print("Scanning database schemas...")
    schema_info = get_database_schema(workspace_id)
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
            response = process_agent_query(user_input, schema_info, workspace_id)
            print(response)
            print("-"*60)
            
        except KeyboardInterrupt:
            print("\nEnding session. Goodbye!")
            break
        except Exception as e:
            print(f"\nAn error occurred in the agent loop: {e}")
            print("-"*60)
