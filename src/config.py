import os
from pathlib import Path

# Base Workspace Directory
BASE_DIR = Path("d:/AI_workflow_project")

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
GEMINI_MODEL = "gemini-2.5-flash"

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
