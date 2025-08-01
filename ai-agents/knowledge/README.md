# Monitoring Knowledge Base

This directory contains knowledge documents that are ingested into the document store for use by the AI monitoring agents. The knowledge is organized into the following categories:

## Directory Structure

- **best_practices/**: Best practices for system monitoring, performance tuning, and troubleshooting
- **incidents/**: Past incident reports, including root cause analysis and resolution steps
- **logs/**: Log analysis patterns, common error messages, and troubleshooting guides

## Adding Knowledge

To add new knowledge to the system:

1. Create a new Markdown (.md) file in the appropriate subdirectory
2. Follow the existing format and structure for consistency
3. Run the ingestion script to update the document store

## Knowledge Ingestion

Use the `ingest_knowledge.py` script to ingest the knowledge into the document store:

```bash
# From the project root directory
python ai-agents/ingest_knowledge.py
```

### Script Options

- `--knowledge-dir`: Path to the knowledge directory (default: "./knowledge")
- `--collection-name`: Name of the Qdrant collection (default: "monitoring_knowledge")
- `--force-refresh`: Force a refresh of the document store (default: false)
- `--verbose`: Print verbose output (default: false)

Example with options:

```bash
python ai-agents/ingest_knowledge.py --knowledge-dir ./custom-knowledge --collection-name custom-collection --force-refresh --verbose
```

## Document Format

Knowledge documents should be written in Markdown format. The AI system works best with well-structured documents that include:

- Clear headings and subheadings
- Concise explanations
- Examples where appropriate
- Lists and tables for structured information

## Best Practices for Knowledge Documents

1. **Be specific**: Include concrete examples, error messages, and solutions
2. **Use consistent terminology**: Maintain consistent terminology across documents
3. **Include context**: Provide enough context for the AI to understand when to apply the knowledge
4. **Update regularly**: Keep the knowledge base up-to-date with new information
5. **Cross-reference**: Reference related documents where appropriate

## Example Knowledge Types

- System architecture documentation
- Common failure modes and solutions
- Performance tuning guidelines
- Incident response procedures
- Troubleshooting guides
- Log analysis patterns
- Alert interpretation guides
