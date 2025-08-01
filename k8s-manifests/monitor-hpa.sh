#!/bin/bash

# This script monitors the Horizontal Pod Autoscaler

echo "Monitoring Horizontal Pod Autoscaler..."
echo "Press Ctrl+C to exit"

# Watch the HPA
kubectl get hpa ai-monitoring-hpa --watch
