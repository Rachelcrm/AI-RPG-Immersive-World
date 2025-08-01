import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field


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
app = FastAPI(title="AI Monitoring System API")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Environment variables
QDRANT_URL = os.getenv("QDRANT_URL", "http://qdrant:6333")
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "monitoring_knowledge")
AI_AGENTS_URL = os.getenv("AI_AGENTS_URL", "http://ai-agents:8001")

# Models
class MetricData(BaseModel):
    name: str
    value: float
    labels: Dict[str, str] = {}
    timestamp: float = Field(default_factory=lambda: datetime.now().timestamp())

class MetricBatch(BaseModel):
    metrics: List[MetricData]

class AnomalyRequest(BaseModel):
    metrics: List[Dict[str, Any]]
    context: Optional[Dict[str, Any]] = None

class AnomalyResponse(BaseModel):
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

# Routes
@app.post("/metrics", status_code=201)
async def ingest_metrics(
    metrics: MetricBatch,
    background_tasks: BackgroundTasks,
):
    """Ingest metrics from Prometheus"""
    # Store metrics in memory for immediate processing
    # In a real implementation, you might want to push these to Kafka
    
    # Check for potential anomalies in background
    background_tasks.add_task(check_for_anomalies, metrics.metrics)
    
    return {"status": "success", "message": f"Ingested {len(metrics.metrics)} metrics"}

async def check_for_anomalies(metrics: List[MetricData]):
    """Background task to check for anomalies"""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{AI_AGENTS_URL}/analyze",
                json={"metrics": [metric.dict() for metric in metrics]}
            )
            if response.status_code == 200:
                # In a real implementation, you might want to trigger alerts
                # or store the analysis results
                print(f"Anomaly analysis complete: {response.json()}")
    except Exception as e:
        print(f"Error checking for anomalies: {str(e)}")

@app.post("/analyze", response_model=AnomalyResponse)
async def analyze_metrics(request: AnomalyRequest):
    """Analyze metrics for anomalies"""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{AI_AGENTS_URL}/analyze",
                json=request.dict(),
                timeout=60  # LLM calls might take time
            )
            if response.status_code != 200:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Error from AI agents: {response.text}"
                )
            return response.json()
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Analysis timed out")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Analysis error: {str(e)}")

@app.post("/query", response_model=QueryResponse)
async def query_knowledge_base(
    request: QueryRequest,
):
    """Query the knowledge base"""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{AI_AGENTS_URL}/query",
                json=request.dict(),
                timeout=30
            )
            if response.status_code != 200:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Error from AI agents: {response.text}"
                )
            return response.json()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Query error: {str(e)}")

@app.post("/refresh-knowledge")
async def refresh_knowledge_base():
    """Force a refresh of the knowledge base"""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(f"{AI_AGENTS_URL}/refresh-knowledge")
            if response.status_code != 200:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Error refreshing knowledge base: {response.text}"
                )
            return {"status": "success", "message": "Knowledge base refreshed"}
    except Exception as e:
        raise HTTPException(
            status_code=500, 
            detail=f"Error refreshing knowledge base: {str(e)}"
        )

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    try:
        # Check AI agents status
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{AI_AGENTS_URL}/health",
                timeout=5
            )
            if response.status_code != 200:
                return {
                    "status": "degraded",
                    "qdrant": "ok",
                    "ai_agents": "error"
                }
        
        return {
            "status": "healthy",
            "qdrant": "ok",
            "ai_agents": "ok"
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e)
        }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
