# Practical Exercises

This document contains hands-on exercises for each session of the Multi-Agent AI Monitoring course. These exercises are designed to reinforce the concepts covered in the lectures and provide practical experience with the technologies used in the system.

## Session 1: Building Your First AI Agent

### Exercise 1.1: Setting Up the Environment

1. Create a new Python virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

2. Install the required dependencies:
   ```bash
   pip install crewai llama-index qdrant-client openai anthropic fastapi uvicorn prometheus-client kafka-python
   ```

3. Create a project directory structure:
   ```bash
   mkdir -p my-monitoring-system/{agents,knowledge/{best_practices,incidents}}
   cd my-monitoring-system
   ```

### Exercise 1.2: Creating a Basic Monitoring Agent

1. Create a file `agents/basic_agent.py` with the following content:

```python
from crewai import Agent, Task, Crew, Process
import os

# Set your API key (replace with your actual key)
os.environ["OPENAI_API_KEY"] = "your-openai-api-key"
# or
# os.environ["ANTHROPIC_API_KEY"] = "your-anthropic-api-key"

# Create a basic monitoring agent
monitoring_agent = Agent(
    role="System Monitor",
    goal="Monitor system metrics and detect anomalies",
    backstory="You're an expert at analyzing system metrics and detecting unusual patterns that indicate potential issues.",
    verbose=True
)

# Define a sample metrics dataset
sample_metrics = """
{
  "cpu_usage": 85.2,
  "memory_usage": 72.5,
  "disk_usage": 68.9,
  "network_in": 1250.45,
  "network_out": 3420.1,
  "response_time_p95": 450.2,
  "error_rate": 2.5,
  "request_count": 1250
}
"""

# Create a task for the agent
analysis_task = Task(
    description=f"Analyze the following metrics and identify any anomalies or concerning patterns:\n\n{sample_metrics}",
    agent=monitoring_agent,
    expected_output="A detailed analysis of the metrics, highlighting any anomalies and their potential impact."
)

# Create a crew with just one agent
crew = Crew(
    agents=[monitoring_agent],
    tasks=[analysis_task],
    verbose=2,
    process=Process.sequential
)

# Run the crew
result = crew.kickoff()

print("\n=== ANALYSIS RESULT ===\n")
print(result)
```

2. Run the script:
   ```bash
   python agents/basic_agent.py
   ```

3. Observe the agent's analysis of the sample metrics.

### Exercise 1.3: Extending the Agent with Custom Logic

1. Modify the `agents/basic_agent.py` file to include threshold-based anomaly detection:

```python
# Add this function to your script
def detect_anomalies(metrics_str):
    """Simple threshold-based anomaly detection"""
    import json
    
    # Define thresholds
    thresholds = {
        "cpu_usage": 80.0,
        "memory_usage": 80.0,
        "disk_usage": 85.0,
        "response_time_p95": 300.0,
        "error_rate": 1.0
    }
    
    # Parse metrics
    metrics = json.loads(metrics_str)
    
    # Check for anomalies
    anomalies = []
    for metric, value in metrics.items():
        if metric in thresholds and value > thresholds[metric]:
            anomalies.append(f"{metric} is {value}, which exceeds the threshold of {thresholds[metric]}")
    
    return anomalies

# Update the sample metrics to include the function result
anomalies = detect_anomalies(sample_metrics.strip())
anomalies_str = "\n".join(anomalies) if anomalies else "No anomalies detected based on simple thresholds."

# Modify the task description to include the anomalies
analysis_task = Task(
    description=f"Analyze the following metrics and elaborate on the detected anomalies:\n\n{sample_metrics}\n\nPre-detected anomalies:\n{anomalies_str}\n\nProvide deeper insights into these anomalies and suggest potential causes and remediation steps.",
    agent=monitoring_agent,
    expected_output="A detailed analysis of the anomalies, their potential causes, and recommended remediation steps."
)
```

2. Run the modified script and observe how the agent uses the pre-detected anomalies to provide deeper insights.

## Session 2: Building the Monitoring Pipeline

### Exercise 2.1: Creating a Prometheus Exporter

