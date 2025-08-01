#!/bin/bash

# Exit on error
set -e

echo "Starting Minikube if not already running..."
minikube status || minikube start

echo "Pointing shell to Minikube's Docker daemon..."
eval $(minikube docker-env)

echo "Building Docker image..."
docker build -t ai-monitoring:latest -f ../ai-agents/Dockerfile ..

echo "Applying Kubernetes manifests..."
kubectl apply -f .

echo "Waiting for deployment to be ready..."
kubectl rollout status deployment/ai-monitoring-agent

echo "Creating Horizontal Pod Autoscaler..."
kubectl apply -f hpa.yaml

echo "Deployment complete! You can access the service with:"
echo "minikube service ai-monitoring-service"

# Get the service URL
URL=$(minikube service ai-monitoring-service --url)
echo "Service URL: $URL"
