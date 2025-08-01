import os
from llama_index.core import VectorStoreIndex, SimpleDirectoryReader, Settings
from llama_index.vector_stores.qdrant import QdrantVectorStore
from llama_index.core import StorageContext
from llama_index.embeddings.openai import OpenAIEmbedding
import qdrant_client
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


class DocumentStore:
    """
    A class to manage document storage and retrieval using LlamaIndex and Qdrant.

    This class handles:
    - Initializing the Qdrant vector database (local or cloud)
    - Loading documents from a specified directory
    - Creating and managing vector embeddings
    - Providing query functionality for semantic search
    """

    def __init__(self, collection_name="monitoring_knowledge", documents_dir="./knowledge"):
        """Initialize the document store with LlamaIndex and Qdrant.

        Args:
            collection_name: Name of the Qdrant collection to store embeddings.
            documents_dir: Directory containing the documents to be indexed.
        """
        self.collection_name = collection_name
        self.documents_dir = documents_dir
        self.client = None
        self.index = None

    def initialize(self, force_reload=False):
        """Initialize the document store and load documents.

        Args:
            force_reload: If True, will reload and reindex all documents.

        Returns:
            The initialized index.
        """
        # Set up OpenAI embeddings
        embed_model = OpenAIEmbedding()
        Settings.embed_model = embed_model

        # Initialize Qdrant client (local or cloud)
        if os.getenv("QDRANT_URL") and os.getenv("QDRANT_API_KEY"):
            # Cloud Qdrant
            self.client = qdrant_client.QdrantClient(
                url=os.getenv("QDRANT_URL"),
                api_key=os.getenv("QDRANT_API_KEY"),
            )
            print("Using Qdrant Cloud instance")
        else:
            # Local Qdrant
            self.client = qdrant_client.QdrantClient(url="http://localhost:6333")
            print("Using local Qdrant instance")

        # Check if collection exists and decide whether to reload
        collections = self.client.get_collections().collections
        collection_exists = any(collection.name == self.collection_name for collection in collections)

        if not collection_exists or force_reload:
            # Delete collection if it exists and we're forcing reload
            if collection_exists and force_reload:
                self.client.delete_collection(self.collection_name)
                print(f"Deleted existing collection: {self.collection_name}")

            # Create a new vector store
            vector_store = QdrantVectorStore(
                client=self.client,
                collection_name=self.collection_name
            )

            # Create storage context
            storage_context = StorageContext.from_defaults(vector_store=vector_store)

            # Load documents
            documents = self._load_documents()
            if not documents:
                print("No documents found to index.")
                return None

            print(f"Indexing {len(documents)} documents...")

            # Create index
            self.index = VectorStoreIndex.from_documents(
                documents,
                storage_context=storage_context,
            )
            print("Documents indexed successfully.")
        else:
            # Load existing index
            print(f"Loading existing index from collection: {self.collection_name}")
            vector_store = QdrantVectorStore(
                client=self.client,
                collection_name=self.collection_name
            )
            self.index = VectorStoreIndex.from_vector_store(vector_store)

        return self.index

    def _load_documents(self):
        """Load documents from the specified directory.

        Returns:
            A list of Document objects.
        """
        if not os.path.exists(self.documents_dir):
            os.makedirs(self.documents_dir)
            print(f"Created documents directory: {self.documents_dir}")
            # Create a sample document if directory is empty
            with open(os.path.join(self.documents_dir, "sample_monitoring.txt"), "w") as f:
                f.write("This is a sample document for the monitoring system. It contains information about system behavior and best practices.")
            print("Created a sample document.")

        # Load all documents from the directory
        print(f"Loading documents from {self.documents_dir}...")
        documents = SimpleDirectoryReader(self.documents_dir).load_data()
        return documents

    def query(self, query_text, similarity_top_k=3):
        """Query the document store for relevant information.

        Args:
            query_text: Text query to search for.
            similarity_top_k: Number of top results to return.

        Returns:
            A response object from the query engine.
        """
        if not self.index:
            raise ValueError("Document store is not initialized. Call initialize() first.")

        query_engine = self.index.as_query_engine(similarity_top_k=similarity_top_k)
        response = query_engine.query(query_text)

        return response

    def ingest(self, document):
        """Ingest a new document into the document store.

        Args:
            document: The document to ingest.
        """
        if not self.index:
            raise ValueError("Document store is not initialized. Call initialize() first.")

        self.index.ingest(document)
        
    def get_query_engine(self, similarity_top_k=3):
        """Get a query engine for the document store.
        
        Args:
            similarity_top_k: Number of top results to return.
            
        Returns:
            A query engine for the document store.
        """
        if not self.index:
            raise ValueError("Document store is not initialized. Call initialize() first.")
            
        return self.index.as_query_engine(similarity_top_k=similarity_top_k)
