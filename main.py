import os
import sys
import logging
from src.config import DB_PATH, PPTX_PATH, POWERBI_DIR, LANDING_ZONE_DIR
from src.etl_orchestrator import ETLPipeline
from src.analyst import run_ai_analysis
from src.presenter import generate_matplotlib_chart, create_presentation_deck
from src.powerbi_generator import generate_powerbi_project
from src.sql_agent import start_chat_loop

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("Pipeline_Orchestrator")

def main():
    print("="*60)
    print("      Starting E-Commerce Auto-Analyst ETL Pipeline")
    print("="*60)
    
    # 1. Initialize Pipeline
    pipeline = ETLPipeline()
    
    # 2. Database schemas setup
    pipeline.create_schema()
    
    # 3. Generate mock CSV files representing 6 months of data
    landing_files = pipeline.generate_mock_csvs()
    
    # 4. Ingest raw CSV batches into Bronze layer
    for file_path in landing_files:
        pipeline.run_bronze_ingest(file_path)
        
    # 5. Execute cleaning and deduplication SQL (Silver layer)
    pipeline.run_silver_transform()
    
    # 6. Execute aggregation SQL (Gold layer)
    pipeline.run_gold_aggregation()
    
    # 7. Export clean data to CSV for Power BI compatibility
    pipeline.export_gold_to_csv()
    
    # 8. Run Data Quality Checks
    dq_results = pipeline.run_data_quality_checks()
    
    print("\n" + "-"*60)
    print("      Visuals & Report Automation Phase")
    print("-"*60)
    
    # 9. Generate Matplotlib Revenue Chart
    generate_matplotlib_chart()
    
    # 10. Generate Power BI Project Folder
    generate_powerbi_project()
    
    # 11. Check Gemini API key for AI Insights and PowerPoint generation
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("\n" + "!"*60)
        print(" [WARNING] GEMINI_API_KEY environment variable is not set!")
        print(" SQLite ETL, Matplotlib Chart, and Power BI project were successfully generated.")
        print(f" PowerPoint report generation is skipped due to missing API credentials.")
        print(" To enable the AI Analyst and presentation creation:")
        print("   Set the GEMINI_API_KEY environment variable and run this script again.")
        print("!"*60 + "\n")
        return
        
    # 12. Run Gemini AI Business Analysis
    print("Invoking Gemini for Business Analysis and Recommendations...")
    try:
        insights = run_ai_analysis()
        
        # 13. Create PowerPoint presentation from AI insights
        create_presentation_deck(insights)
        
        print("\n" + "="*60)
        print("      Pipeline execution complete!")
        print(f"      - Database: {DB_PATH}")
        print(f"      - PowerPoint Report: {PPTX_PATH}")
        print(f"      - Power BI Project: {POWERBI_DIR}/AutoAnalyst.pbip")
        print("="*60)
        
    except Exception as e:
        logger.error(f"AI Analytics pipeline failed: {e}")
        print("\n[ERROR] Pipeline completed data steps, but AI generation failed. See log above.")
        
    # 14. Launch the Interactive SQL Agent so the user can talk to the data
    start_chat_loop()

if __name__ == "__main__":
    main()
