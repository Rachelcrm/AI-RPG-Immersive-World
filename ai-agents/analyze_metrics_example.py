#!/usr/bin/env python3
"""
Example script for analyzing metrics using the AI monitoring system.

This script demonstrates how to:
1. Initialize the monitoring agent system
2. Prepare sample metrics data
3. Analyze the metrics using the AI agents
4. Display the analysis results
"""

import os
import json
import sys
from datetime import datetime, timedelta
from dotenv import load_dotenv

# Add the current directory to the path so we can import our modules
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Import our agent system
from agent_system import MonitoringAgentSystem


def generate_sample_metrics():
    """Generate sample metrics data for demonstration purposes."""
    # Current time as base
    now = datetime.now()
    
    # Generate timestamps for the last hour (every 5 minutes)
    timestamps = [
        (now - timedelta(minutes=i*5)).timestamp() 
        for i in range(12)
    ]
    
    # Sample CPU metrics with an anomaly (spike at 25 minutes ago)
    cpu_metrics = []
    for i, ts in enumerate(timestamps):
        # Normal CPU around 30%, with a spike to 95% at 25 minutes ago
        cpu_value = 95.0 if i == 5 else 30.0 + (5.0 * (i % 3))
        cpu_metrics.append({
            "name": "cpu_usage_percent",
            "value": cpu_value,
            "labels": {"host": "web-server-01", "environment": "production"},
            "timestamp": ts
        })
    
    # Sample memory metrics with a gradual increase (potential memory leak)
    memory_metrics = []
    for i, ts in enumerate(timestamps):
        # Memory gradually increasing from 40% to 80%
        memory_value = 40.0 + (i * 3.5)
        memory_metrics.append({
            "name": "memory_usage_percent",
            "value": memory_value,
            "labels": {"host": "web-server-01", "environment": "production"},
            "timestamp": ts
        })
    
    # Sample API latency metrics with an increase correlating with CPU spike
    latency_metrics = []
    for i, ts in enumerate(timestamps):
        # Normal latency around 100ms, with an increase during CPU spike
        latency_value = 350.0 if 4 <= i <= 6 else 100.0 + (20.0 * (i % 3))
        latency_metrics.append({
            "name": "api_latency_ms",
            "value": latency_value,
            "labels": {"endpoint": "/api/users", "method": "GET"},
            "timestamp": ts
        })
    
    # Sample error rate metrics
    error_metrics = []
    for i, ts in enumerate(timestamps):
        # Error rate increases during the CPU spike
        error_value = 5.2 if 4 <= i <= 6 else 0.5
        error_metrics.append({
            "name": "error_rate_percent",
            "value": error_value,
            "labels": {"service": "user-service"},
            "timestamp": ts
        })
    
    # Combine all metrics
    all_metrics = cpu_metrics + memory_metrics + latency_metrics + error_metrics
    
    return all_metrics


def main():
    """Main function to demonstrate metric analysis."""
    # Load environment variables
    load_dotenv()
    
    # Get API keys from environment variables
    openai_api_key = os.getenv("OPENAI_API_KEY", "")
    if not openai_api_key:
        print("Error: OPENAI_API_KEY environment variable is required")
        print("Please set it in your .env file or environment")
        sys.exit(1)
    
    anthropic_api_key = os.getenv("ANTHROPIC_API_KEY", "")
    
    print("Initializing the monitoring agent system...")
    # Initialize the agent system
    agent_system = MonitoringAgentSystem(
        openai_api_key=openai_api_key,
        anthropic_api_key=anthropic_api_key,
        knowledge_base_path="./knowledge",
        qdrant_url="http://localhost:6333",  # Use localhost for the example
        collection_name="monitoring_knowledge"
    )
    
    print("Generating sample metrics data...")
    # Generate sample metrics
    metrics_data = generate_sample_metrics()
    
    # Print a sample of the metrics
    print("\nSample metrics data:")
    for metric_type in ["cpu_usage_percent", "memory_usage_percent", "api_latency_ms", "error_rate_percent"]:
        sample = next((m for m in metrics_data if m["name"] == metric_type), None)
        if sample:
            print(f"  {sample['name']}: {sample['value']} (timestamp: {datetime.fromtimestamp(sample['timestamp']).strftime('%H:%M:%S')})")
    
    print("\nAnalyzing metrics using AI agents...")
    print("(This may take a few minutes depending on the LLM response time)")
    
    # Analyze the metrics
    try:
        result = agent_system.analyze_metrics(metrics_data)
        
        # Print the analysis result
        print("\n" + "="*80)
        print("ANALYSIS RESULT:")
        print("="*80)
        print(result["report"])
        print("="*80)
        print(f"Analysis completed at: {result['timestamp']}")
        
        # Save the result to a file
        output_file = "metric_analysis_result.txt"
        with open(output_file, "w") as f:
            f.write(f"Analysis Report:\n{result['report']}\n\n")
            f.write(f"Timestamp: {result['timestamp']}")
        print(f"\nFull analysis result saved to {output_file}")
        
    except Exception as e:
        print(f"Error analyzing metrics: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
