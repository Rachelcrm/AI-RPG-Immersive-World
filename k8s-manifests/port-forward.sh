#!/bin/bash

# This script sets up port forwarding to access the AI Monitoring application

# Default port
PORT=8001

# Check if a port was provided as an argument
if [ $# -eq 1 ]; then
    PORT=$1
fi

# Get the pod name
POD_NAME=$(kubectl get pods -l app=ai-monitoring-agent -o jsonpath="{.items[0].metadata.name}")

if [ -z "$POD_NAME" ]; then
    echo "Error: No pods found for the ai-monitoring-agent application."
    echo "Make sure the deployment is running by checking 'kubectl get pods'."
    exit 1
fi

echo "Setting up port forwarding from localhost:$PORT to pod $POD_NAME:8001"
echo "You can access the application at http://localhost:$PORT"
echo "Press Ctrl+C to stop port forwarding"

# Set up port forwarding
kubectl port-forward $POD_NAME $PORT:8001
