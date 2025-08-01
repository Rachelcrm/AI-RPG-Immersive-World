#!/usr/bin/env python3
"""
Test script for the MonitoringAgentSystem class
"""

import os
from agent_system import MonitoringAgentSystem
from monitoring_tools import create_monitoring_tools


def main():
    # Get API keys from environment variables
    openai_api_key = os.getenv("OPENAI_API_KEY", "")
    anthropic_api_key = os.getenv("ANTHROPIC_API_KEY", "")
    
    # Initialize the agent system
    agent_system = MonitoringAgentSystem(
        openai_api_key=openai_api_key,
        anthropic_api_key=anthropic_api_key,
        knowledge_base_path="./knowledge",
        qdrant_url="http://localhost:6333",  # Use localhost instead of Docker service name
        collection_name="monitoring_knowledge"
    )
    
    # Test creating monitoring tools
    try:
        print("Testing create_monitoring_tools function...")
        tools = create_monitoring_tools(agent_system.document_store)
        print(f"Successfully created {len(tools)} tools:")
        for tool in tools:
            print(f"  - {tool.name}: {tool.description}")
        print("Test passed!")
    except Exception as e:
        print(f"Error creating monitoring tools: {str(e)}")
    
    # Test querying the document store
    try:
        print("\nTesting document store query...")
        query = "What are common causes of high CPU usage?"
        print(f"Query: {query}")
        response = agent_system.query(query)
        print(f"Response: {response}")
        print("Test passed!")
    except Exception as e:
        print(f"Error querying document store: {str(e)}")
    
    # You could add more tests here if needed

if __name__ == "__main__":
    main()
