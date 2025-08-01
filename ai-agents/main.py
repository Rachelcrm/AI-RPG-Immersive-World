"""
AI Agent Service Entry Point

This module provides a FastAPI application that serves as the entry point for the AI agent service.
It provides endpoints for analyzing metrics, querying the knowledge base, and refreshing the knowledge base.
"""

import os
import sys
from typing import Any, Dict, List, Optional
from pathlib import Path

import uvicorn
from fastapi import BackgroundTasks, FastAPI, HTTPException
from pydantic import BaseModel
from dotenv import load_dotenv


def fetch_env() -> Path | None:
    possible_paths = [
        Path('.env'),  # Current directory
        Path('/app/.env'),  # App directory
        Path(__file__).parent / '.env',  # Same directory as the script
        Path(__file__).resolve().parent.parent / '.env'
    ]
    env_found = False
    exist_env_path = None
    for env_path in possible_paths:
        if env_path.exists():
            # Load the .env file
            env_found = True
            exist_env_path = env_path
            break
    if not env_found:
        print(f"Error: .env file not found in any of the expected locations")
        sys.exit(1)
    return exist_env_path


# Load environment variables from .env file
load_dotenv(dotenv_path=fetch_env())

# Import the MonitoringAgentSystem
from agent_system import MonitoringAgentSystem

# Create FastAPI app
app = FastAPI(
    title="AI Monitoring Agent Service",
    description="Service for AI-enhanced monitoring and analysis",
    version="0.1.0"
)

# Environment variables
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
KNOWLEDGE_BASE_PATH = os.getenv("KNOWLEDGE_BASE_PATH", "./knowledge")
QDRANT_URL = os.getenv("QDRANT_URL", "http://qdrant:6333")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY")
COLLECTION_NAME = os.getenv("QDRANT_COLLECTION", "monitoring_knowledge")

# Initialize the agent system
agent_system = MonitoringAgentSystem(
    openai_api_key=OPENAI_API_KEY,
    anthropic_api_key=ANTHROPIC_API_KEY,
    knowledge_base_path=KNOWLEDGE_BASE_PATH,
    qdrant_url=QDRANT_URL,
    qdrant_api_key=QDRANT_API_KEY,
    collection_name=COLLECTION_NAME
)

# Define request/response models
class MetricData(BaseModel):
    name: str
    value: float
    labels: Dict[str, str] = {}
    timestamp: float

class AnalysisRequest(BaseModel):
    metrics: List[Dict[str, Any]]
    context: Optional[Dict[str, Any]] = None

class AnalysisResponse(BaseModel):
    report: str
    timestamp: str
    recommendations: List[str] = []
    severity: Optional[str] = None

class QueryRequest(BaseModel):
    query: str
    top_k: Optional[int] = 5

class QueryResponse(BaseModel):
    response: str
    source_documents: List[Dict[str, Any]] = []

# Define routes
@app.post("/analyze", response_model=AnalysisResponse)
async def analyze_metrics(request: AnalysisRequest):
    """
    Analyze metrics using the AI agent system.
    
    Args:
        request: Analysis request containing metrics and optional context
        
    Returns:
        AnalysisResponse: Analysis results
    """
    try:
        result = agent_system.analyze_metrics(request.metrics)
        
        # Extract recommendations and severity from the report if possible
        recommendations = []
        severity = None
        
        # This is a simple extraction, in a real system you might use more sophisticated parsing
        report_lines = result["report"].split("\n")
        for line in report_lines:
            if line.startswith("- ") and ("recommend" in line.lower() or "suggest" in line.lower()):
                recommendations.append(line[2:])
            elif "severity:" in line.lower():
                severity = line.split(":", 1)[1].strip()
        
        return {
            "report": result["report"],
            "timestamp": result["timestamp"],
            "recommendations": recommendations,
            "severity": severity
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Analysis error: {str(e)}")

@app.post("/query", response_model=QueryResponse)
async def query_knowledge_base(request: QueryRequest):
    """
    Query the knowledge base.
    
    Args:
        request: Query request containing the query text and optional parameters
        
    Returns:
        QueryResponse: Query results
    """
    try:
        response = agent_system.query(request.query, top_k=request.top_k)
        
        # Extract source documents if available
        source_documents = []
        if hasattr(response, "source_nodes"):
            for node in response.source_nodes:
                source_documents.append({
                    "text": node.node.text,
                    "score": node.score,
                    "metadata": node.node.metadata
                })
        
        return {
            "response": str(response),
            "source_documents": source_documents
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Query error: {str(e)}")

@app.post("/refresh-knowledge")
async def refresh_knowledge_base(background_tasks: BackgroundTasks):
    """
    Force a refresh of the knowledge base.
    
    Args:
        background_tasks: FastAPI background tasks
        
    Returns:
        Dict: Status message
    """
    # Run the refresh in the background to avoid blocking the response
    background_tasks.add_task(agent_system.force_knowledge_refresh)
    
    return {
        "status": "success",
        "message": "Knowledge base refresh started in the background"
    }

@app.get("/health")
async def health_check():
    """
    Health check endpoint.
    
    Returns:
        Dict: Health status
    """
    # Check if the knowledge base is available
    kb_status = "ok" if agent_system.document_store.index is not None else "error"
    
    # Check if the LLM API keys are set
    llm_status = "ok"
    if not OPENAI_API_KEY and not ANTHROPIC_API_KEY:
        llm_status = "error"
    
    # Overall status
    status = "healthy" if kb_status == "ok" and llm_status == "ok" else "degraded"
    
    return {
        "status": status,
        "knowledge_base": kb_status,
        "llm_api": llm_status
    }

if __name__ == "__main__":
    uvicorn.run("ai-agents.main:app", host="0.0.0.0", port=8001, reload=True)