1. Create a file `prometheus_exporter.py` with the following content:

```python
import time
import threading
import random
from prometheus_client import Counter, Histogram, Gauge, start_http_server

# Create metrics
REQUEST_COUNT = Counter('app_request_count', 'Total request count', ['method', 'endpoint', 'status'])
REQUEST_LATENCY = Histogram('app_request_latency_seconds', 'Request latency in seconds', ['method', 'endpoint'])
ACTIVE_REQUESTS = Gauge('app_active_requests', 'Number of active requests', ['method'])
ERROR_RATE = Gauge('app_error_rate', 'Error rate percentage')

# Simulate request metrics
def simulate_requests():
    endpoints = ['/api/users', '/api/products', '/api/orders', '/api/dashboard']
    methods = ['GET', 'POST', 'PUT', 'DELETE']
    statuses = ['200', '201', '400', '404', '500']
    
    while True:
        # Simulate a request
        endpoint = random.choice(endpoints)
        method = random.choice(methods)
        status = random.choice(statuses)
        latency = random.uniform(0.01, 2.0)
        
        # Increment active requests
        ACTIVE_REQUESTS.labels(method=method).inc()
        
        # Record request
        REQUEST_COUNT.labels(method=method, endpoint=endpoint, status=status).inc()
        REQUEST_LATENCY.labels(method=method, endpoint=endpoint).observe(latency)
        
        # Simulate error rate (0-5%)
        error_rate = random.uniform(0, 5)
        ERROR_RATE.set(error_rate)
        
        # Decrement active requests
        time.sleep(0.1)  # Simulate processing time
        ACTIVE_REQUESTS.labels(method=method).dec()
        
        # Wait before next request
        time.sleep(random.uniform(0.1, 0.5))

if __name__ == '__main__':
    # Start HTTP server to expose metrics
    start_http_server(8000)
    print("Metrics server started at http://localhost:8000")
    
    # Start simulating requests in a separate thread
    thread = threading.Thread(target=simulate_requests, daemon=True)
    thread.start()
    
    # Keep the main thread running
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Server stopped")
```

2. Run the exporter:
   ```bash
   python prometheus_exporter.py
   ```

3. Open http://localhost:8000 in your browser to see the metrics.

### Exercise 2.2: Setting Up a Kafka Producer

1. Make sure you have Kafka running locally or use the Docker Compose setup from the course materials.

2. Create a file `kafka_producer.py` with the following content:

```python
from kafka import KafkaProducer
import json
import time
import random

def create_sample_metrics():
    """Create sample metrics data"""
    return {
        "timestamp": time.time(),
        "metrics": {
            "cpu_usage": random.uniform(20, 95),
            "memory_usage": random.uniform(30, 90),
            "disk_usage": random.uniform(40, 95),
            "network_in": random.uniform(500, 5000),
            "network_out": random.uniform(1000, 10000),
            "response_time_p95": random.uniform(100, 500),
            "error_rate": random.uniform(0, 5),
            "request_count": random.randint(500, 2000)
        }
    }

def run_producer():
    """Run the Kafka producer"""
    # Create producer
    producer = KafkaProducer(
        bootstrap_servers=['localhost:9092'],
        value_serializer=lambda v: json.dumps(v).encode('utf-8'),
        acks='all'
    )
    
    try:
        # Send metrics every second
        while True:
            metrics = create_sample_metrics()
            producer.send('metrics', metrics)
            print(f"Sent metrics: {metrics}")
            time.sleep(1)
    except KeyboardInterrupt:
        print("Producer stopped")
    finally:
        producer.flush()
        producer.close()

if __name__ == "__main__":
    run_producer()
```

3. Run the producer:
   ```bash
   python kafka_producer.py
   ```

### Exercise 2.3: Creating a Simple Knowledge Base

1. Create a file `knowledge/best_practices/performance.md` with the following content:

