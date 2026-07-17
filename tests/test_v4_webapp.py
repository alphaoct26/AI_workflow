import json
import pytest
from unittest.mock import patch
from app import app

@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client

def test_web_app_index_endpoint(client):
    """Verify that the dashboard index page loads successfully."""
    response = client.get("/")
    assert response.status_code == 200
    assert b"Auto-Analyst" in response.data

def test_web_app_workspaces_list(client):
    """Verify that the workspace list endpoint returns a JSON list."""
    response = client.get("/api/workspaces")
    assert response.status_code == 200
    data = json.loads(response.data)
    assert isinstance(data, list)
    assert len(data) >= 1

def test_web_app_workspace_details(client):
    """Verify that the workspace details KPI endpoint returns expected JSON structures."""
    response = client.get("/api/workspace/default")
    assert response.status_code == 200
    data = json.loads(response.data)
    assert "workspace_id" in data
    assert "dialect" in data
    assert "kpis" in data
    assert "tables" in data
    
    kpis = data["kpis"]
    assert "bronze_count" in kpis
    assert "silver_count" in kpis
    assert "quarantine_count" in kpis
    assert "total_revenue" in kpis

@patch("src.sql_agent.process_web_agent_query")
def test_web_app_chat_agent_endpoint(mock_web_agent, client):
    """Verify that the natural language chat endpoint processes questions and maps structured outputs."""
    # Setup mock structured response
    mock_web_agent.return_value = {
        "success": True,
        "sql": "SELECT * FROM silver_clean_sales LIMIT 5;",
        "columns": ["date", "category", "revenue"],
        "rows": [["2026-01-15", "Electronics", "1500.00"]],
        "answer": "Here are the top 5 sales records."
    }
    
    payload = {"question": "show me 5 sales records"}
    response = client.post("/api/workspace/default/chat", json=payload)
    
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data["success"] is True
    assert data["sql"] == "SELECT * FROM silver_clean_sales LIMIT 5;"
    assert data["columns"] == ["date", "category", "revenue"]
    assert data["rows"] == [["2026-01-15", "Electronics", "1500.00"]]
    assert data["answer"] == "Here are the top 5 sales records."
