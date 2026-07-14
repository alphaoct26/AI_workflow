import json
import logging
import os
from pathlib import Path
from src.config import POWERBI_DIR, CLEAN_CSV_PATH, GOLD_CSV_PATH, BASE_DIR

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("PowerBI_Generator")

def get_m_escaped_path(path: Path) -> str:
    """Format file path with double backslashes for Power Query M code compatibility on Windows."""
    # Check if host override path is configured (e.g. running inside Docker but Power BI on Windows)
    host_workspace = os.environ.get("HOST_WORKSPACE_PATH")
    if host_workspace:
        try:
            rel_path = path.resolve().relative_to(BASE_DIR.resolve())
            host_clean = host_workspace.replace("/", "\\").rstrip("\\")
            rel_clean = str(rel_path).replace("/", "\\")
            win_path = f"{host_clean}\\{rel_clean}"
            return win_path.replace("\\", "\\\\")
        except Exception as e:
            logger.warning(f"Failed to map relative path to HOST_WORKSPACE_PATH: {e}")
            
    abs_path = path.resolve().absolute()
    # Replace any forward slash (standard in Python Path) with standard Windows backslashes
    win_path = str(abs_path).replace("/", "\\")
    # Escape backslashes for Power Query M string representation
    return win_path.replace("\\", "\\\\")