```markdown
# Performance Best Practices

## CPU Usage
- High CPU usage (>80%) may indicate compute-intensive operations or inefficient code
- Consider optimizing algorithms or scaling horizontally
- Look for CPU-bound processes that might be optimized

## Memory Usage
- High memory usage (>80%) may lead to swapping and performance degradation
- Check for memory leaks in long-running processes
- Consider increasing available memory or optimizing memory usage

## Disk Usage
- High disk usage (>85%) can lead to write failures and performance issues
- Implement log rotation and data archiving
- Monitor disk I/O for bottlenecks

## Network
- High network utilization may indicate DDoS, data transfer issues, or inefficient protocols
- Implement caching to reduce network traffic
- Use compression for large data transfers

## Response Time
- P95 response times >300ms indicate potential performance issues
- Look for slow database queries or external service calls
- Implement caching for frequently accessed data

## Error Rate
- Error rates >1% warrant immediate investigation
- Common causes include resource exhaustion, bugs, or external service failures
- Implement circuit breakers for external dependencies
```

2. Create a file `knowledge/incidents/recent_incident.md` with the following content:

```markdown
# Recent Incident: Database Connection Failure

## Incident Summary
- Date: Last week
- Duration: 15 minutes
- Impact: 100% of API requests failed with 500 errors

## Root Cause
The database connection pool exhausted all available connections due to a connection leak in the API service. The leak was caused by a missing connection close statement in a new endpoint.

## Resolution
1. Restarted the API service to release all connections
2. Fixed the connection leak by adding proper connection handling
3. Implemented connection pool monitoring

## Lessons Learned
- Always use connection pooling with proper connection release
- Implement monitoring for connection pool utilization
- Add circuit breakers for database connections
```

3. Create a file `build_knowledge_base.py` with the following content:

```python
from llama_index.core import SimpleDirectoryReader, VectorStoreIndex
from llama_index.core.storage.storage_context import StorageContext
from llama_index.vector_stores.qdrant import QdrantVectorStore
import qdrant_client
import os

# Set your API key (replace with your actual key)
os.environ["OPENAI_API_KEY"] = "your-openai-api-key"


# or
# os.environ["ANTHROPIC_API_KEY"] = "your-anthropic-api-key"

def build_knowledge_base():
    """Build a knowledge base from markdown files"""
    # Initialize Qdrant client (local server)
    client = qdrant_client.QdrantClient(location=":memory:")

    # Create collection
    client.create_collection(
        collection_name="monitoring_knowledge",
        vectors_config={
            "size": 1536,  # OpenAI embedding dimension
            "distance": "Cosine"
        }
    )

    # Create vector store
    vector_store = QdrantVectorStore(
        client=client,
        collection_name="monitoring_knowledge"
    )

    # Create storage context
    storage_context = StorageContext.from_defaults(vector_store=vector_store)

    # Load documents
    documents = SimpleDirectoryReader("../knowledge").load_data()
    print(f"Loaded {len(documents)} documents")

    # Build index
    index = VectorStoreIndex.from_documents(
        documents,
        storage_context=storage_context
    )

    # Test query
    query_engine = index.as_query_engine()
    response = query_engine.query("What should I do if I see high CPU usage?")
    print("\n=== QUERY RESULT ===\n")
    print(response)

    return index, query_engine


if __name__ == "__main__":
    build_knowledge_base()
```

4. Run the script:
   ```bash
   python build_knowledge_base.py
   ```

## Session 3: Implementing Smart Alerts

### Exercise 3.1: Creating a Multi-Agent System

1. Create a file `agents/multi_agent_system.py` with the following content:

