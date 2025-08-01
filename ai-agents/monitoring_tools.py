from typing import Any

from crewai.tools import BaseTool
from pydantic import BaseModel, Field


# Create schema classes for tool arguments
class QuerySchema(BaseModel):
    query: str = Field(description="The query to search for in the document store")


class AnomalySchema(BaseModel):
    metrics_data: str = Field(description="JSON string containing metrics data to analyze for anomalies")


class RootCauseSchema(BaseModel):
    anomaly_description: str = Field(description="Description of the anomaly to analyze for root causes")


class RemediationSchema(BaseModel):
    issue_description: str = Field(description="Description of the issue to provide remediation steps for")


class MonitoringQueryTool(BaseTool):
    """Tool for querying the monitoring knowledge base."""

    name: str = "monitoring_query"
    description: str = "Useful for searching the knowledge base for information about system behavior, past incidents, and best practices"
    document_store: Any = Field(description="Document store for querying")
    args_schema: type[BaseModel] = QuerySchema

    def _run(self, query: str) -> str:
        """Run the tool to search for monitoring information."""
        try:
            response = self.document_store.query(query)
            return f"Search results for '{query}':\n\n{response}"
        except Exception as e:
            return f"Error searching for '{query}': {str(e)}"


class AnomalyDetectionTool(BaseTool):
    """Tool for detecting anomalies in system metrics."""

    name: str = "anomaly_detection"
    description: str = "Useful for analyzing metrics data to identify anomalies and unusual patterns"
    document_store: Any = Field(description="Document store for querying")
    args_schema: type[BaseModel] = AnomalySchema

    def _run(self, metrics_data: str) -> str:
        """Run the tool to detect anomalies in metrics data."""
        try:
            query = f"Analyze the following metrics data to identify anomalies and unusual patterns: {metrics_data}"
            response = self.document_store.query(query)
            return f"Anomaly detection results:\n\n{response}"
        except Exception as e:
            return f"Error detecting anomalies: {str(e)}"


class RootCauseAnalysisTool(BaseTool):
    """Tool for analyzing root causes of detected anomalies."""

    name: str = "root_cause_analysis"
    description: str = "Useful for determining the underlying causes of detected anomalies"
    document_store: Any = Field(description="Document store for querying")
    args_schema: type[BaseModel] = RootCauseSchema

    def _run(self, anomaly_description: str) -> str:
        """Run the tool to analyze root causes."""
        try:
            query = f"Determine the most likely root causes for the following anomaly: {anomaly_description}"
            response = self.document_store.query(query)
            return f"Root cause analysis results:\n\n{response}"
        except Exception as e:
            return f"Error analyzing root causes: {str(e)}"


class RemediationTool(BaseTool):
    """Tool for providing remediation steps for detected issues."""

    name: str = "remediation"
    description: str = "Useful for providing actionable recommendations to address detected issues"
    document_store: Any = Field(description="Document store for querying")
    args_schema: type[BaseModel] = RemediationSchema

    def _run(self, issue_description: str) -> str:
        """Run the tool to provide remediation steps."""
        try:
            query = f"Provide remediation steps for the following issue: {issue_description}"
            response = self.document_store.query(query)
            return f"Remediation recommendations:\n\n{response}"
        except Exception as e:
            return f"Error providing remediation steps: {str(e)}"


def create_monitoring_tools(document_store):
    """Create and return the monitoring tools with the document store injected."""

    # Create instances of each tool with the document store
    query_tool = MonitoringQueryTool(document_store=document_store)
    anomaly_tool = AnomalyDetectionTool(document_store=document_store)
    root_cause_tool = RootCauseAnalysisTool(document_store=document_store)
    remediation_tool = RemediationTool(document_store=document_store)

    return [query_tool, anomaly_tool, root_cause_tool, remediation_tool]
