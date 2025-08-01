#!/usr/bin/env python3
"""
AI Monitoring System Demonstration

This script demonstrates the AI-enhanced monitoring system by:
1. Starting the example web application
2. Generating traffic with configurable anomaly patterns
3. Ensuring metrics flow through Prometheus to Kafka
4. Triggering AI analysis
5. Displaying the results
"""

import argparse
import random
import subprocess
import sys
import time

import requests

# Define anomaly types
ANOMALY_TYPES = {
    "spike": "Generate sudden spike in error rates and latency",
    "gradual_degradation": "Generate gradually increasing error rates and latency",
    "normal": "Generate normal traffic patterns (baseline)"
}

def main():
    parser = argparse.ArgumentParser(description="AI Monitoring System Demo")
    parser.add_argument("--anomaly", choices=ANOMALY_TYPES.keys(), default="normal",
                        help="Type of anomaly to generate")
    parser.add_argument("--duration", type=int, default=60,
                        help="Duration of the demo in seconds")
    parser.add_argument("--api-url", default="http://localhost:8000",
                        help="URL of the API service")
    parser.add_argument("--web-app-port", type=int, default=8002,
                        help="Port to run the example web app on")
    parser.add_argument("--prometheus-url", default="http://localhost:9090",
                        help="URL of the Prometheus server")
    parser.add_argument("--kafka-brokers", default="localhost:9092",
                        help="Kafka broker addresses")
    parser.add_argument("--skip-web-app", action="store_true",
                        help="Skip starting the example web app (if it's already running)")
    parser.add_argument("--skip-bridge", action="store_true",
                        help="Skip starting the Prometheus to Kafka bridge (if it's already running)")
    args = parser.parse_args()
    
    print(f"=== AI Monitoring System Demonstration ===")
    print(f"Anomaly type: {args.anomaly}")
    print(f"Duration: {args.duration} seconds")
    
    # Start the example web app (in a separate thread)
    web_app_process = None
    if not args.skip_web_app:
        print(f"Starting example web application on port {args.web_app_port}...")
        web_app_process = start_example_web_app(args.web_app_port)
    
    # Start the Prometheus to Kafka bridge (in a separate thread)
    bridge_process = None
    if not args.skip_bridge:
        print(f"Starting Prometheus to Kafka bridge...")
        bridge_process = start_prometheus_to_kafka_bridge(
            args.prometheus_url, args.kafka_brokers
        )
    
    try:
        # Wait for services to initialize
        print("Waiting for services to initialize...")
        time.sleep(5)
        
        # Generate traffic based on the selected anomaly type
        print(f"Generating {args.anomaly} traffic pattern...")
        generate_traffic(args.anomaly, args.duration, args.web_app_port)
        
        # Wait for metrics to be processed
        print("Waiting for metrics to be processed...")
        time.sleep(10)
        
        # Trigger AI analysis
        print("Triggering AI analysis...")
        analysis_result = trigger_analysis(args.api_url)
        
        # Display the results
        print("\n=== AI Analysis Results ===\n")
        display_analysis_results(analysis_result)
        
    finally:
        # Clean up processes
        if web_app_process:
            print("Stopping example web application...")
            web_app_process.terminate()
        
        if bridge_process:
            print("Stopping Prometheus to Kafka bridge...")
            bridge_process.terminate()

def start_example_web_app(port):
    """Start the example web application in a subprocess"""
    try:
        # Fix the import in example_web_app_usage.py
        with open('examples/example_web_app_usage.py', 'r') as f:
            content = f.read()
        
        # Replace relative import with absolute import
        content = content.replace('from .prom_exporter', 'from examples.prom_exporter')
        
        with open('examples/example_web_app_usage.py', 'w') as f:
            f.write(content)
            
        # Start the web app
        process = subprocess.Popen([
            sys.executable, 
            "-m", "uvicorn", 
            "examples.example_web_app_usage:app", 
            "--host", "0.0.0.0", 
            "--port", str(port)
        ])
        
        # Wait for the web app to start
        time.sleep(2)
        
        # Check if the web app is running
        try:
            response = requests.get(f"http://localhost:{port}/")
            if response.status_code == 200:
                print(f"Example web app started successfully on port {port}")
            else:
                print(f"Example web app returned status code {response.status_code}")
        except requests.RequestException as e:
            print(f"Error connecting to example web app: {str(e)}")
        
        return process
    except Exception as e:
        print(f"Error starting example web app: {str(e)}")
        return None