```python
from crewai import Agent, Task, Crew, Process
import os
import json

# Set your API key (replace with your actual key)
os.environ["OPENAI_API_KEY"] = "your-openai-api-key"
# or
# os.environ["ANTHROPIC_API_KEY"] = "your-anthropic-api-key"

# Sample metrics with an anomaly
sample_metrics = {
    "cpu_usage": 92.5,
    "memory_usage": 87.3,
    "disk_usage": 68.9,
    "network_in": 1250.45,
    "network_out": 3420.1,
    "response_time_p95": 450.2,
    "error_rate": 3.5,
    "request_count": 1250
}

# Create agents
anomaly_detector = Agent(
    role="Anomaly Detection Specialist",
    goal="Identify anomalies in system metrics and determine their severity and impact",
    backstory="You're an expert at analyzing system metrics and detecting unusual patterns that indicate potential issues before they become critical failures.",
    verbose=True
)

root_cause_analyzer = Agent(
    role="Root Cause Analyst",
    goal="Determine the underlying cause of detected anomalies",
    backstory="You're a specialized diagnostician who can trace system issues back to their source by analyzing patterns and correlations across multiple metrics and logs.",
    verbose=True
)

remediation_advisor = Agent(
    role="Remediation Advisor",
    goal="Provide actionable recommendations to address detected issues",
    backstory="You're a seasoned operations expert who knows the best practices for addressing system issues while minimizing impact on users and maintaining system stability.",
    verbose=True
)

# Create tasks
detect_task = Task(
    description=f"Analyze the following metrics and identify any anomalies or unusual patterns. Focus on values that deviate significantly from expected ranges or show concerning trends.\n\nMETRICS DATA:\n{json.dumps(sample_metrics, indent=2)}",
    agent=anomaly_detector,
    expected_output="A detailed description of any anomalies found, including the specific metrics affected, the nature of the anomaly, and the potential severity."
)

analyze_task = Task(
    description="Based on the anomalies identified, determine the most likely root causes. Consider common failure patterns and system dependencies.",
    agent=root_cause_analyzer,
    expected_output="A ranked list of potential root causes for the observed anomalies, with supporting evidence and confidence levels for each hypothesis.",
    context=[detect_task]
)

remediate_task = Task(
    description="Develop a detailed remediation plan for the identified issues. Include immediate mitigation steps as well as longer-term solutions to prevent recurrence.",
    agent=remediation_advisor,
    expected_output="A step-by-step remediation plan with both immediate actions and strategic recommendations to address the root causes.",
    context=[detect_task, analyze_task]
)

# Create crew
crew = Crew(
    agents=[anomaly_detector, root_cause_analyzer, remediation_advisor],
    tasks=[detect_task, analyze_task, remediate_task],
    verbose=2,
    process=Process.sequential
)

# Run the crew
result = crew.kickoff()

print("\n=== ANALYSIS RESULT ===\n")
print(result)
```

2. Run the script:
   ```bash
   python agents/multi_agent_system.py
   ```

### Exercise 3.2: Implementing Alert Rules

1. Create a file `alert_rules.yml` with the following content:

```yaml
groups:
  - name: example
    rules:
      - alert: HighCpuUsage
        expr: cpu_usage > 80
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High CPU usage detected"
          description: "CPU usage is above 80% for the last 5 minutes (current value: {{ $value }}%)"

      - alert: HighMemoryUsage
        expr: memory_usage > 80
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High memory usage detected"
          description: "Memory usage is above 80% for the last 5 minutes (current value: {{ $value }}%)"

      - alert: HighErrorRate
        expr: error_rate > 1
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "High error rate detected"
          description: "Error rate is above 1% for the last 2 minutes (current value: {{ $value }}%)"

      - alert: SlowResponseTime
        expr: response_time_p95 > 300
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Slow response time detected"
          description: "95th percentile response time is above 300ms for the last 5 minutes (current value: {{ $value }}ms)"
```

2. Create a file `alert_processor.py` with the following content:

