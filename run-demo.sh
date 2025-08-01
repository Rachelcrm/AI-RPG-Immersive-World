#!/bin/bash

# AI Monitoring System Demo Launcher
# This script provides a one-click way to run the AI monitoring system demo

# Color codes for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to check if a service is running
check_service() {
    local service_name=$1
    local check_command=$2
    
    echo -e "${BLUE}Checking if $service_name is running...${NC}"
    
    if eval "$check_command"; then
        echo -e "${GREEN}✓ $service_name is running${NC}"
        return 0
    else
        echo -e "${RED}✗ $service_name is not running${NC}"
        return 1
    fi
}

# Print banner
echo -e "${BLUE}============================================${NC}"
echo -e "${BLUE}    AI Monitoring System Demo Launcher     ${NC}"
echo -e "${BLUE}============================================${NC}"
echo ""

# Check if Python is installed
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}Error: Python 3 is not installed or not in PATH${NC}"
    exit 1
fi

# Check if required Python packages are installed
echo -e "${BLUE}Checking required Python packages...${NC}"
python3 -c "import requests, uvicorn" 2>/dev/null
if [ $? -ne 0 ]; then
    echo -e "${YELLOW}Installing required Python packages...${NC}"
    pip install requests uvicorn fastapi prometheus-client confluent-kafka
fi

# Check if Docker services are running
docker_running=true
check_service "Docker" "docker ps &>/dev/null" || docker_running=false

if [ "$docker_running" = true ]; then
    # Check if required Docker services are running
    check_service "Prometheus" "curl -s http://localhost:9090/-/healthy &>/dev/null" || echo -e "${YELLOW}Warning: Prometheus is not running. Make sure to start it with docker-compose.${NC}"
    check_service "Kafka" "nc -z localhost 9092 &>/dev/null" || echo -e "${YELLOW}Warning: Kafka is not running. Make sure to start it with docker-compose.${NC}"
    check_service "AI Agents API" "curl -s http://localhost:8001/health &>/dev/null" || echo -e "${YELLOW}Warning: AI Agents API is not running. Make sure to start it with docker-compose.${NC}"
    check_service "Main API" "curl -s http://localhost:8000/health &>/dev/null" || echo -e "${YELLOW}Warning: Main API is not running. Make sure to start it with docker-compose.${NC}"
else
    echo -e "${YELLOW}Warning: Docker is not running. Some features may not work correctly.${NC}"
    echo -e "${YELLOW}Please make sure docker-compose services are running:${NC}"
    echo -e "${YELLOW}  docker-compose up -d${NC}"
fi

echo ""
echo -e "${BLUE}Select anomaly type to demonstrate:${NC}"
echo -e "  ${GREEN}1) Normal traffic${NC} - Baseline traffic pattern"
echo -e "  ${YELLOW}2) Spike anomaly${NC} - Sudden spike in errors and latency"
echo -e "  ${RED}3) Gradual degradation${NC} - Slowly increasing errors and latency"
echo ""
read -p "Enter your choice (1-3): " choice

# Set anomaly type based on user choice
case $choice in
    1)
        anomaly_type="normal"
        ;;
    2)
        anomaly_type="spike"
        ;;
    3)
        anomaly_type="gradual_degradation"
        ;;
    *)
        echo -e "${RED}Invalid choice. Using normal traffic pattern.${NC}"
        anomaly_type="normal"
        ;;
esac

echo ""
echo -e "${BLUE}Running demo with ${anomaly_type} traffic pattern...${NC}"
echo ""

# Run the demo script
python3 demo.py --anomaly "$anomaly_type" --duration 60

echo ""
echo -e "${GREEN}Demo completed!${NC}"
echo ""

