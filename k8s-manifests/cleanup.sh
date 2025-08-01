#!/bin/bash

echo "Deleting all Kubernetes resources created by the deployment..."
kubectl delete -f .

echo "Resources deleted. To stop Minikube, run:"
echo "minikube stop"