```python
import yaml
import json
import time
from crewai import Agent, Task, Crew, Process
import os

# Set your API key (replace with your actual key)
os.environ["OPENAI_API_KEY"] = "your-openai-api-key"
# or
# os.environ["ANTHROPIC_API_KEY"] = "your-anthropic-api-key"

# Load alert rules
with open('alert_rules.yml', 'r') as file:
    alert_config = yaml.safe_load(file)

# Sample metrics with anomalies
sample_metrics = {
    "cpu_usage": 92.5,
    "memory_usage": 87.3,
    "disk_usage": 68.9,
    "network_in": 1250.45,
    "network_out": 3420.1,
    "response_time_p95": 450.2,
    "error_rate": 3.5,
    "request_count": 1250,
    "timestamp": time.time()
}

def evaluate_alert_rules(metrics, rules):
    """Evaluate alert rules against metrics"""
    triggered_alerts = []
    
    for group in rules.get('groups', []):
        for rule in group.get('rules', []):
            alert_name = rule.get('alert')
            expression = rule.get('expr')
            
            # Simple expression evaluation (in a real system, this would be more sophisticated)
            metric_name, operator, threshold = parse_expression(expression)
            
            if metric_name in metrics:
                metric_value = metrics[metric_name]
                
                if operator == '>' and metric_value > threshold:
                    # Alert is triggered
                    triggered_alerts.append({
                        'alert': alert_name,
                        'severity': rule.get('labels', {}).get('severity', 'info'),
                        'summary': rule.get('annotations', {}).get('summary', ''),
                        'description': rule.get('annotations', {}).get('description', '').replace('{{ $value }}', str(metric_value)),
                        'value': metric_value,
                        'threshold': threshold
                    })
    
    return triggered_alerts

def parse_expression(expression):
    """Parse a simple alert expression (metric > threshold)"""
    parts = expression.split()
    if len(parts) == 3 and parts[1] == '>':
        return parts[0], '>', float(parts[2])
    return None, None, None

def process_alerts(metrics, alerts):
    """Process triggered alerts using AI agents"""
    if not alerts:
        print("No alerts triggered")
        return
    
    print(f"Triggered alerts: {len(alerts)}")
    for alert in alerts:
        print(f"- {alert['alert']} ({alert['severity']}): {alert['summary']}")
    
    # Create an agent to analyze the alerts
    alert_analyzer = Agent(
        role="Alert Analyst",
        goal="Analyze triggered alerts and provide context and recommendations",
        backstory="You're an expert at interpreting monitoring alerts and providing actionable insights to operations teams.",
        verbose=True
    )
    
    # Create a task for the agent
    analysis_task = Task(
        description=f"Analyze the following alerts and metrics. Provide context about the potential impact, likely causes, and recommended actions.\n\nMETRICS:\n{json.dumps(metrics, indent=2)}\n\nALERTS:\n{json.dumps(alerts, indent=2)}",
        agent=alert_analyzer,
        expected_output="A comprehensive analysis of the alerts with context, impact assessment, likely causes, and recommended actions."
    )
    
    # Create a crew with just one agent
    crew = Crew(
        agents=[alert_analyzer],
        tasks=[analysis_task],
        verbose=2,
        process=Process.sequential
    )
    
    # Run the crew
    result = crew.kickoff()
    
    print("\n=== ALERT ANALYSIS ===\n")
    print(result)

if __name__ == "__main__":
    # Evaluate alert rules
    triggered_alerts = evaluate_alert_rules(sample_metrics, alert_config)
    
    # Process alerts
    process_alerts(sample_metrics, triggered_alerts)
```

3. Run the script:
   ```bash
   python alert_processor.py
   ```

## Session 4: Deployment and Advanced Features

### Exercise 4.1: Dockerizing the Application

1. Create a file `Dockerfile` with the following content:

```dockerfile
FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Set environment variables
ENV PYTHONUNBUFFERED=1

# Expose port
EXPOSE 8000

# Run the application
CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"]
```

2. Create a file `requirements.txt` with the following content:

```
crewai
llama-index
qdrant-client
openai
anthropic
fastapi
uvicorn
prometheus-client
kafka-python
pyyaml
```

3. Create a file `api.py` with the following content:

