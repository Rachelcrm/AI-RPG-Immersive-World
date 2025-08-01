"""
Example Web Application with AI Prometheus Monitoring

This is a simple FastAPI application that demonstrates how to use the
AIPrometheusExporter for monitoring. It includes several endpoints that
generate different metrics.
"""

import random
import time
from fastapi import FastAPI, Request, Response, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from pydantic import BaseModel
import uvicorn

from examples.prom_exporter import AIPrometheusExporter
from prometheus_client import start_http_server


def init_metrics_exporter(port=8888):
    """Initialize the Prometheus metrics exporter"""
    start_http_server(port)

init_metrics_exporter()

# Create FastAPI app
app = FastAPI(
    title="AI Monitoring Example",
    description="Example web application with AI-enhanced Prometheus monitoring",
    version="0.1.0"
)

# Create monitoring middleware
class AIMonitoringMiddleware(BaseHTTPMiddleware):
    def __init__(self, app):
        super().__init__(app)
        self.exporter = AIPrometheusExporter(app_name="example_app")
        
        # Create all metrics needed by the dashboard
        # Request count
        self.request_counter = self.exporter.create_counter(
            "requests_total",
            "Total number of HTTP requests",
            ["method", "endpoint", "status"]
        )

        # Request latency
        self.request_latency = self.exporter.create_histogram(
            "request_duration_seconds",
            "HTTP request latency in seconds",
            ["method", "endpoint"]
        )

        # Error count
        self.error_counter = self.exporter.create_counter(
            "errors_total",
            "Total number of errors",
            ["method", "endpoint", "error_type"]
        )

        # Active requests gauge
        self.active_requests = self.exporter.create_gauge(
            "active_requests",
            "Number of active HTTP requests",
            ["method"]
        )

        # Processing time
        self.processing_time = self.exporter.create_histogram(
            "processing_time_seconds",
            "Time spent processing requests",
            ["endpoint"],
            buckets=[0.01, 0.05, 0.1, 0.5, 1.0, 5.0]
        )

        # Active users
        self.active_users = self.exporter.create_gauge(
            "active_users",
            "Number of active users"
        )

        # Initialize with random number of users
        self.active_users.set(random.randint(5, 20))
    
    async def dispatch(self, request: Request, call_next):
        # Track endpoint and method for metrics
        endpoint = request.url.path
        method = self._get_request_method(request)
        
        print(f"Request: {method} {endpoint}")
        
        try:
            # Increment active requests gauge
            self.active_requests.labels(method=method).inc()
            self.request_counter.labels(method=method, endpoint=endpoint, status=200).inc()
            print(f"Incremented active_requests for {method}")
            
            # Start timing
            start_time = time.time()
            
            try:
                # Process the request
                response = await call_next(request)
                
                # Get response status
                status = self._get_response_status(response)
                print(f"Response: {status} for {method} {endpoint}")
                
                # Record request metrics
                if endpoint != "/metrics":
                    try:
                        # Increment request counter
                        self.request_counter.labels(method=method, endpoint=endpoint, status=status).inc()
                        print(f"Incremented request_counter for {method} {endpoint} {status}")
                        
                        # Record request duration
                        duration = time.time() - start_time
                        self.request_latency.labels(method=method, endpoint=endpoint).observe(duration)
                        print(f"Recorded request_latency for {method} {endpoint}: {duration}")
                        
                        # Record processing time
                        processing_duration = time.time() - start_time
                        self.processing_time.labels(endpoint=endpoint).observe(processing_duration)
                        print(f"Recorded processing_time for {endpoint}: {processing_duration}")
                    except Exception as metric_error:
                        print(f"Error recording metrics: {type(metric_error).__name__}: {str(metric_error)}")
                
                # Decrement active requests gauge
                self.active_requests.labels(method=method).dec()
                print(f"Decremented active_requests for {method}")
                
                return response
            except Exception as e:
                # Record error metrics
                error_type = type(e).__name__
                print(f"Error in request: {error_type}: {str(e)}")
                try:
                    self.error_counter.labels(method=method, endpoint=endpoint, error_type=error_type).inc()
                    print(f"Incremented error_counter for {method} {endpoint} {error_type}")
                except Exception as metric_error:
                    print(f"Error recording error metric: {type(metric_error).__name__}: {str(metric_error)}")
                
                # Decrement active requests gauge
                self.active_requests.labels(method=method).dec()
                print(f"Decremented active_requests for {method}")
                
                # Re-raise the exception
                raise
        except Exception as outer_error:
            print(f"Outer error in dispatch: {type(outer_error).__name__}: {str(outer_error)}")
            raise
    
    # Implement framework-specific methods
    def _get_request_method(self, request):
        return request.method
    
    def _get_request_endpoint(self, request):
        return request.url.path
    
    def _get_response_status(self, response):
        return str(response.status_code)


