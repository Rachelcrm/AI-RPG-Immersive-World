# AI-Enhanced Web Service Monitoring System

A comprehensive monitoring system that combines traditional metrics-based monitoring with AI-powered analysis to provide deeper insights into system behavior and anomalies.

## Key Features

- Real-time analysis with OpenAI/Claude APIs
- LlamaIndex-powered knowledge integration with Qdrant vector store
- Native Prometheus compatibility
- Kafka-based streaming pipeline
- Framework-agnostic instrumentation
- Multi-agent system for specialized monitoring tasks

## Architecture

```
Web Apps → Prometheus → Kafka → CrewAI+LLM → Grafana + AlertManager
                                    ↑
                                    │
                                Qdrant + LlamaIndex
```

## Components

- **Prometheus Exporter**: Framework-agnostic metrics collection
- **Prometheus to Kafka Bridge**: Streams metrics to Kafka
- **AI Agent System**: Multi-agent system for analyzing metrics
- **Knowledge Base**: LlamaIndex with Qdrant for context-aware analysis
- **API Service**: Exposes endpoints for monitoring and analysis
- **Web App**: Example application with monitoring instrumentation

## Getting Started

### Prerequisites

- Docker and Docker Compose
- Python 3.12+
- OpenAI or Anthropic API key (for LLM integration)

### Installation

1. Clone the repository:

```bash
git clone 
cd ai-monitoring
```

2. Set up environment variables:

```bash
# Copy the example environment file
cp .env.example .env

# Edit .env with your API keys and configuration
# You'll need to set at minimum:
# - OPENAI_API_KEY or ANTHROPIC_API_KEY for LLM integration
# - Other configuration as needed for your environment
```

> **Note**: The `.env` file is excluded from version control via `.gitignore` to protect sensitive information like API keys. Never commit your actual `.env` file to the repository.

3. Start the services:

```bash
docker-compose up -d
```

### Running Guide

1. **Start Infrastructure Services Only**:

   ```bash
   docker-compose up -d
   ```

2. **Set Up Local Environment**:

   ```bash
   # Create a virtual environment
   python -m venv venv
   
   # Activate the virtual environment
   # On Windows:
   venv\Scripts\activate
   # On macOS/Linux:
   source venv/bin/activate
   
   # Install dependencies
   pip install -r requirements.txt
   ```

3. **Configure Environment Variables**:

   Create a `.env.local` file with the following content:

   ```
   # API Service
   API_HOST=0.0.0.0
   API_PORT=8000
   AI_AGENTS_URL=http://localhost:8001
   
   # AI Agent Service
   OPENAI_API_KEY=your_openai_api_key_here
   ANTHROPIC_API_KEY=your_anthropic_api_key_here
   KNOWLEDGE_BASE_PATH=./knowledge
   QDRANT_URL=http://localhost:6333
   QDRANT_COLLECTION=monitoring_knowledge
   
   # Prometheus to Kafka Bridge
   PROMETHEUS_URL=http://localhost:9090
   KAFKA_BROKERS=localhost:9092
   KAFKA_TOPIC=prom_metrics
   POLLING_INTERVAL=60
   ```

   Then load these environment variables:

   ```bash
   # On Windows (PowerShell):
   foreach($line in Get-Content .env.local) {
     if($line -match '^(.+)=(.+)$') {
       $name = $matches[1]
       $value = $matches[2]
       [Environment]::SetEnvironmentVariable($name, $value, "Process")
     }
   }
   
   # On macOS/Linux:
   export $(grep -v '^#' .env.local | xargs)
   ```

4. **Run the AI Agent Service Locally**:

   ```bash
   cd ai-agents
   uvicorn main:app --host 0.0.0.0 --port 8001 --reload
   ```

5. **Run the API Service Locally**:

   Open a new terminal, activate the virtual environment, and run:

   ```bash
   cd app
   uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
   ```

6. **Run the Prometheus to Kafka Bridge Locally**:

   Open a new terminal, activate the virtual environment, and run:

   ```bash
   cd app
   python -m prometheus_to_kafka --prometheus-url http://localhost:9090 --kafka-brokers localhost:9092
   ```

