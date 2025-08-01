#!/bin/bash

# This script creates a Horizontal Pod Autoscaler for the AI Monitoring deployment

echo "Creating Horizontal Pod Autoscaler for AI Monitoring..."

# Apply the HPA configuration
kubectl apply -f hpa.yaml

echo "HPA created successfully!"
echo "You can check the HPA status with:"
echo "kubectl get hpa"
echo "or use the monitor-hpa.sh script to watch the HPA in real-time."