```python
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Dict, Any, List, Optional
import json
import os
from datetime import datetime

# Import your agent system
# In a real application, you would import your actual agent system
# For this exercise, we'll create a simplified version

app = FastAPI(title="AI Monitoring API")

class MetricsRequest(BaseModel):
    metrics: Dict[str, Any]
    timestamp: Optional[float] = None

class QueryRequest(BaseModel):
    query: str
    top_k: Optional[int] = 5

class AnalysisResponse(BaseModel):
    report: str
    timestamp: str
    recommendations: List[str] = []
    severity: Optional[str] = None

class QueryResponse(BaseModel):
    response: str
    source_documents: List[Dict[str, Any]] = []

@app.get("/")
async def root():
    return {"message": "AI Monitoring API is running"}

@app.post("/analyze", response_model=AnalysisResponse)
async def analyze_metrics(request: MetricsRequest):
    """Analyze metrics using the AI agent system"""
    try:
        # In a real application, you would call your agent system here
        # For this exercise, we'll return a mock response
        
        # Mock analysis
        cpu_usage = request.metrics.get("cpu_usage", 0)
        memory_usage = request.metrics.get("memory_usage", 0)
        error_rate = request.metrics.get("error_rate", 0)
        
        severity = "critical" if error_rate > 2 or cpu_usage > 90 else "warning" if cpu_usage > 80 or memory_usage > 80 else "info"
        
        recommendations = []
        if cpu_usage > 80:
            recommendations.append("Investigate high CPU usage and consider scaling horizontally")
        if memory_usage > 80:
            recommendations.append("Check for memory leaks and consider increasing available memory")
        if error_rate > 1:
            recommendations.append("Investigate the cause of high error rates in application logs")
        
        report = f"""
# Monitoring Analysis Report

## Summary
The system is currently experiencing {severity} issues that require attention.

## Metrics Analysis
- CPU Usage: {cpu_usage}% - {'High' if cpu_usage > 80 else 'Normal'}
- Memory Usage: {memory_usage}% - {'High' if memory_usage > 80 else 'Normal'}
- Error Rate: {error_rate}% - {'High' if error_rate > 1 else 'Normal'}

## Recommendations
{'- ' + '\\n- '.join(recommendations) if recommendations else 'No immediate actions required.'}
"""
        
        return {
            "report": report,
            "timestamp": datetime.now().isoformat(),
            "recommendations": recommendations,
            "severity": severity
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Analysis error: {str(e)}")

@app.post("/query", response_model=QueryResponse)
async def query_knowledge_base(request: QueryRequest):
    """Query the knowledge base"""
    try:
        # In a real application, you would query your knowledge base here
        # For this exercise, we'll return a mock response
        
        response = f"Response to query: {request.query}"
        
        return {
            "response": response,
            "source_documents": [
                {
                    "text": "Sample document text that matches the query",
                    "score": 0.95,
                    "metadata": {"source": "best_practices/performance.md"}
                }
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Query error: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
```

4. Create a file `docker-compose.yml` with the following content:

```yaml
version: '3'

services:
  api:
    build: .
    ports:
      - "8000:8000"
    environment:
      - OPENAI_API_KEY=your-openai-api-key
      # or
      # - ANTHROPIC_API_KEY=your-anthropic-api-key
    volumes:
      - ./knowledge:/app/knowledge
```

5. Build and run the Docker container:
   ```bash
   docker-compose up --build
   ```

6. Test the API at http://localhost:8000/docs

### Exercise 4.2: Advanced Agent Capabilities

1. Create a file `agents/advanced_agent.py` with the following content:

