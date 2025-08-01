from crewai import Agent, Task, Crew, Process
import os
import json
from datetime import datetime
from typing import Dict, List, Any

from llamaindex_qdrant import DocumentStore
from monitoring_tools import create_monitoring_tools

class MonitoringAgentSystem:
    def __init__(self, 
                 openai_api_key: str = None, 
                 anthropic_api_key: str = None,
                 knowledge_base_path: str = "./knowledge",
                 knowledge_refresh_interval: int = 3600,
                 qdrant_url: str = "http://qdrant:6333",
                 qdrant_api_key: str = None,
                 collection_name: str = "monitoring_knowledge"):
        """Initialize the monitoring agent system
        
        Args:
            openai_api_key: OpenAI API key
            anthropic_api_key: Anthropic API key
            knowledge_base_path: Path to knowledge base directory
            knowledge_refresh_interval: How often to refresh knowledge base (seconds)
            qdrant_url: URL of the Qdrant server
            qdrant_api_key: API key for Qdrant (if needed)
            collection_name: Name of the Qdrant collection
        """
        # Set API keys
        if openai_api_key:
            os.environ["OPENAI_API_KEY"] = openai_api_key
        if anthropic_api_key:
            os.environ["ANTHROPIC_API_KEY"] = anthropic_api_key
            
        self.knowledge_base_path = knowledge_base_path
        self.knowledge_refresh_interval = knowledge_refresh_interval
        self.last_refresh_time = 0
        
        # Initialize document store
        self.document_store = DocumentStore(
            collection_name=collection_name,
            documents_dir=knowledge_base_path
        )
        
        # Set environment variables for Qdrant
        os.environ["QDRANT_URL"] = qdrant_url
        if qdrant_api_key:
            os.environ["QDRANT_API_KEY"] = qdrant_api_key
        
        # Initialize the document store
        self._setup_document_store()
        
    def _setup_document_store(self, force_refresh=False):
        """Set up or refresh the document store"""
        current_time = datetime.now().timestamp()
        
        # Only refresh if enough time has passed or force refresh is requested
        if (force_refresh or 
            current_time - self.last_refresh_time > self.knowledge_refresh_interval):
            
            try:
                # Initialize the document store
                self.document_store.initialize(force_reload=force_refresh)
                self.last_refresh_time = current_time
                return True
            except Exception as e:
                print(f"Error setting up document store: {str(e)}")
                return False
        return True
        
    def create_agents(self):
        """Create all the required agents for the monitoring system"""
        # Make sure document store is set up
        self._setup_document_store()
        
        # Create monitoring tools
        monitoring_tools = create_monitoring_tools(self.document_store)
        
        # Create Anomaly Detection Agent
        anomaly_detector = Agent(
            role="Anomaly Detection Specialist",
            goal="Identify anomalies in system metrics and determine their severity and impact",
            backstory="You're an expert at analyzing system metrics and detecting unusual patterns that indicate potential issues before they become critical failures.",
            verbose=True,
            allow_delegation=True,
            tools=monitoring_tools
        )
        
        # Create Root Cause Analysis Agent
        root_cause_analyzer = Agent(
            role="Root Cause Analyst",
            goal="Determine the underlying cause of detected anomalies",
            backstory="You're a specialized diagnostician who can trace system issues back to their source by analyzing patterns and correlations across multiple metrics and logs.",
            verbose=True,
            allow_delegation=True,
            tools=monitoring_tools
        )
        
        # Create Remediation Advisor Agent
        remediation_advisor = Agent(
            role="Remediation Advisor",
            goal="Provide actionable recommendations to address detected issues",
            backstory="You're a seasoned operations expert who knows the best practices for addressing system issues while minimizing impact on users and maintaining system stability.",
            verbose=True,
            allow_delegation=True,
            tools=monitoring_tools
        )
        
        # Create Communicator Agent
        communicator = Agent(
            role="Technical Communicator",
            goal="Synthesize findings and recommendations into clear, concise reports",
            backstory="You're skilled at translating complex technical information into clear, actionable insights that both technical and non-technical stakeholders can understand.",
            verbose=True,
            allow_delegation=False,
            tools=monitoring_tools
        )
        
        return {
            "anomaly_detector": anomaly_detector,
            "root_cause_analyzer": root_cause_analyzer,
            "remediation_advisor": remediation_advisor,
            "communicator": communicator
        }
    
    def analyze_metrics(self, metrics_data: List[Dict[str, Any]]):
        """Analyze metrics and return insights
        
        Args:
            metrics_data: List of metric data points
            
        Returns:
            Dict with analysis results
        """
        # Create agents
        agents = self.create_agents()
        
        # Format metrics for human-readable input
        metrics_str = json.dumps(metrics_data, indent=2)
        
        # Define tasks
        detect_task = Task(
            description=f"Analyze the following metrics and identify any anomalies or unusual patterns. Focus on values that deviate significantly from expected ranges or show concerning trends.\n\nMETRICS DATA:\n{metrics_str}",
            agent=agents["anomaly_detector"],
            expected_output="A detailed description of any anomalies found, including the specific metrics affected, the nature of the anomaly, and the potential severity."
        )
        
        analyze_task = Task(
            description="Based on the anomalies identified, determine the most likely root causes. Consider common failure patterns, system dependencies, and any relevant historical incidents from the knowledge base.",
            agent=agents["root_cause_analyzer"],
            expected_output="A ranked list of potential root causes for the observed anomalies, with supporting evidence and confidence levels for each hypothesis.",
            context=[detect_task]
        )
        
        remediate_task = Task(
            description="Develop a detailed remediation plan for the identified issues. Include immediate mitigation steps as well as longer-term solutions to prevent recurrence.",
            agent=agents["remediation_advisor"],
            expected_output="A step-by-step remediation plan with both immediate actions and strategic recommendations to address the root causes.",
            context=[detect_task, analyze_task]
        )
        
        report_task = Task(
            description="Create a comprehensive incident report that summarizes the anomalies detected, their root causes, and the recommended remediation steps. The report should be concise but thorough, suitable for both technical and management audiences.",
            agent=agents["communicator"],
            expected_output="A well-structured incident report with executive summary, technical details, and actionable recommendations.",
            context=[detect_task, analyze_task, remediate_task]
        )
        
        # Create crew
        crew = Crew(
            agents=list(agents.values()),
            tasks=[detect_task, analyze_task, remediate_task, report_task],
            verbose=True,
            process=Process.sequential
        )
        
        # Execute tasks
        result = crew.kickoff()
        
        return {
            "report": result,
            "timestamp": datetime.now().isoformat()
        }
        
    def force_knowledge_refresh(self):
        """Force a refresh of the knowledge base"""
        return self._setup_document_store(force_refresh=True)
        
    def query(self, query_text, top_k=5):
        """Query the document store
        
        Args:
            query_text: The query text
            top_k: Number of results to return
            
        Returns:
            The query result
        """
        return self.document_store.query(query_text, similarity_top_k=top_k)
