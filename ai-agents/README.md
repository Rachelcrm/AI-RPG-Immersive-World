# AI Monitoring Agents

This directory contains the implementation of an AI-powered monitoring system that uses LlamaIndex, Qdrant, and CrewAI to analyze metrics and provide insights.

## Components

- **DocumentStore**: A class that manages document storage and retrieval using LlamaIndex and Qdrant
- **Monitoring Tools**: Specialized CrewAI tools for different monitoring tasks
- **Agent System**: A system that creates and manages AI agents for monitoring tasks
- **API**: A FastAPI application that provides endpoints for analyzing metrics and querying the knowledge base

## Files

- `llamaindex_qdrant.py`: Implementation of the DocumentStore class
- `monitoring_tools.py`: Implementation of specialized CrewAI tools
- `agent_system.py`: Implementation of the MonitoringAgentSystem class
- `main.py`: FastAPI application entry point
- `test.py`: Test script for the MonitoringAgentSystem
- `ingest_knowledge.py`: Script for ingesting knowledge into the document store
- `analyze_metrics_example.py`: Example script for analyzing metrics

## Setup

1. Install the required dependencies:

```bash
pip install -r requirements.txt
```

2. Set up environment variables in a `.env` file:

```
OPENAI_API_KEY=your_openai_api_key
ANTHROPIC_API_KEY=your_anthropic_api_key (optional)
QDRANT_URL=http://localhost:6333 (or your Qdrant cloud URL)
QDRANT_API_KEY=your_qdrant_api_key (if using Qdrant cloud)
KNOWLEDGE_BASE_PATH=./knowledge
```

3. Start Qdrant (if using local instance):

```bash
docker run -p 6333:6333 -p 6334:6334 -v $(pwd)/qdrant_data:/qdrant/storage qdrant/qdrant
```

4. Ingest knowledge into the document store:

```bash
python ai-agents/ingest_knowledge.py --verbose
```

## Usage

### Running the API

```bash
uvicorn ai-agents.main:app --host 0.0.0.0 --port 8001 --reload
```

### API Endpoints

- `POST /analyze`: Analyze metrics and return insights
- `POST /query`: Query the knowledge base
- `POST /refresh-knowledge`: Force a refresh of the knowledge base
- `GET /health`: Check the health of the service

### Example: Analyzing Metrics

```bash
python ai-agents/analyze_metrics_example.py
```

### Example: Testing the System

```bash
python ai-agents/test.py
```

## Architecture

The system uses a multi-agent approach with specialized agents:

1. **Anomaly Detection Agent**: Identifies anomalies in metrics
2. **Root Cause Analysis Agent**: Determines the underlying causes of anomalies
3. **Remediation Advisor Agent**: Provides recommendations to address issues
4. **Communicator Agent**: Synthesizes findings into clear reports

These agents use specialized tools to interact with the knowledge base and perform their tasks.

## Knowledge Base

The knowledge base is stored in the `knowledge/` directory and is organized into categories:

- `best_practices/`: Best practices for system monitoring and troubleshooting
- `incidents/`: Past incident reports and resolutions
- `logs/`: Log analysis patterns and troubleshooting guides

See the `knowledge/README.md` file for more information on how to add and organize knowledge.

## Extending the System

### Adding New Tools

To add new tools, modify the `monitoring_tools.py` file:

1. Create a new schema class for the tool arguments
2. Create a new tool class that extends BaseTool
3. Add the tool to the `create_monitoring_tools` function

### Adding New Agents

To add new agents, modify the `agent_system.py` file:

1. Add a new agent creation in the `create_agents` method
2. Add new tasks in the `analyze_metrics` method if needed

### Customizing the Document Store

To customize the document store, modify the `llamaindex_qdrant.py` file:

1. Adjust the initialization parameters
2. Modify the document loading and indexing logic
3. Customize the query functionality