```python
from crewai import Agent, Task, Crew, Process
from llama_index.core.tools import FunctionTool
import os
import json
import time

# Set your API key (replace with your actual key)
os.environ["OPENAI_API_KEY"] = "your-openai-api-key"
# or
# os.environ["ANTHROPIC_API_KEY"] = "your-anthropic-api-key"

# Define custom tools for the agents
def get_historical_metrics(metric_name, days=7):
    """
    Get historical metrics for a specific metric.
    
    Args:
        metric_name: The name of the metric to retrieve
        days: Number of days of historical data to retrieve
        
    Returns:
        A list of daily values for the specified metric
    """
    # In a real system, this would query a time-series database
    # For this exercise, we'll generate mock data
    import random
    
    history = []
    now = time.time()
    day_seconds = 86400  # seconds in a day
    
    for i in range(days):
        timestamp = now - (i * day_seconds)
        
        if metric_name == "cpu_usage":
            value = random.uniform(50, 85)
        elif metric_name == "memory_usage":
            value = random.uniform(60, 80)
        elif metric_name == "error_rate":
            value = random.uniform(0.1, 1.0)
        else:
            value = random.uniform(0, 100)
            
        history.append({
            "timestamp": timestamp,
            "value": value
        })
    
    return history

def check_service_status(service_name):
    """
    Check the status of a specific service.
    
    Args:
        service_name: The name of the service to check
        
    Returns:
        The status of the service
    """
    # In a real system, this would check actual service status
    # For this exercise, we'll return mock data
    services = {
        "api": "running",
        "database": "running",
        "cache": "running",
        "worker": "degraded"
    }
    
    return {
        "service": service_name,
        "status": services.get(service_name, "unknown"),
        "uptime": "3d 12h 45m" if services.get(service_name) == "running" else "15m"
    }

# Create function tools
historical_metrics_tool = FunctionTool.from_defaults(
    name="get_historical_metrics",
    fn=get_historical_metrics,
    description="Get historical metrics for a specific metric over a number of days"
)

service_status_tool = FunctionTool.from_defaults(
    name="check_service_status",
    fn=check_service_status,
    description="Check the status of a specific service"
)

# Sample metrics with an anomaly
sample_metrics = {
    "cpu_usage": 92.5,
    "memory_usage": 87.3,
    "disk_usage": 68.9,
    "network_in": 1250.45,
    "network_out": 3420.1,
    "response_time_p95": 450.2,
    "error_rate": 3.5,
    "request_count": 1250
}

# Create advanced agents with tools
anomaly_detector = Agent(
    role="Anomaly Detection Specialist",
    goal="Identify anomalies in system metrics and determine their severity and impact",
    backstory="You're an expert at analyzing system metrics and detecting unusual patterns that indicate potential issues before they become critical failures.",
    verbose=True,
    tools=[historical_metrics_tool]
)

root_cause_analyzer = Agent(
    role="Root Cause Analyst",
    goal="Determine the underlying cause of detected anomalies",
    backstory="You're a specialized diagnostician who can trace system issues back to their source by analyzing patterns and correlations across multiple metrics and logs.",
    verbose=True,
    tools=[historical_metrics_tool, service_status_tool]
)

remediation_advisor = Agent(
    role="Remediation Advisor",
    goal="Provide actionable recommendations to address detected issues",
    backstory="You're a seasoned operations expert who knows the best practices for addressing system issues while minimizing impact on users and maintaining system stability.",
    verbose=True,
    tools=[service_status_tool]
)

# Create tasks with tools
detect_task = Task(
    description=f"Analyze the following metrics and identify any anomalies or unusual patterns. Use historical data to determine if these values are abnormal compared to recent trends.\n\nMETRICS DATA:\n{json.dumps(sample_metrics, indent=2)}",
    agent=anomaly_detector,
    expected_output="A detailed description of any anomalies found, including the specific metrics affected, the nature of the anomaly, and the potential severity."
)

analyze_task = Task(
    description="Based on the anomalies identified, determine the most likely root causes. Check service statuses and use historical metrics to identify patterns that might explain the anomalies.",
    agent=root_cause_analyzer,
    expected_output="A ranked list of potential root causes for the observed anomalies, with supporting evidence and confidence levels for each hypothesis.",
    context=[detect_task]
)

remediate_task = Task(
    description="Develop a detailed remediation plan for the identified issues. Include immediate mitigation steps as well as longer-term solutions to prevent recurrence. Check service statuses to inform your recommendations.",
    agent=remediation_advisor,
    expected_output="A step-by-step remediation plan with both immediate actions and strategic recommendations to address the root causes.",
    context=[detect_task, analyze_task]
)

# Create crew
crew = Crew(
    agents=[anomaly_detector, root_cause_analyzer, remediation_advisor],
    tasks=[detect_task, analyze_task, remediate_task],
    verbose=2,
    process=Process.sequential
)

# Run the crew
result = crew.kickoff()

print("\n=== ANALYSIS RESULT ===\n")
print(result)
```

2. Run the script:
   ```bash
   python agents/advanced_agent.py
   ```

3. Observe how the agents use the tools to gather additional information for their analysis.