def generate_powerbi_project():
    """Generates the Power BI Project (.pbip) folder structure and configuration files."""
    logger.info("PowerBI Generator: Creating .pbip folder structure...")
    
    # 1. Resolve folders
    report_dir = POWERBI_DIR / "AutoAnalyst.Report"
    model_dir = POWERBI_DIR / "AutoAnalyst.SemanticModel"
    
    report_dir.mkdir(parents=True, exist_ok=True)
    model_dir.mkdir(parents=True, exist_ok=True)
    
    # Escaped CSV paths
    clean_csv_m_path = get_m_escaped_path(CLEAN_CSV_PATH)
    gold_csv_m_path = get_m_escaped_path(GOLD_CSV_PATH)
    
    # 2. Generate launcher: AutoAnalyst.pbip
    pbip_content = {
        "version": "1.0",
        "settings": {
            "reportId": "87c47e8e-a2b1-4f9e-a612-c2cb101eeab5"
        },
        "report": {
            "path": "AutoAnalyst.Report"
        }
    }
    with open(POWERBI_DIR / "AutoAnalyst.pbip", "w", encoding="utf-8") as f:
        json.dump(pbip_content, f, indent=2)
        
    # 3. Generate Report links: definition.pbir
    pbir_content = {
        "version": "1.0",
        "datasetReference": {
            "byPath": {
                "path": "../AutoAnalyst.SemanticModel"
            }
        }
    }
    with open(report_dir / "definition.pbir", "w", encoding="utf-8") as f:
        json.dump(pbir_content, f, indent=2)
        
    # 4. Generate initial Report Layout (widescreen canvas setup)
    layout_content = {
        "version": "1.0",
        "theme": "Modern",
        "layoutOptimization": 0,
        "config": "{}",
        "publicDisplaySettings": "{}",
        "sections": [
            {
                "id": "Section1",
                "name": "ReportSection1",
                "displayName": "Executive Summary Dashboard",
                "filters": "[]",
                "config": "{}",
                "displayOption": 1,
                "width": 1280,
                "height": 720,
                "visualContainers": []
            }
        ]
    }
    with open(report_dir / "Layout", "w", encoding="utf-8") as f:
        json.dump(layout_content, f, indent=2)
        
    # 5. Generate Semantic Model links: definition.pbism
    pbism_content = {
        "version": "1.0",
        "settings": {
            "storageMode": "Import"
        }
    }
    with open(model_dir / "definition.pbism", "w", encoding="utf-8") as f:
        json.dump(pbism_content, f, indent=2)
        
    # 6. Generate semantic model schema: model.bim
    model_bim_content = {
        "name": "AutoAnalystModel",
        "compatibilityLevel": 1550,
        "model": {
            "culture": "en-US",
            "dataAccessOptions": {
                "legacyRedirects": True,
                "returnErrorValuesAsNull": True
            },
            "defaultPowerBIDataSourceVersion": "PowerBI_V3",
            "relationships": [],
            "tables": [
                {
                    "name": "CleanSales",
                    "description": "Standardized transactions from the Silver database layer.",
                    "columns": [
                        {"name": "id", "dataType": "int64", "sourceColumn": "id"},
                        {"name": "date", "dataType": "dateTime", "sourceColumn": "date", "formatString": "yyyy-mm-dd"},
                        {"name": "category", "dataType": "string", "sourceColumn": "category"},
                        {"name": "revenue", "dataType": "double", "sourceColumn": "revenue", "formatString": "\\$#,0.00"},
                        {"name": "cost", "dataType": "double", "sourceColumn": "cost", "formatString": "\\$#,0.00"},
                        {"name": "units_sold", "dataType": "int64", "sourceColumn": "units_sold", "formatString": "#,0"},
                        {"name": "profit", "dataType": "double", "sourceColumn": "profit", "formatString": "\\$#,0.00"}
                    ],
                    "partitions": [
                        {
                            "name": "CleanSalesPartition",
                            "source": {
                                "type": "m",
                                "expression": [
                                    "let",
                                    f"    Source = Csv.Document(File.Contents(\"{clean_csv_m_path}\"),[Delimiter=\",\", Columns=8, Encoding=1252, QuoteStyle=QuoteStyle.None]),",
                                    "    #\"Promoted Headers\" = Table.PromoteHeaders(Source, [PromoteAllScalars=true]),",
                                    "    #\"Changed Type\" = Table.TransformColumnTypes(#\"Promoted Headers\",{{\"id\", Int64.Type}, {\"date\", type date}, {\"category\", type text}, {\"revenue\", type number}, {\"cost\", type number}, {\"units_sold\", Int64.Type}, {\"profit\", type number}})",
                                    "in",
                                    "    #\"Changed Type\""
                                ]
                            }
                        }
                    ]
                },
                {
                    "name": "GoldSummary",
                    "description": "Monthly aggregates and business metrics from the Gold warehouse layer.",
                    "columns": [
                        {"name": "month", "dataType": "string", "sourceColumn": "month"},
                        {"name": "revenue", "dataType": "double", "sourceColumn": "revenue", "formatString": "\\$#,0.00"},
                        {"name": "cost", "dataType": "double", "sourceColumn": "cost", "formatString": "\\$#,0.00"},
                        {"name": "profit_margin", "dataType": "double", "sourceColumn": "profit_margin", "formatString": "0.00%"},
                        {"name": "units_sold", "dataType": "int64", "sourceColumn": "units_sold", "formatString": "#,0"},
                        {"name": "top_category", "dataType": "string", "sourceColumn": "top_category"}
                    ],
                    "partitions": [
                        {
                            "name": "GoldSummaryPartition",
                            "source": {
                                "type": "m",
                                "expression": [
                                    "let",
                                    f"    Source = Csv.Document(File.Contents(\"{gold_csv_m_path}\"),[Delimiter=\",\", Columns=6, Encoding=1252, QuoteStyle=QuoteStyle.None]),",
                                    "    #\"Promoted Headers\" = Table.PromoteHeaders(Source, [PromoteAllScalars=true]),",
                                    "    #\"Changed Type\" = Table.TransformColumnTypes(#\"Promoted Headers\",{{\"month\", type text}, {\"revenue\", type number}, {\"cost\", type number}, {\"profit_margin\", type number}, {\"units_sold\", Int64.Type}, {\"top_category\", type text}})",
                                    "in",
                                    "    #\"Changed Type\""
                                ]
                            }
                        }
                    ]
                }
            ]
        }
    }
    with open(model_dir / "model.bim", "w", encoding="utf-8") as f:
        json.dump(model_bim_content, f, indent=2)
        
    logger.info("PowerBI Generator: Power BI Project successfully created in PowerBI_Report/.")
