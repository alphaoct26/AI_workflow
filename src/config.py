import os
from pathlib import Path
from dotenv import load_dotenv

# Base Workspace Directory
BASE_DIR = Path("d:/AI_workflow_project")

# Load environment variables
load_dotenv(BASE_DIR / ".env")

# Folders
LANDING_ZONE_DIR = BASE_DIR / "landing_zone"
DATA_DIR = BASE_DIR / "data"
POWERBI_DIR = BASE_DIR / "PowerBI_Report"

# Database Path
DB_PATH = DATA_DIR / "ecommerce.db"

# Data File Paths
RAW_CSV_PATH = DATA_DIR / "raw_sales.csv"
CLEAN_CSV_PATH = DATA_DIR / "raw_sales_clean.csv"
GOLD_CSV_PATH = DATA_DIR / "gold_monthly_metrics.csv"

# Output Assets
CHART_PATH = DATA_DIR / "monthly_revenue.png"
PPTX_PATH = DATA_DIR / "ecommerce_report.pptx"

# Make sure folders exist
for folder in [LANDING_ZONE_DIR, DATA_DIR, POWERBI_DIR]:
    folder.mkdir(parents=True, exist_ok=True)

# LLM Configuration
GEMINI_MODEL = "gemini-3.5-flash"

# Premium Theme Colors (Deep Slate, Indigo & Teal Accent)
THEME_COLORS = {
    "dark_bg": (30, 41, 59),       # #1E293B (Slate 800)
    "light_bg": (248, 250, 252),   # #F8FAFC (Slate 50)
    "primary": (79, 70, 229),      # #4F46E5 (Indigo 600)
    "secondary": (13, 148, 136),   # #0D9488 (Teal 600)
    "text_dark": (15, 23, 42),     # #0F172A (Slate 900)
    "text_muted": (71, 85, 105),   # #475569 (Slate 600)
    "card_bg": (255, 255, 255),    # White
    "accent_light": (238, 242, 255) # #EEF2FF (Indigo 50)
}

# Hex Color mappings for Matplotlib / HTML
THEME_HEX = {
    "dark_bg": "#1E293B",
    "light_bg": "#F8FAFC",
    "primary": "#4F46E5",
    "secondary": "#0D9488",
    "text_dark": "#0F172A",
    "text_muted": "#475569",
    "card_bg": "#FFFFFF",
    "accent_light": "#EEF2FF",
    "grid_color": "#E2E8F0"
}

# Standard fonts
FONT_TITLE = "Arial"
FONT_BODY = "Calibri"

def get_api_keys() -> list:
    """Loads Gemini API keys from environment variable and local gemini_keys.txt file."""
    keys = []
    # 1. Primary: environment variable
    env_key = os.environ.get("GEMINI_API_KEY")
    if env_key:
        keys.append(env_key)
        
    # 2. Secondary: gemini_keys.txt (one key per line)
    keys_file = BASE_DIR / "gemini_keys.txt"
    if keys_file.exists():
        try:
            with open(keys_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    # Skip empty lines and comments
                    if line and not line.startswith("#"):
                        # Strip accidental quotes
                        if (line.startswith('"') and line.endswith('"')) or (line.startswith("'") and line.endswith("'")):
                            line = line[1:-1].strip()
                        if line and line not in keys:
                            keys.append(line)
        except Exception as e:
            print(f"Warning: Could not read gemini_keys.txt: {e}", flush=True)
            
    return keys

def execute_with_retry(api_call_func):
    """
    Executes a Gemini API function, rotating through keys if transient errors 
    (503, 504, 429) or invalid authentication occurs. Retries once with backoff per key.
    """
    from google import genai
    from google.genai import types
    import time
    
    keys = get_api_keys()
    if not keys:
        raise ValueError("No Gemini API keys found. Set GEMINI_API_KEY env var or list them in gemini_keys.txt.")
        
    last_err = None
    for idx, key in enumerate(keys):
        for attempt in range(2): # Try up to 2 times per key
            try:
                client = genai.Client(api_key=key, http_options=types.HttpOptions(timeout=30000))
                return api_call_func(client)
            except Exception as e:
                last_err = e
                err_str = str(e)
                
                # Check if it is a transient connection, rate limit, or model busy error
                is_transient = any(code in err_str for code in ["503", "UNAVAILABLE", "504", "DEADLINE_EXCEEDED", "ResourceExhausted", "429"])
                if is_transient:
                    wait_time = 2 ** attempt
                    print(f"\n[API Warning] Key {idx+1}/{len(keys)} hit error ({err_str}). Retrying in {wait_time}s...", flush=True)
                    time.sleep(wait_time)
                else:
                    # Auth error or bad request: rotate key immediately
                    print(f"\n[API Warning] Key {idx+1}/{len(keys)} failed with critical error: {err_str}. Rotating...", flush=True)
                    break
                    
    # All keys exhausted
    raise last_err

