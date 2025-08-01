#!/usr/bin/env python3
"""
Knowledge Ingestion Script

This script ingests documents from the knowledge directory into the document store.
It can be used to initially populate the document store or to refresh it with new documents.
"""

import os
import argparse
import sys
from pathlib import Path
from dotenv import load_dotenv

# Add the current directory to the path so we can import our modules
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Import our document store
from llamaindex_qdrant import DocumentStore


def fetch_env() -> Path | None:
    """Find and load the .env file from possible locations."""
    possible_paths = [
        Path('.env'),  # Current directory
        Path('/app/.env'),  # App directory
        Path(__file__).parent / '.env',  # Same directory as the script
        Path(__file__).resolve().parent.parent / '.env'  # Parent directory
    ]
    env_found = False
    exist_env_path = None
    for env_path in possible_paths:
        if env_path.exists():
            # Load the .env file
            env_found = True
            exist_env_path = env_path
            break
    if not env_found:
        print(f"Warning: .env file not found in any of the expected locations")
    return exist_env_path


def ingest_knowledge(knowledge_dir="./knowledge", collection_name="monitoring_knowledge", 
                     force_refresh=False, verbose=False):
    """
    Ingest knowledge from the specified directory into the document store.
    
    Args:
        knowledge_dir: Path to the knowledge directory
        collection_name: Name of the Qdrant collection
        force_refresh: Whether to force a refresh of the document store
        verbose: Whether to print verbose output
    
    Returns:
        True if ingestion was successful, False otherwise
    """
    # Check if the knowledge directory exists
    if not os.path.exists(knowledge_dir):
        print(f"Error: Knowledge directory '{knowledge_dir}' does not exist")
        return False
    
    # Print information about the knowledge directory
    if verbose:
        print(f"Ingesting knowledge from '{knowledge_dir}'")
        print("Directory structure:")
        for root, dirs, files in os.walk(knowledge_dir):
            level = root.replace(knowledge_dir, '').count(os.sep)
            indent = ' ' * 4 * level
            print(f"{indent}{os.path.basename(root)}/")
            sub_indent = ' ' * 4 * (level + 1)
            for file in files:
                print(f"{sub_indent}{file}")
    
    # Initialize the document store
    try:
        document_store = DocumentStore(
            collection_name=collection_name,
            documents_dir=knowledge_dir
        )
        
        # Initialize the document store (this will load and index the documents)
        document_store.initialize(force_reload=force_refresh)
        
        print(f"Successfully ingested knowledge into collection '{collection_name}'")
        return True
    except Exception as e:
        print(f"Error ingesting knowledge: {str(e)}")
        return False


def main():
    """Main function to parse arguments and ingest knowledge."""
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Ingest knowledge into the document store")
    parser.add_argument("--knowledge-dir", default="./knowledge", 
                        help="Path to the knowledge directory")
    parser.add_argument("--collection-name", default="monitoring_knowledge", 
                        help="Name of the Qdrant collection")
    parser.add_argument("--force-refresh", action="store_true", 
                        help="Force a refresh of the document store")
    parser.add_argument("--verbose", action="store_true", 
                        help="Print verbose output")
    args = parser.parse_args()
    
    # Load environment variables
    env_path = fetch_env()
    if env_path:
        load_dotenv(dotenv_path=env_path)
    
    # Ingest knowledge
    success = ingest_knowledge(
        knowledge_dir=args.knowledge_dir,
        collection_name=args.collection_name,
        force_refresh=args.force_refresh,
        verbose=args.verbose
    )
    
    # Exit with appropriate status code
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
