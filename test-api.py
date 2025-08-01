#!/usr/bin/env python3
"""
AI Monitoring System API Test Script

This script tests the AI monitoring system API by sending a simple request
and checking if the response is valid.
"""

import argparse
import json
import requests
import sys

def test_health(api_url):
    """Test the health endpoint"""
    try:
        response = requests.get(f"{api_url}/health")
        if response.status_code == 200:
            data = response.json()
            print(f"Health check successful: {json.dumps(data, indent=2)}")
            return True
        else:
            print(f"Health check failed with status code {response.status_code}: {response.text}")
            return False
    except requests.RequestException as e:
        print(f"Error connecting to API: {str(e)}")
        return False

def test_analyze(api_url):
    """Test the analyze endpoint with a simple metrics payload"""
    # Create a simple metrics payload
    metrics = [
        {
            "name": "example_app_requests_total",
            "value": 150,
            "labels": {
                "method": "GET",
                "endpoint": "/items",
                "status": "200"
            },
            "timestamp": 1647123456.789
        },
        {
            "name": "example_app_request_duration_seconds",
            "value": 0.15,
            "labels": {
                "method": "GET",
                "endpoint": "/items"
            },
            "timestamp": 1647123456.789
        },
        {
            "name": "example_app_errors_total",
            "value": 2,
            "labels": {
                "method": "GET",
                "endpoint": "/items",
                "error_type": "timeout"
            },
            "timestamp": 1647123456.789
        }
    ]
    
    try:
        print("Sending test metrics to analyze endpoint...")
        response = requests.post(
            f"{api_url}/analyze",
            json={"metrics": metrics}
        )
        
        if response.status_code == 200:
            data = response.json()
            print("\nAnalysis successful!")
            print(f"\nReport:\n{data['report']}")
            
            if data.get("recommendations"):
                print("\nRecommendations:")
                for i, rec in enumerate(data["recommendations"], 1):
                    print(f"{i}. {rec}")
            
            if data.get("severity"):
                print(f"\nSeverity: {data['severity']}")
                
            return True
        else:
            print(f"Analysis failed with status code {response.status_code}: {response.text}")
            return False
    except requests.RequestException as e:
        print(f"Error connecting to API: {str(e)}")
        return False

def test_query(api_url):
    """Test the query endpoint"""
    try:
        print("\nTesting knowledge base query...")
        response = requests.post(
            f"{api_url}/query",
            json={"query": "What are common causes of high error rates?", "top_k": 3}
        )
        
        if response.status_code == 200:
            data = response.json()
            print("\nQuery successful!")
            print(f"\nResponse: {data['response']}")
            
            if data.get("source_documents"):
                print("\nSource documents:")
                for i, doc in enumerate(data["source_documents"], 1):
                    print(f"{i}. {doc.get('text', '')[:100]}... (Score: {doc.get('score', 'N/A')})")
                
            return True
        else:
            print(f"Query failed with status code {response.status_code}: {response.text}")
            return False
    except requests.RequestException as e:
        print(f"Error connecting to API: {str(e)}")
        return False

def main():
    parser = argparse.ArgumentParser(description="Test the AI monitoring system API")
    parser.add_argument("--api-url", default="http://localhost:8000",
                        help="URL of the API service")
    parser.add_argument("--test", choices=["health", "analyze", "query", "all"],
                        default="all", help="Test to run")
    args = parser.parse_args()
    
    print(f"Testing AI monitoring system API at {args.api_url}")
    
    # Run the selected test(s)
    if args.test in ["health", "all"]:
        if not test_health(args.api_url):
            print("\nHealth check failed. The API may not be running.")
            if args.test == "all":
                print("Skipping remaining tests.")
                sys.exit(1)
    
    if args.test in ["analyze", "all"]:
        test_analyze(args.api_url)
    
    if args.test in ["query", "all"]:
        test_query(args.api_url)
    
    print("\nTests completed.")

if __name__ == "__main__":
    main()
