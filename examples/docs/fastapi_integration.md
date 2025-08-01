# FastAPI Integration

This document provides examples of how to integrate the `AIPrometheusExporter` with FastAPI applications.

## Installation

First, make sure you have the required dependencies:

```bash
pip install fastapi uvicorn prometheus-client
```

## Integration

### Step 1: Create a Middleware

Create a file named `monitoring.py` in your FastAPI application:

```python
from fastapi import FastAPI, Request, Response
from fastapi.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response as StarletteResponse
from examples.prom_exporter import AIPrometheusExporter
import time


class AIMonitoringMiddleware(BaseHTTPMiddleware):
    """FastAPI middleware for monitoring with Prometheus."""

    def __init__(self, app: FastAPI, app_name: str = "fastapi_app"):
        """
        Initialize the middleware.
        
        Args:
            app: FastAPI application instance
            app_name: Name of the application (used as a prefix for metrics)
        """
        super().__init__(app)
        self.app = app
        self.exporter = AIPrometheusExporter(app_name=app_name)

        # Add metrics endpoint
        @app.get("/metrics")
        async def metrics():
            return Response(
                content=self.exporter.expose_metrics(),
                media_type="text/plain; version=0.0.4; charset=utf-8"
            )

    async def dispatch(self, request: Request, call_next):
        """
        Process the request and response.
        
        Args:
            request: FastAPI request
            call_next: Next middleware or route handler
            
        Returns:
            Response: FastAPI response
        """
        # Start timing the request
        self.exporter.start_request_timer(request)

        try:
            # Process the request
            response = await call_next(request)

            # End timing the request
            self.exporter.end_request_timer(request, response)

            return response
        except Exception as e:
            # Record the error
            error_type = type(e).__name__
            self.exporter.record_error(request, error_type)

            # Re-raise the exception
            raise

    # Implement framework-specific methods
    def _get_request_method(self, request: Request) -> str:
        return request.method

    def _get_request_endpoint(self, request: Request) -> str:
        return request.url.path

    def _get_response_status(self, response: StarletteResponse) -> str:
        return str(response.status_code)
```

### Step 2: Add Middleware to FastAPI App

Add the middleware to your FastAPI application:

```python
from fastapi import FastAPI
from myapp.monitoring import AIMonitoringMiddleware

app = FastAPI()

# Add the monitoring middleware
app.add_middleware(AIMonitoringMiddleware)
```

## Custom Metrics

You can add custom metrics to your FastAPI application:

```python
from fastapi import FastAPI, Depends
from myapp.monitoring import AIMonitoringMiddleware

app = FastAPI()
middleware = AIMonitoringMiddleware(app)

# Create custom metrics
user_counter = middleware.exporter.create_counter(
    "users_registered_total",
    "Total number of registered users",
    ["user_type"]
)

@app.post("/register")
async def register_user(user_data: dict):
    # ... user registration logic ...
    
    # Increment the counter
    user_counter.labels(user_type="standard").inc()
    
    # ... rest of the endpoint ...
    return {"status": "success"}
```

## Complete Example

Here's a complete example of a FastAPI application with Prometheus monitoring:

```python
from fastapi import FastAPI, Request, Response, HTTPException
from fastapi.middleware.base import BaseHTTPMiddleware
from app.prom_exporter import AIPrometheusExporter
from pydantic import BaseModel

class AIMonitoringMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: FastAPI, app_name: str = "fastapi_app"):
        super().__init__(app)
        self.app = app
        self.exporter = AIPrometheusExporter(app_name=app_name)
        
        # Add metrics endpoint
        @app.get("/metrics")
        async def metrics():
            return Response(
                content=self.exporter.expose_metrics(),
                media_type="text/plain; version=0.0.4; charset=utf-8"
            )
    
    async def dispatch(self, request: Request, call_next):
        self.exporter.start_request_timer(request)
        
        try:
            response = await call_next(request)
            self.exporter.end_request_timer(request, response)
            return response
        except Exception as e:
            error_type = type(e).__name__
            self.exporter.record_error(request, error_type)
            raise
    
    def _get_request_method(self, request: Request) -> str:
        return request.method
    
    def _get_request_endpoint(self, request: Request) -> str:
        return request.url.path
    
    def _get_response_status(self, response) -> str:
        return str(response.status_code)

# Create FastAPI app
app = FastAPI(title="Example API")

# Add monitoring middleware
middleware = AIMonitoringMiddleware(app)

# Create custom metrics
api_calls = middleware.exporter.create_counter(
    "api_calls_total",
    "Total number of API calls",
    ["endpoint"]
)

# Define data models
class Item(BaseModel):
    name: str
    price: float

# Define routes
@app.get("/items")
async def get_items():
    # Increment custom metric
    api_calls.labels(endpoint="get_items").inc()
    
    # Return response
    return [{"name": "Item 1", "price": 10.5}, {"name": "Item 2", "price": 20.0}]

@app.post("/items")
async def create_item(item: Item):
    # Increment custom metric
    api_calls.labels(endpoint="create_item").inc()
    
    # Return response
    return {"status": "created", "item": item.dict()}

@app.get("/error")
async def trigger_error():
    # This will be caught by the middleware
    raise HTTPException(status_code=500, detail="Intentional error")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
