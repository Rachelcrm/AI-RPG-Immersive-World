#!/bin/bash

# This script generates load on the AI Monitoring deployment to test the HPA

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

echo "Generating CPU load on pod: $POD_NAME"
echo "This will run a CPU-intensive task in the pod to trigger the HPA."
echo "Press Ctrl+C to stop the load generation."

# Run a CPU-intensive task in the pod
kubectl exec -it $POD_NAME -- bash -c "while true; do echo 'Generating CPU load...'; for i in {1..1000000}; do echo \$i > /dev/null; done; done"
