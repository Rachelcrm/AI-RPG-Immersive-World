#!/bin/bash

# This script helps scale the AI Monitoring deployment

# Default replicas
REPLICAS=1

# Check if a replica count was provided as an argument
if [ $# -eq 1 ]; then
    # Check if the argument is a positive integer
    if [[ $1 =~ ^[0-9]+$ ]]; then
        REPLICAS=$1
    else
        echo "Error: Replica count must be a positive integer."
        echo "Usage: $0 [replica_count]"
        exit 1
    fi
fi

echo "Scaling the AI Monitoring deployment to $REPLICAS replicas..."

# Scale the deployment
kubectl scale deployment/ai-monitoring-agent --replicas=$REPLICAS

# Wait for the scaling to complete
echo "Waiting for scaling to complete..."
kubectl rollout status deployment/ai-monitoring-agent

echo "Deployment scaled successfully to $REPLICAS replicas!"
echo "You can check the status with:"
echo "./status.sh"
