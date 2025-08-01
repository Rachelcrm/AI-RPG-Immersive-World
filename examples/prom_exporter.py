import threading
import time
from typing import Any, List, Optional

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, Summary, generate_latest


class AIPrometheusExporter:
    """
    A generic Prometheus metrics exporter for web applications.
    
    This class provides a framework-agnostic way to instrument web applications
    and expose metrics to Prometheus. It can be extended or integrated with
    different web frameworks through middleware or extensions.
    """
    
    def __init__(self, app_name: str = "web_app", registry: Optional[CollectorRegistry] = None):
        """
        Initialize the Prometheus exporter.
        
        Args:
            app_name: Name of the application (used as a prefix for metrics)
            registry: Optional custom Prometheus registry
        """
        self.app_name = app_name
        self.registry = registry or CollectorRegistry()
        
        # Initialize metrics
        # self._setup_metrics()

        # Thread-local storage for request timing
        self.local = threading.local()

    def _setup_metrics(self):
        """Set up the default metrics"""
        # Request count and latency
        self.request_counter = Counter(
            f"{self.app_name}_requests_total",
            "Total number of HTTP requests",
            ["method", "endpoint", "status"],
            registry=self.registry
        )

        self.request_latency = Histogram(
            f"{self.app_name}_request_duration_seconds",
            "HTTP request latency in seconds",
            ["method", "endpoint"],
            registry=self.registry
        )

        # Error count
        self.error_counter = Counter(
            f"{self.app_name}_errors_total",
            "Total number of errors",
            ["method", "endpoint", "error_type"],
            registry=self.registry
        )

        # Active requests gauge
        self.active_requests = Gauge(
            f"{self.app_name}_active_requests",
            "Number of active HTTP requests",
            ["method"],
            registry=self.registry
        )

        # Custom metrics can be added by extending this class

    def start_request_timer(self, request: Any):
        """
        Start timing a request. Call this at the beginning of a request.
        
        Args:
            request: The request object (framework-specific)
        """
        # Store start time in thread-local storage
        self.local.start_time = time.time()
        
        # Extract method from request (framework-specific implementation required)
        method = self._get_request_method(request)
        
        # Increment active requests gauge
        self.active_requests.labels(method=method).inc()
    
    def end_request_timer(self, request: Any, response: Any):
        """
        End timing a request. Call this at the end of a request.
        
        Args:
            request: The request object (framework-specific)
            response: The response object (framework-specific)
        """
        # Skip if no start time was recorded
        if not hasattr(self.local, "start_time"):
            return
        
        # Calculate duration
        duration = time.time() - self.local.start_time
        
        # Extract request details (framework-specific implementation required)
        method = self._get_request_method(request)
        endpoint = self._get_request_endpoint(request)
        status = self._get_response_status(response)
        
        # Record metrics
        self.request_counter.labels(method=method, endpoint=endpoint, status=status).inc()
        self.request_latency.labels(method=method, endpoint=endpoint).observe(duration)
        
        # Decrement active requests gauge
        self.active_requests.labels(method=method).dec()
        
        # Clean up thread-local storage
        del self.local.start_time
    
    def record_error(self, request: Any, error_type: str):
        """
        Record an error.
        
        Args:
            request: The request object (framework-specific)
            error_type: Type of error
        """
        method = self._get_request_method(request)
        endpoint = self._get_request_endpoint(request)
        
        self.error_counter.labels(method=method, endpoint=endpoint, error_type=error_type).inc()
    
    def expose_metrics(self) -> bytes:
        """
        Generate Prometheus metrics output.
        
        Returns:
            bytes: Prometheus metrics in text format
        """
        return generate_latest(self.registry)
    
    # Framework-specific methods (to be implemented by subclasses)
    def _get_request_method(self, request: Any) -> str:
        """
        Extract HTTP method from request.
        
        Args:
            request: The request object (framework-specific)
            
        Returns:
            str: HTTP method (GET, POST, etc.)
        """
        # Default implementation (override in subclasses)
        return "UNKNOWN"
    
    def _get_request_endpoint(self, request: Any) -> str:
        """
        Extract endpoint from request.
        
        Args:
            request: The request object (framework-specific)
            
        Returns:
            str: Request endpoint
        """
        # Default implementation (override in subclasses)
        return "UNKNOWN"
    
    def _get_response_status(self, response: Any) -> str:
        """
        Extract status code from response.
        
        Args:
            response: The response object (framework-specific)
            
        Returns:
            str: Response status code
        """
        # Default implementation (override in subclasses)
        return "UNKNOWN"
    
    # Custom metric helpers
    def create_counter(self, name: str, description: str, labels: List[str] = None) -> Counter:
        """
        Create a custom counter metric.
        
        Args:
            name: Metric name
            description: Metric description
            labels: List of label names
            
        Returns:
            Counter: Prometheus counter metric
        """
        full_name = f"{self.app_name}_{name}"
        return Counter(full_name, description, labels or [], registry=self.registry)
    
    def create_gauge(self, name: str, description: str, labels: List[str] = None) -> Gauge:
        """
        Create a custom gauge metric.
        
        Args:
            name: Metric name
            description: Metric description
            labels: List of label names
            
        Returns:
            Gauge: Prometheus gauge metric
        """
        full_name = f"{self.app_name}_{name}"
        return Gauge(full_name, description, labels or [], registry=self.registry)
    
    def create_histogram(self, name: str, description: str, labels: List[str] = None, buckets: List[float] = None) -> Histogram:
        """
        Create a custom histogram metric.
        
        Args:
            name: Metric name
            description: Metric description
            labels: List of label names
            buckets: List of bucket boundaries
            
        Returns:
            Histogram: Prometheus histogram metric
        """
        full_name = f"{self.app_name}_{name}"
        return Histogram(full_name, description, labels or [], buckets=buckets or Histogram.DEFAULT_BUCKETS, registry=self.registry)
    
    def create_summary(self, name: str, description: str, labels: List[str] = None) -> Summary:
        """
        Create a custom summary metric.
        
        Args:
            name: Metric name
            description: Metric description
            labels: List of label names
            
        Returns:
            Summary: Prometheus summary metric
        """
        full_name = f"{self.app_name}_{name}"
        return Summary(full_name, description, labels or [], registry=self.registry)
