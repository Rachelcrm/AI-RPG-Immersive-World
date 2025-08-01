#!/bin/bash

# This script restarts the AI Monitoring deployment

echo "Restarting the AI Monitoring deployment..."

# Restart the deployment
kubectl rollout restart deployment/ai-monitoring-agent

# Wait for the restart to complete
echo "Waiting for restart to complete..."
kubectl rollout status deployment/ai-monitoring-agent

echo "Deployment restarted successfully!"
echo "You can check the status with:"
echo "./status.sh"
