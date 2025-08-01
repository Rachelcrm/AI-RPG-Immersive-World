# Flask Integration

This document provides examples of how to integrate the `AIPrometheusExporter` with Flask applications.

## Installation

First, make sure you have the required dependencies:

```bash
pip install flask prometheus-client
```

## Integration

### Step 1: Create a Flask Extension

Create a file named `monitoring.py` in your Flask application:

```python
from flask import Flask, request, Response, g
from examples.prom_exporter import AIPrometheusExporter


class FlaskMonitoring:
    """Flask extension for Prometheus monitoring."""

    def __init__(self, app=None, app_name="flask_app"):
        """
        Initialize the Flask monitoring extension.
        
        Args:
            app: Flask application instance
            app_name: Name of the application (used as a prefix for metrics)
        """
        self.app = app
        self.app_name = app_name
        self.exporter = AIPrometheusExporter(app_name=app_name)

        if app is not None:
            self.init_app(app)

    def init_app(self, app):
        """
        Initialize the extension with a Flask application.
        
        Args:
            app: Flask application instance
        """

        # Register before_request handler
        @app.before_request
        def before_request():
            g.start_time = self.exporter.start_request_timer(request)

        # Register after_request handler
        @app.after_request
        def after_request(response):
            self.exporter.end_request_timer(request, response)
            return response

        # Register error handler
        @app.errorhandler(Exception)
        def handle_exception(error):
            error_type = type(error).__name__
            self.exporter.record_error(request, error_type)
            # Re-raise the exception to let Flask handle it
            raise error

        # Add metrics endpoint
        @app.route('/metrics')
        def metrics():
            return Response(
                self.exporter.expose_metrics(),
                content_type="text/plain; version=0.0.4; charset=utf-8"
            )

        # Store reference to the extension
        app.extensions['prometheus_metrics'] = self

    # Implement framework-specific methods
    def _get_request_method(self, request):
        return request.method

    def _get_request_endpoint(self, request):
        return request.endpoint or request.path

    def _get_response_status(self, response):
        return str(response.status_code)
```

### Step 2: Initialize the Extension

Initialize the extension in your Flask application:

```python
from flask import Flask
from myapp.monitoring import FlaskMonitoring

app = Flask(__name__)
metrics = FlaskMonitoring(app)

# Or use the factory pattern
metrics = FlaskMonitoring()

def create_app():
    app = Flask(__name__)
    metrics.init_app(app)
    return app
```

## Custom Metrics

You can add custom metrics to your Flask application:

```python
from flask import Flask
from myapp.monitoring import FlaskMonitoring

app = Flask(__name__)
metrics = FlaskMonitoring(app)

# Create custom metrics
user_counter = metrics.exporter.create_counter(
    "users_registered_total",
    "Total number of registered users",
    ["user_type"]
)

@app.route('/register', methods=['POST'])
def register_user():
    # ... user registration logic ...
    
    # Increment the counter
    user_counter.labels(user_type="standard").inc()
    
    # ... rest of the view ...
    return {"status": "success"}
```

## Complete Example

Here's a complete example of a Flask application with Prometheus monitoring:

```python
from flask import Flask, jsonify, request
from app.prom_exporter import AIPrometheusExporter

class FlaskMonitoring:
    def __init__(self, app=None, app_name="flask_app"):
        self.app = app
        self.exporter = AIPrometheusExporter(app_name=app_name)
        
        if app is not None:
            self.init_app(app)
    
    def init_app(self, app):
        @app.before_request
        def before_request():
            self.exporter.start_request_timer(request)
        
        @app.after_request
        def after_request(response):
            self.exporter.end_request_timer(request, response)
            return response
        
        @app.route('/metrics')
        def metrics():
            return Response(
                self.exporter.expose_metrics(),
                content_type="text/plain; version=0.0.4; charset=utf-8"
            )
        
        # Store reference to the extension
        app.extensions['prometheus_metrics'] = self
    
    def _get_request_method(self, request):
        return request.method
    
    def _get_request_endpoint(self, request):
        return request.endpoint or request.path
    
    def _get_response_status(self, response):
        return str(response.status_code)

# Create Flask app
app = Flask(__name__)

# Initialize monitoring
metrics = FlaskMonitoring(app)

# Create custom metrics
api_calls = metrics.exporter.create_counter(
    "api_calls_total",
    "Total number of API calls",
    ["endpoint"]
)

# Define routes
@app.route('/api/data')
def get_data():
    # Increment custom metric
    api_calls.labels(endpoint="get_data").inc()
    
    # Return response
    return jsonify({"data": "example"})

@app.route('/api/users')
def get_users():
    # Increment custom metric
    api_calls.labels(endpoint="get_users").inc()
    
    # Return response
    return jsonify({"users": ["user1", "user2"]})

if __name__ == '__main__':
    app.run(debug=True)
