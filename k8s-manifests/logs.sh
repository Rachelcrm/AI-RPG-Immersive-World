#!/bin/bash

# This script helps view logs from the AI Monitoring application pods

# Check if a pod name was provided as an argument
if [ $# -eq 1 ]; then
    POD_NAME=$1
    
    # Check if the pod exists
    if ! kubectl get pod $POD_NAME &> /dev/null; then
        echo "Error: Pod $POD_NAME not found."
        exit 1
    fi
else
    # Get the first pod with the ai-monitoring-agent label
    POD_NAME=$(kubectl get pods -l app=ai-monitoring-agent -o jsonpath="{.items[0].metadata.name}" 2>/dev/null)
    
    if [ -z "$POD_NAME" ]; then
        echo "Error: No pods found for the ai-monitoring-agent application."
        echo "Make sure the deployment is running by checking 'kubectl get pods'."
        exit 1
    fi
fi

# Check if -f flag was provided
if [[ "$*" == *"-f"* ]]; then
    FOLLOW="-f"
else
    FOLLOW=""
fi

echo "Viewing logs for pod: $POD_NAME"
echo "Press Ctrl+C to exit"

# View the logs
kubectl logs $FOLLOW $POD_NAME
