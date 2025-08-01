#!/bin/bash

# This script helps debug image pull issues

echo "Debugging image pull issues..."

# Get pods with image pull errors
echo -e "\nPods with image pull errors:"
kubectl get pods | grep -E "ErrImagePull|ImagePullBackOff"

# Get detailed information about pods with issues
PROBLEM_PODS=$(kubectl get pods | grep -E "ErrImagePull|ImagePullBackOff" | awk '{print $1}')

if [ -n "$PROBLEM_PODS" ]; then
    echo -e "\nDetailed information about problematic pods:"
    for pod in $PROBLEM_PODS; do
        echo -e "\n==== Pod: $pod ===="
        kubectl describe pod $pod | grep -A 10 "Events:"
    done
    
    echo -e "\nChecking images in Minikube's Docker daemon..."
    eval $(minikube docker-env)
    
    # Extract image names from problematic pods
    for pod in $PROBLEM_PODS; do
        IMAGE=$(kubectl get pod $pod -o jsonpath="{.spec.containers[0].image}")
        echo -e "\nChecking for image: $IMAGE"
        
        # Check if image exists in Minikube's Docker daemon
        if docker images | grep -q $(echo $IMAGE | cut -d':' -f1); then
            echo "✅ Image found in Minikube's Docker daemon"
            docker images | grep $(echo $IMAGE | cut -d':' -f1)
        else
            echo "❌ Image NOT found in Minikube's Docker daemon"
            echo "You need to build the image with:"
            echo "eval \$(minikube docker-env)"
            echo "docker build -t $IMAGE ."
        fi
    done
    
    echo -e "\nPossible solutions:"
    echo "1. Make sure the image name in deployment.yaml matches the one you built"
    echo "2. Build the image directly in Minikube's Docker daemon:"
    echo "   eval \$(minikube docker-env)"
    echo "   docker build -t <image-name>:<tag> ."
    echo "3. Set imagePullPolicy to 'Never' instead of 'IfNotPresent' to only use local images"
    echo "4. Check for typos in the image name or tag"
else
    echo "No pods with image pull errors found."
fi