7. **Run the Example Web Application Locally**:

   Open a new terminal, activate the virtual environment, and run:

   ```bash
   cd app
   uvicorn web_app:app --host 0.0.0.0 --port 8002 --reload
   ```

8. **Debugging**:

   Since the code is running locally, you can use your IDE's debugging tools:

   - In VS Code, add breakpoints and use the Run and Debug panel
   - Use `pdb` for command-line debugging by adding `import pdb; pdb.set_trace()` in your code
   - Add print statements for quick debugging

9. **Hot Reloading**:

   The `--reload` flag with uvicorn enables hot reloading, so your changes will be applied automatically when you save files.

#### Running Individual Components

If you want to run specific components individually for development or testing:

1. **Run the API Service**:

   ```bash
   cd app
   uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
   ```

2. **Run the AI Agent Service**:

   ```bash
   cd ai-agents
   uvicorn main:app --host 0.0.0.0 --port 8001 --reload
   ```

3. **Run the Example Web Application**:

   ```bash
   cd app
   uvicorn web_app:app --host 0.0.0.0 --port 8002 --reload
   ```

4. **Run the Prometheus to Kafka Bridge**:

   ```bash
   cd app
   python -m prometheus_to_kafka --prometheus-url http://localhost:9090 --kafka-brokers localhost:9092
   ```

#### Verify Services and Configure Grafana

1. **Verify the services are running**:
   - Metrics exporter: http://localhost:8888/metrics (only starts when game starts)
   - Grafana UI: http://localhost:3000 (login with admin/admin)

2. **Configure Grafana**:
   - Login to Grafana at http://localhost:3000 (username: admin, password: admin)
   - Add Prometheus data source:
     - Go to Configuration > Connections > Add data source
     - Select Prometheus > Add new data source
     - Set URL to http://host.docker.internal:9090
     - Click "Save & Test"
   
3. **Import the dashboard**:
   - Go to Dashboards > New > Import
   - Click "Upload Dashboard JSON file"
   - Select grafana/dashboards/ai_monitoring.json
   - Click "Import"

#### Monitoring the System


1. **View Dashboards in Grafana**:
   
   Open http://localhost:3000 in your browser to access the Grafana UI.
   
   - Login with admin/admin
   - Navigate to "Dashboards" to view the AI Monitoring Dashboard
   - The dashboard shows request rates, latencies, error rates, and more

2. **Interact with the API**:
   
   The API is available at http://localhost:8000.
   
   - Use the `/metrics` endpoint to view Prometheus metrics
   - Use the `/analyze` endpoint to analyze metrics using AI
   - Use the `/query` endpoint to query the knowledge base
   - Use the `/refresh-knowledge` endpoint to refresh the knowledge base

3. **Test the Example Web Application**:
   
   The example web application is available at http://localhost:8002.
   
   - Access different endpoints to generate metrics
   - Try the `/error` endpoint to generate errors
   - Try the `/slow` endpoint to generate slow responses

#### Troubleshooting

1. **Check Logs**:
   
   ```bash
   # View logs for a specific service
   docker-compose logs api
   
   # Follow logs in real-time
   docker-compose logs -f ai-agents
   
   # View logs for all services
   docker-compose logs
   ```

2. **Check Container Status**:
   
   ```bash
   docker-compose ps
   ```

3. **Restart a Service**:
   
   ```bash
   docker-compose restart api
   ```

4. **Rebuild a Service**:
   
   ```bash
   docker-compose build api
   docker-compose up -d api
   ```

### Usage

#### Instrumenting Your Application

The system provides a framework-agnostic way to instrument your applications. Examples are provided for:

- Django
- Flask
- FastAPI

See the documentation in `examples/docs/` for detailed integration instructions.

#### Accessing Dashboards

- Grafana: http://localhost:3000 (admin/admin)


#### API Endpoints

- `/metrics`: Prometheus metrics endpoint
- `/analyze`: Analyze metrics using AI
- `/query`: Query the knowledge base
- `/refresh-knowledge`: Force a refresh of the knowledge base