def start_prometheus_to_kafka_bridge(prometheus_url, kafka_brokers):
    """Start the Prometheus to Kafka bridge in a subprocess"""
    try:
        process = subprocess.Popen([
            sys.executable,
            "examples/prometheus_to_kafka.py",
            "--exclude-internal"
        ])
        
        return process
    except Exception as e:
        print(f"Error starting Prometheus to Kafka bridge: {str(e)}")
        return None

def generate_traffic(anomaly_type, duration, port):
    """Generate traffic with the specified anomaly pattern"""
    if anomaly_type == "spike":
        generate_spike_traffic(duration, port)
    elif anomaly_type == "gradual_degradation":
        generate_gradual_degradation_traffic(duration, port)
    else:  # normal
        generate_normal_traffic(duration, port)

def generate_normal_traffic(duration, port):
    """Generate normal traffic pattern"""
    base_url = f"http://localhost:{port}"
    end_time = time.time() + duration
    
    print("Generating normal traffic pattern...")
    
    while time.time() < end_time:
        # Random endpoint selection with weighted distribution
        endpoint = random.choices(
            ["/", "/items", "/items/0", "/items/1", "/categories"],
            weights=[0.2, 0.4, 0.2, 0.1, 0.1]
        )[0]
        
        try:
            requests.get(f"{base_url}{endpoint}", timeout=2)
        except requests.RequestException:
            pass
        
        # Random sleep between requests (0.1 to 0.5 seconds)
        time.sleep(random.uniform(0.1, 0.5))
        
        # Print progress
        progress = int(((time.time() - (end_time - duration)) / duration) * 100)
        print(f"\rProgress: {progress}%", end="")
    
    print("\rProgress: 100%")

def generate_spike_traffic(duration, port):
    """Generate traffic with a sudden error spike"""
    base_url = f"http://localhost:{port}"
    start_time = time.time()
    end_time = start_time + duration
    
    # First third: normal traffic
    spike_start = start_time + (duration / 3)
    spike_end = spike_start + (duration / 3)
    
    print("Generating spike traffic pattern...")
    print("Phase 1: Normal traffic...")
    
    while time.time() < end_time:
        current_time = time.time()
        
        # During spike period
        if spike_start <= current_time < spike_end:
            if current_time - spike_start < 1:  # Just entered spike phase
                print("\nPhase 2: Spike traffic...")
            
            # High error rate (50% requests to error endpoint)
            if random.random() < 0.5:
                try:
                    requests.get(f"{base_url}/error", timeout=2)
                except requests.RequestException:
                    pass
            
            # High latency (30% requests to slow endpoint)
            elif random.random() < 0.3:
                try:
                    requests.get(f"{base_url}/slow", timeout=5)
                except requests.RequestException:
                    pass
            
            # Regular endpoints
            else:
                endpoint = random.choice(["/", "/items", "/categories"])
                try:
                    requests.get(f"{base_url}{endpoint}", timeout=2)
                except requests.RequestException:
                    pass
                
            # Faster requests during spike (0.05 to 0.2 seconds between requests)
            time.sleep(random.uniform(0.05, 0.2))
        
        # Normal traffic outside spike period
        else:
            if current_time - spike_end < 1 and current_time >= spike_end:  # Just entered recovery phase
                print("\nPhase 3: Recovery traffic...")
                
            endpoint = random.choices(
                ["/", "/items", "/items/0", "/categories", "/error", "/slow"],
                weights=[0.3, 0.3, 0.2, 0.1, 0.05, 0.05]
            )[0]
            
            try:
                requests.get(f"{base_url}{endpoint}", timeout=5)
            except requests.RequestException:
                pass
            
            # Normal sleep between requests
            time.sleep(random.uniform(0.1, 0.5))
        
        # Print progress
        progress = int(((current_time - start_time) / duration) * 100)
        print(f"\rProgress: {progress}%", end="")
    
    print("\rProgress: 100%")

