#!/bin/bash

# This script gets the URL for the AI Monitoring service

echo "Getting URL for the AI Monitoring service..."

# Get the URL
URL=$(minikube service ai-monitoring-service --url)

if [ -z "$URL" ]; then
    echo "Error: Could not get URL for the service."
    echo "Make sure the service is running by checking 'kubectl get services'."
    exit 1
fi

echo "Service URL: $URL"
echo "You can access the application at this URL."
echo "To open the URL in your default browser, run:"
echo "minikube service ai-monitoring-service"
