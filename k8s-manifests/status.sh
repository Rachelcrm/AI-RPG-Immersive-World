#!/bin/bash

echo "Checking Minikube status..."
minikube status

echo -e "\nChecking pods..."
kubectl get pods

echo -e "\nChecking deployments..."
kubectl get deployments

echo -e "\nChecking services..."
kubectl get services

echo -e "\nChecking Horizontal Pod Autoscalers..."
kubectl get hpa

echo -e "\nTo get detailed information about a pod, run:"
echo "kubectl describe pod <pod-name>"

echo -e "\nTo view logs for a pod, run:"
echo "kubectl logs <pod-name>"

echo -e "\nTo get the service URL, run:"
echo "minikube service ai-monitoring-service --url"