def generate_gradual_degradation_traffic(duration, port):
    """Generate traffic with gradually increasing error rates and latency"""
    base_url = f"http://localhost:{port}"
    start_time = time.time()
    end_time = start_time + duration
    
    print("Generating gradual degradation traffic pattern...")
    
    while time.time() < end_time:
        current_time = time.time()
        
        # Calculate how far we are through the duration (0.0 to 1.0)
        progress = (current_time - start_time) / duration
        
        # Gradually increase error probability from 0.05 to 0.4
        error_probability = 0.05 + (0.35 * progress)
        
        # Gradually increase slow endpoint probability from 0.05 to 0.3
        slow_probability = 0.05 + (0.25 * progress)
        
        # Determine which endpoint to call
        if random.random() < error_probability:
            # Error endpoint
            try:
                requests.get(f"{base_url}/error", timeout=2)
            except requests.RequestException:
                pass
        elif random.random() < slow_probability:
            # Slow endpoint
            try:
                requests.get(f"{base_url}/slow", timeout=5)
            except requests.RequestException:
                pass
        else:
            # Regular endpoints
            endpoint = random.choice(["/", "/items", "/categories"])
            try:
                requests.get(f"{base_url}{endpoint}", timeout=2)
            except requests.RequestException:
                pass
        
        # Gradually decrease sleep time between requests (0.5 to 0.1 seconds)
        sleep_time = 0.5 - (0.4 * progress)
        time.sleep(max(0.1, sleep_time))
        
        # Print progress
        progress_percent = int(progress * 100)
        print(f"\rProgress: {progress_percent}% (Error rate: {error_probability:.2f}, Slow rate: {slow_probability:.2f})", end="")
    
    print("\rProgress: 100%")

def trigger_analysis(api_url):
    """Trigger AI analysis and return the results"""
    try:
        # Get the latest metrics from Prometheus
        prometheus_url = "http://localhost:9090"
        
        # Try different queries to get metrics
        queries = [
            '{__name__=~"example_app_.*"}',  # Original query
            '{job="example_app"}',           # Try job-based query
            '{instance=~".*:8002"}',         # Try instance-based query
            '{__name__!=""}'                 # Fallback to all metrics
        ]
        
        metrics_data = []
        for query in queries:
            print(f"Trying Prometheus query: {query}")
            prom_response = requests.get(
                f"{prometheus_url}/api/v1/query",
                params={"query": query}
            )
            
            if prom_response.status_code == 200:
                results = prom_response.json().get("data", {}).get("result", [])
                if results:
                    print(f"Found {len(results)} metrics with query: {query}")
                    break
        
        
        if prom_response.status_code != 200:
            print(f"Error fetching metrics from Prometheus: {prom_response.text}")
            return None
        
        # Format metrics for the analysis API
        metrics_data = []
        for result in prom_response.json()["data"]["result"]:
            metric_name = result["metric"]["__name__"]
            labels = {k: v for k, v in result["metric"].items() if k != "__name__"}
            value = float(result["value"][1])
            timestamp = result["value"][0]
            
            metrics_data.append({
                "name": metric_name,
                "value": value,
                "labels": labels,
                "timestamp": timestamp
            })
        
        print(f"Collected {len(metrics_data)} metrics from Prometheus")
        
        # Send metrics to the analysis API
        analysis_response = requests.post(
            f"{api_url}/analyze",
            json={"metrics": metrics_data}
        )
        
        if analysis_response.status_code != 200:
            print(f"Error triggering analysis: {analysis_response.text}")
            return None
        
        return analysis_response.json()
    
    except Exception as e:
        print(f"Error triggering analysis: {str(e)}")
        return None

def display_analysis_results(result):
    """Format and display the analysis results"""
    if not result:
        print("No analysis results available.")
        return
    
    # Print the full report
    print(result["report"])
    print("\n" + "="*50 + "\n")
    
    # Print a summary
    print("SUMMARY:")
    print(f"Timestamp: {result['timestamp']}")
    
    if result.get("severity"):
        print(f"Severity: {result['severity']}")
    
    if result.get("recommendations"):
        print("\nRECOMMENDATIONS:")
        for i, rec in enumerate(result["recommendations"], 1):
            print(f"{i}. {rec}")

if __name__ == "__main__":
    main()