middleware = AIMonitoringMiddleware(app)

# Add the SAME instance to the app
app.add_middleware(BaseHTTPMiddleware, dispatch=middleware.dispatch)
# Add metrics endpoint
@app.get("/metrics")
async def metrics():
    return Response(
        content=middleware.exporter.expose_metrics(),
        media_type="text/plain; version=0.0.4; charset=utf-8"
    )

# Define data models
class Item(BaseModel):
    name: str
    price: float
    category: str

# Sample data
items = [
    {"name": "Laptop", "price": 1299.99, "category": "Electronics"},
    {"name": "Smartphone", "price": 699.99, "category": "Electronics"},
    {"name": "Headphones", "price": 199.99, "category": "Audio"},
    {"name": "Monitor", "price": 349.99, "category": "Electronics"},
    {"name": "Keyboard", "price": 89.99, "category": "Accessories"},
]

# Define routes
@app.get("/")
async def root():
    """Root endpoint that returns a welcome message."""
    # Simulate user activity
    if random.random() > 0.7:
        # 30% chance of user count changing
        change = random.choice([-1, 1])
        current = middleware.active_users._value.get()
        # Ensure we don't go below 1 user
        new_value = max(1, current + change)
        middleware.active_users.set(new_value)
    
    return {"message": "Welcome to the AI Monitoring Example API"}

@app.get("/items")
async def get_items():
    """Get all items."""
    # Simulate variable processing time
    time.sleep(random.uniform(0.01, 0.1))
    return items

@app.get("/items/{item_id}")
async def get_item(item_id: int):
    """Get a specific item by ID."""
    # Simulate variable processing time
    time.sleep(random.uniform(0.05, 0.2))
    
    if item_id < 0 or item_id >= len(items):
        raise HTTPException(status_code=404, detail="Item not found")
    
    return items[item_id]

@app.post("/items")
async def create_item(item: Item):
    """Create a new item."""
    # Simulate variable processing time
    time.sleep(random.uniform(0.1, 0.3))
    
    items.append(item.dict())
    return {"status": "created", "item": item.dict()}

@app.get("/categories")
async def get_categories():
    """Get all unique categories."""
    # Simulate variable processing time
    time.sleep(random.uniform(0.02, 0.08))
    
    categories = set(item["category"] for item in items)
    return {"categories": list(categories)}

@app.get("/error")
async def trigger_error():
    """Endpoint that always raises an error (for testing error metrics)."""
    # 50% chance of different error types
    if random.random() > 0.5:
        raise HTTPException(status_code=500, detail="Internal server error")
    else:
        raise ValueError("Simulated value error")

@app.get("/slow")
async def slow_endpoint():
    """A deliberately slow endpoint to demonstrate latency metrics."""
    # Sleep for 1-3 seconds
    sleep_time = random.uniform(1.0, 3.0)
    time.sleep(sleep_time)
    return {"message": f"Slow response after {sleep_time:.2f} seconds"}

if __name__ == "__main__":
    uvicorn.run("examples.example_web_app_usage:app", host="0.0.0.0", port=8002, reload=True)
