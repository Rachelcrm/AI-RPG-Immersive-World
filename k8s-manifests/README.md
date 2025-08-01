# Deploying AI Monitoring System on Minikube

This guide explains how to deploy the AI Monitoring System on a local Kubernetes cluster using Minikube.

## Quick Start

For convenience, several scripts are provided to help you deploy and manage the application:

- `setup-env.sh`: Helps set up environment variables and creates the secret.yaml file
- `deploy.sh`: Automates the entire deployment process
- `status.sh`: Checks the status of your deployment
- `port-forward.sh`: Sets up port forwarding to access the application
- `get-url.sh`: Gets the URL for the service
- `logs.sh`: Views logs from the application pods
- `restart.sh`: Restarts the deployment
- `describe-pod.sh`: Shows detailed information about a pod
- `scale.sh`: Scales the deployment to a specified number of replicas manually
- `create-hpa.sh`: Creates a Horizontal Pod Autoscaler for automatic scaling
- `monitor-hpa.sh`: Monitors the Horizontal Pod Autoscaler
- `generate-load.sh`: Generates CPU load to test the autoscaler
- `debug-image.sh`: Helps debug image pull issues
- `cleanup.sh`: Removes all Kubernetes resources

To use these scripts:

```bash
# Set up environment variables (do this first)
./setup-env.sh

# Deploy the application
./deploy.sh

# Check status
./status.sh

# Access the application via port forwarding
./port-forward.sh

# Get the service URL
./get-url.sh

# View application logs
./logs.sh

# Get detailed information about a pod
./describe-pod.sh

# For manual scaling
./scale.sh 3  # Scale to 3 replicas

# For auto-scaling
./create-hpa.sh  # Create the Horizontal Pod Autoscaler
./monitor-hpa.sh  # Monitor the HPA status
./generate-load.sh  # Generate load to test the HPA

# Debug image pull issues
./debug-image.sh  # Diagnose and fix ErrImagePull errors

# Restart the deployment if needed
./restart.sh

# Clean up when done
./cleanup.sh
```

For a more detailed, step-by-step approach, follow the instructions below.

## Prerequisites

- [Minikube](https://minikube.sigs.k8s.io/docs/start/) installed
- [kubectl](https://kubernetes.io/docs/tasks/tools/install-kubectl/) installed
- [Docker](https://docs.docker.com/get-docker/) installed

## Step 1: Start Minikube

Start your local Kubernetes cluster:

```bash
minikube start
```

## Step 2: Build and Load the Docker Image

Since we're using a local Minikube cluster, we need to build the Docker image and load it into Minikube's Docker daemon:

```bash
# Point your terminal to use Minikube's Docker daemon
eval $(minikube docker-env)

# Navigate to the project root directory
cd /path/to/multi-agent-ai-monitoring

# Build the Docker image
docker build -t ai-monitoring:latest -f ai-agents/Dockerfile .
```

## Step 3: Update Secret Values

Before deploying, update the secret values in `secret.yaml` with your actual API keys:

```bash
# Edit the secret.yaml file
kubectl edit -f k8s-manifests/secret.yaml
```

Or manually edit the file and replace the placeholder values with your actual API keys.

## Step 4: Apply Kubernetes Manifests

Apply all the Kubernetes manifests:

```bash
kubectl apply -f k8s-manifests/
```

This will create:
- ConfigMap with application configuration
- Secret with API keys
- Deployment with the application pods
- Service to expose the application

## Step 5: Verify the Deployment

Check if the pods are running:

```bash
kubectl get pods
```

Check the deployment status:

```bash
kubectl get deployments
```

Check the service:

```bash
kubectl get services
```

## Step 6: Access the Application

You can access the application using Minikube's service command:

```bash
minikube service ai-monitoring-service
```

This will open a browser window with the application URL.

Alternatively, you can get the URL with:

```bash
minikube service ai-monitoring-service --url
```

You can also use the provided get-url.sh script:

```bash
# Get the service URL
./get-url.sh
```

This script will display the URL for the service and provide instructions on how to open it in your browser.

You can also use port forwarding to access the application directly:

```bash
# Forward local port 8001 to the pod's port 8001
./port-forward.sh

# Or specify a different local port
./port-forward.sh 9000
```

This will make the application available at http://localhost:8001 (or the port you specified).

## Troubleshooting

### View Pod Logs

If the pods are not starting correctly, you can check the logs:

```bash
# Get the pod name
kubectl get pods

# View logs for a specific pod
kubectl logs <pod-name>
```

You can also use the provided logs.sh script:

```bash
# View logs for the first ai-monitoring pod
./logs.sh

# View logs for a specific pod
./logs.sh <pod-name>

# Follow logs in real-time
./logs.sh -f
```

### Check Pod Details

For more detailed information about a pod:

```bash
kubectl describe pod <pod-name>
```

You can also use the provided describe-pod.sh script:

```bash
# Describe the first ai-monitoring pod
./describe-pod.sh

# Describe a specific pod
./describe-pod.sh <pod-name>
```

This script will show detailed information about the pod, including events, conditions, and container statuses.

### Scale Deployment

#### Manual Scaling

If you need to manually scale the deployment to handle more load:

```bash
kubectl scale deployment/ai-monitoring-agent --replicas=3
```

You can also use the provided scale.sh script:

```bash
# Scale to 3 replicas
./scale.sh 3

# Scale back to 1 replica
./scale.sh 1
```

This script will scale the deployment to the specified number of replicas and wait for the scaling to complete.

#### Auto Scaling

The deployment can be automatically scaled based on CPU utilization using a Horizontal Pod Autoscaler (HPA):

```bash
# Create the HPA
./create-hpa.sh

# Monitor the HPA status
./monitor-hpa.sh
```

The HPA is configured to:
- Maintain between 1 and 5 replicas
- Scale up when average CPU utilization exceeds 70%
- Scale down when it falls below 70%

To test the auto-scaling, you can generate CPU load:

```bash
# Generate CPU load to trigger scaling
./generate-load.sh
```

You can view the current HPA status with:

```bash
kubectl get hpa
```

### Restart Deployment

If you need to restart the deployment:

```bash
kubectl rollout restart deployment ai-monitoring-agent
```

You can also use the provided restart.sh script:

```bash
# Restart the deployment
./restart.sh
```

This script will restart the deployment and wait for the rollout to complete.

### Debug Image Pull Issues

If you encounter `ErrImagePull` or `ImagePullBackOff` errors, you can use the provided debug-image.sh script:

```bash
# Run the debug script
./debug-image.sh
```

This script will:
1. Identify pods with image pull errors
2. Show detailed error information from the pod events
3. Check if the required images exist in Minikube's Docker daemon
4. Provide suggestions to fix the issues

Common causes of image pull errors in Minikube:
- Image name mismatch between deployment.yaml and what was built
- Not building the image in Minikube's Docker daemon
- Typos in image names or tags
- Using an incorrect imagePullPolicy

To fix these issues:
1. Make sure the image name in deployment.yaml matches what you built
2. Build the image directly in Minikube's Docker daemon:
   ```bash
   eval $(minikube docker-env)
   docker build -t ai-monitoring:latest -f ai-agents/Dockerfile ..
   ```
3. Set imagePullPolicy to "Never" instead of "IfNotPresent" if you're only using local images

### Delete and Redeploy

If you need to start fresh:

```bash
kubectl delete -f k8s-manifests/
kubectl apply -f k8s-manifests/
```

## Cleaning Up

When you're done, you can delete the resources:

```bash
kubectl delete -f k8s-manifests/
```

To stop Minikube:

```bash
minikube stop
