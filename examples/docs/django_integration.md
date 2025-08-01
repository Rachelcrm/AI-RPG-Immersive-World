# Django Integration

This document provides examples of how to integrate the `AIPrometheusExporter` with Django applications.

## Installation

First, make sure you have the required dependencies:

```bash
pip install django prometheus-client
```

## Integration

### Step 1: Create a Middleware

Create a file named `middleware.py` in your Django application:

```python
from django.http import HttpRequest, HttpResponse
from django.utils.deprecation import MiddlewareMixin
from examples.prom_exporter import AIPrometheusExporter

class AIMonitoringMiddleware(MiddlewareMixin):
    """Django middleware for monitoring with Prometheus."""
    
    def __init__(self, get_response=None):
        super().__init__(get_response)
        self.exporter = AIPrometheusExporter(app_name="django_app")
    
    def process_request(self, request):
        """Start timing the request."""
        self.exporter.start_request_timer(request)
        
    def process_response(self, request, response):
        """End timing the request and record metrics."""
        self.exporter.end_request_timer(request, response)
        return response
    
    def process_exception(self, request, exception):
        """Record exceptions."""
        error_type = type(exception).__name__
        self.exporter.record_error(request, error_type)
    
    # Implement framework-specific methods
    def _get_request_method(self, request):
        return request.method
    
    def _get_request_endpoint(self, request):
        try:
            from django.urls import resolve
            resolver_match = resolve(request.path)
            return resolver_match.view_name
        except:
            return request.path
    
    def _get_response_status(self, response):
        return str(response.status_code)
```

### Step 2: Add Middleware to Settings

Add the middleware to your Django settings:

```python
# In settings.py
MIDDLEWARE = [
    # ...
    'myapp.middleware.AIMonitoringMiddleware',
    # ...
]
```

### Step 3: Create a Metrics Endpoint

Create a view to expose the metrics:

```python
# In views.py
from django.http import HttpResponse
from myapp.middleware import AIMonitoringMiddleware

def metrics_view(request):
    """Expose Prometheus metrics."""
    middleware = AIMonitoringMiddleware()
    metrics_data = middleware.exporter.expose_metrics()
    return HttpResponse(
        metrics_data,
        content_type="text/plain; version=0.0.4; charset=utf-8"
    )
```

### Step 4: Add URL Route

Add a URL route for the metrics endpoint:

```python
# In urls.py
from django.urls import path
from myapp.views import metrics_view

urlpatterns = [
    # ...
    path('metrics/', metrics_view, name='metrics'),
    # ...
]
```

## Custom Metrics

You can add custom metrics to your Django application:

```python
# In views.py
from myapp.middleware import AIMonitoringMiddleware

# Get the exporter from the middleware
middleware = AIMonitoringMiddleware()
exporter = middleware.exporter

# Create custom metrics
user_counter = exporter.create_counter(
    "users_registered_total",
    "Total number of registered users",
    ["user_type"]
)

# Use in a view
def register_user(request):
    # ... user registration logic ...
    
    # Increment the counter
    user_counter.labels(user_type="standard").inc()
    
    # ... rest of the view ...
```

## Complete Example

Here's a complete example of a Django application with Prometheus monitoring:

```python
# middleware.py
from django.http import HttpRequest, HttpResponse
from django.utils.deprecation import MiddlewareMixin
from app.prom_exporter import AIPrometheusExporter

class AIMonitoringMiddleware(MiddlewareMixin):
    def __init__(self, get_response=None):
        super().__init__(get_response)
        self.exporter = AIPrometheusExporter(app_name="django_app")
    
    def process_request(self, request):
        self.exporter.start_request_timer(request)
        
    def process_response(self, request, response):
        self.exporter.end_request_timer(request, response)
        return response
    
    def _get_request_method(self, request):
        return request.method
    
    def _get_request_endpoint(self, request):
        return request.path
    
    def _get_response_status(self, response):
        return str(response.status_code)

# views.py
from django.http import HttpResponse, JsonResponse
from .middleware import AIMonitoringMiddleware

middleware = AIMonitoringMiddleware()
exporter = middleware.exporter

# Custom metrics
api_calls = exporter.create_counter(
    "api_calls_total",
    "Total number of API calls",
    ["endpoint"]
)

def metrics_view(request):
    metrics_data = exporter.expose_metrics()
    return HttpResponse(
        metrics_data,
        content_type="text/plain; version=0.0.4; charset=utf-8"
    )

def api_endpoint(request):
    # Increment custom metric
    api_calls.labels(endpoint="api_endpoint").inc()
    
    # Return response
    return JsonResponse({"status": "success"})

# urls.py
from django.urls import path
from .views import metrics_view, api_endpoint

urlpatterns = [
    path('metrics/', metrics_view, name='metrics'),
    path('api/', api_endpoint, name='api_endpoint'),
]

# settings.py
MIDDLEWARE = [
    # ...
    'myapp.middleware.AIMonitoringMiddleware',
    # ...
]
