# Session 2: Core Components

## Distributed Monitoring Architecture (30 min)

### Introduction to Prometheus
- Time-series database for metrics collection
- Pull-based architecture
- Key components:
  - Scrapers: Collect metrics from endpoints
  - Storage: Time-series database
  - PromQL: Query language
  - Alertmanager: Handles alerts

**In Simple Words:**
Think of Prometheus like a health monitor for your computer systems. Just as a doctor regularly checks your vital signs (heart rate, blood pressure, etc.), Prometheus regularly checks your system's vital signs (CPU usage, memory, response times). Instead of waiting for you to send health updates, it actively goes out and collects this information on a schedule, stores it in a special database, and can alert you when something doesn't look right.

```mermaid
graph TD
    subgraph "Prometheus Architecture"
        A[Prometheus Server] -->|Scrapes metrics from| B[Application/Service]
        A -->|Scrapes metrics from| C[Other Systems]
        A -->|Stores data in| D[Time-Series Database]
        A -->|Executes| E[PromQL Queries]
        A -->|Sends alerts to| F[Alertmanager]
        F -->|Notifies| G[Email/Slack/PagerDuty]
        H[Grafana] -->|Queries| A
    end
```

### Prometheus Metrics Types
- **Counter**: Cumulative metric that only increases (e.g., request count)
- **Gauge**: Metric that can go up and down (e.g., memory usage)
- **Histogram**: Samples observations and counts them in configurable buckets
- **Summary**: Similar to histogram, but calculates quantiles over a sliding time window

**In Simple Words:**
Prometheus uses different types of measurements, like different instruments in a doctor's office:

```mermaid
graph TD
    subgraph "Prometheus Metrics Types"
        A[Counter] -->|"Like an odometer in a car"| A1[Only goes up, never down]
        A1 -->|"Examples"| A2[Total requests, errors, completed tasks]
        
        B[Gauge] -->|"Like a fuel gauge"| B1[Can go up and down]
        B1 -->|"Examples"| B2[Memory usage, CPU usage, active connections]
        
        C[Histogram] -->|"Like sorting test scores into grade ranges"| C1[Groups measurements into buckets]
        C1 -->|"Examples"| C2[Response time ranges, request size ranges]
        
        D[Summary] -->|"Like calculating class percentiles"| D1[Tracks average and percentiles over time]
        D1 -->|"Examples"| D2[90% of requests complete within X seconds]
    end
```

### Kafka Streaming Basics
- Distributed event streaming platform
- Key components:
  - Topics: Categories for message streams
  - Producers: Send messages to topics
  - Consumers: Read messages from topics
  - Brokers: Kafka server instances
  - Consumer Groups: Load balancing across consumers

**In Simple Words:**
Kafka works like a super-efficient postal service for computer data. Imagine a post office with different mailboxes (topics) for different types of mail. Some people (producers) drop off mail into these mailboxes. The post office (brokers) organizes and stores this mail. Other people (consumers) come to collect mail from specific mailboxes they're interested in. Multiple people can read the same mail without removing it, and groups of people (consumer groups) can divide up the work of processing mail from a single mailbox.

```mermaid
graph TD
    subgraph "Kafka Architecture"
        A[Producer 1] -->|Sends messages to| C[Topic A]
        B[Producer 2] -->|Sends messages to| C
        B -->|Sends messages to| D[Topic B]
        
        subgraph "Kafka Cluster"
            C -->|Stored in| E[Broker 1]
            D -->|Stored in| F[Broker 2]
            E <-->|Replication| F
        end
        
        C -->|Read by| G[Consumer 1]
        D -->|Read by| H[Consumer 2]
        D -->|Read by| I[Consumer 3]
        
        subgraph "Consumer Group"
            H
            I
        end
    end
```

### System Metrics Collection
- Framework-agnostic instrumentation
- Middleware integration
- Custom metrics creation
- Exporters for different services

**In Simple Words:**
Collecting metrics from your system is like installing various sensors throughout your house to monitor temperature, electricity usage, water flow, and security. These sensors can be added to any part of your house (your application) regardless of how it was built. Some sensors come built-in with appliances (middleware integration), some you install yourself (custom metrics), and some are special adapters that let older appliances connect to your monitoring system (exporters).

```mermaid
graph TD
    subgraph "System Metrics Collection"
        A[Your Application] -->|Built-in metrics| E[Prometheus]
        
        B[Database] -->|Database Exporter| E
        C[Web Server] -->|Web Server Exporter| E
        D[Operating System] -->|Node Exporter| E
        
        F[Custom Business Logic] -->|Custom metrics| A
        G[API Middleware] -->|Request metrics| A
        H[Authentication Service] -->|Auth metrics| A
    end
```

### Prometheus to Kafka Bridge
```python
class PrometheusToKafkaBridge:
    def __init__(self, prometheus_url, kafka_brokers, topic="prom_metrics",
                 polling_interval=60, batch_size=100):
        self.prometheus_url = prometheus_url
        self.kafka_brokers = kafka_brokers
        self.topic = topic
        self.polling_interval = polling_interval
        self.batch_size = batch_size
        self.prom = None
        self.producer = None
        
    def connect(self):
        """Establish connections to Prometheus and Kafka with retries"""
        try:
            self.prom = PrometheusConnect(url=self.prometheus_url, disable_ssl=True)
            self.producer = KafkaProducer(
                bootstrap_servers=self.kafka_brokers,
                value_serializer=lambda v: json.dumps(v).encode('utf-8'),
                retries=5,
                acks='all'
            )
            return True
        except Exception as e:
            logging.error(f"Connection error: {str(e)}")
            return False
```

**In Simple Words:**
This code creates a bridge that connects Prometheus (our health monitoring system) to Kafka (our mail delivery system). It's like having a person who regularly checks all the health sensors in your house and then sends reports through the mail to other people who need to know about the health of your house. The bridge:
- Knows where to find Prometheus and Kafka
- Decides how often to check for new metrics (polling_interval)
- Determines how many metrics to send at once (batch_size)
- Has methods to connect to both systems

```mermaid
sequenceDiagram
    participant P as Prometheus
    participant B as PrometheusToKafkaBridge
    participant K as Kafka
    participant C as Consumers
    
    Note over B: Initializes with configuration
    B->>P: Connect to Prometheus
    B->>K: Connect to Kafka
    
    loop Every polling_interval seconds
        B->>P: Query for metrics
        P-->>B: Return current metrics
        B->>B: Process and batch metrics
        B->>K: Send metrics batch to topic
        K-->>C: Metrics available for consumers
    end
```

## Knowledge Management with LlamaIndex (45 min)

### Understanding Vector Databases
- Purpose: Efficient similarity search for embeddings
- How they work: Index vectors for fast nearest-neighbor search
- Comparison to traditional databases
- Popular options: Qdrant, Pinecone, Weaviate, Milvus

**In Simple Words:**
Imagine a library where books are organized not by author or title, but by how similar their content is. Books about similar topics would be placed near each other on the shelves. A vector database works the same way for AI - it converts text, images, or other data into special "coordinates" (vectors) and organizes them so that similar items are "near" each other. This makes it very fast to find information that's similar to what you're looking for, even if it doesn't contain the exact words you searched for.

```mermaid
graph TD
    subgraph "Vector Database Concept"
        A[Text Documents] -->|Convert to vectors| B[Embedding Model]
        B -->|Store vectors| C[Vector Database]
        D[Query Text] -->|Convert to vector| B
        B -->|Find similar vectors| C
        C -->|Return similar documents| E[Search Results]
    end
    
    subgraph "Traditional vs. Vector DB"
        F[Traditional DB] -->|"Exact match search:<br>WHERE title = 'monitoring'"| F1[Only exact matches]
        G[Vector DB] -->|"Similarity search:<br>Find content similar to 'system monitoring'"| G1[Semantically similar results]
    end
```

### Document Ingestion and Indexing
- Document loading and chunking
- Text embedding generation
- Vector storage and indexing
- Metadata management

**In Simple Words:**
Getting documents into a vector database is like preparing books for a library:
1. First, you break large books into chapters or sections (chunking)
2. Then, you create a special "essence" of each section that captures its meaning (embedding)
3. Next, you organize these essences in a way that makes them easy to find (indexing)
4. Finally, you keep track of information about each section, like which book it came from (metadata)

```mermaid
flowchart TD
    A[Documents] -->|Load| B[Raw Text]
    B -->|Split into chunks| C[Text Chunks]
    C -->|Generate embeddings| D[Vector Embeddings]
    D -->|Store in database| E[Vector Index]
    
    C -->|Extract information| F[Metadata]
    F -->|Store with vectors| E
    
    G[Document 1] -->|Chunk 1| H[Chunk 1.1]
    G -->|Chunk 2| I[Chunk 1.2]
    G -->|Chunk 3| J[Chunk 1.3]
    
    H -->|Embed| K["Vector [0.1, 0.2, ...]"]
    I -->|Embed| L["Vector [0.3, 0.5, ...]"]
    J -->|Embed| M["Vector [0.7, 0.1, ...]"]
```

### Qdrant Vector Store
- High-performance vector similarity search
- Filtering capabilities
- Scalable architecture
- Python client integration

**In Simple Words:**
Qdrant is like a specialized library with super-fast librarians who can instantly find books similar to the one you're interested in. It not only organizes books by similarity but also lets you filter by other properties - like "only show me science fiction books published after 2010 that are similar to this book." It's designed to handle millions of books efficiently and works well with Python, making it easy for our code to use.

```mermaid
graph TD
    subgraph "Qdrant Vector Store"
        A[Your Application] -->|"Store vectors<br>(Python Client)"| B[Qdrant Server]
        A -->|"Search similar vectors<br>(Python Client)"| B
        
        B -->|"Contains"| C[Collections]
        C -->|"Contain"| D[Points]
        D -->|"Have"| E[Vector Data]
        D -->|"Have"| F[Payload/Metadata]
        
        G[Search Query] -->|"Find similar to [0.1, 0.2, ...]<br>WHERE category = 'monitoring'"| B
        B -->|"Returns"| H[Similar Points]
    end
```

### LlamaIndex Integration
```python
class QdrantKnowledgeBase:
    def __init__(self, 
                 collection_name="monitoring_knowledge",
                 qdrant_url="http://qdrant:6333",
                 qdrant_api_key=None,
                 embedding_dim=1536,
                 knowledge_dir="./knowledge"):
        self.collection_name = collection_name
        self.qdrant_url = qdrant_url
        self.qdrant_api_key = qdrant_api_key
        self.embedding_dim = embedding_dim
        self.knowledge_dir = knowledge_dir
        self.client = None
        self.index = None
        
        # Set up Qdrant client
        self._setup_qdrant_client()
```

**In Simple Words:**
This code creates a special knowledge base using Qdrant (our similarity library) and LlamaIndex (a tool that helps manage knowledge for AI). It's like setting up a specialized research assistant who has access to a library of information about monitoring systems. The knowledge base:
- Has a name for its collection of information
- Knows where to find the Qdrant server
- Has security credentials if needed
- Knows how detailed the "essence" of each document should be (embedding_dim)
- Knows where to find the documents to learn from (knowledge_dir)

```mermaid
graph TD
    subgraph "LlamaIndex + Qdrant Integration"
        A[Knowledge Documents] -->|Processed by| B[LlamaIndex]
        B -->|Generates embeddings| C[Embedding Model]
        C -->|Stores vectors in| D[Qdrant Vector Store]
        
        E[User Query] -->|Processed by| B
        B -->|Retrieves relevant context from| D
        B -->|Generates response using| F[LLM]
        F -->|Returns| G[Answer with context]
    end
```

### Query Processing
- Query embedding generation
- Vector similarity search
- Result ranking and filtering
- Response generation

**In Simple Words:**
When you ask a question, the system follows these steps:
1. Converts your question into the same kind of "essence" (vector) as the stored documents
2. Finds documents with similar "essences" to your question
3. Sorts these documents by how relevant they are to your question
4. Uses the most relevant documents to help generate a helpful answer

```mermaid
flowchart TD
    A[User Query] -->|Convert to vector| B[Query Embedding]
    B -->|Search similar vectors| C[Vector Database]
    C -->|Return similar documents| D[Relevant Documents]
    D -->|Rank by relevance| E[Ranked Results]
    E -->|Filter by criteria| F[Filtered Results]
    F -->|Provide context to| G[LLM]
    G -->|Generate| H[Final Response]
```

## Hands-on: Building the Monitoring Pipeline (45 min)

### Setting up Prometheus Exporters
- Creating a custom exporter class
- Implementing metric collection
- Exposing metrics endpoint
- Configuring Prometheus to scrape metrics

**In Simple Words:**
Setting up Prometheus exporters is like installing sensors in your house:
1. First, you create a special device (exporter class) that knows how to measure things
2. Then, you program it to collect specific measurements (metric collection)
3. Next, you make sure it has a way to share these measurements when asked (metrics endpoint)
4. Finally, you tell your monitoring system where to find these sensors (Prometheus configuration)

```mermaid
graph TD
    subgraph "Prometheus Exporter Setup"
        A[Your Application] -->|"Includes"| B[Custom Exporter Class]
        B -->|"Defines"| C[Metrics to Collect]
        B -->|"Exposes"| D[HTTP Endpoint /metrics]
        
        E[Prometheus Server] -->|"Scrapes"| D
        E -->|"Stores"| F[Time-Series Database]
        
        G[prometheus.yml] -->|"Configures"| E
    end
```

### Implementing Kafka Producers/Consumers
- Setting up Kafka producer for metrics
- Implementing batch processing
- Error handling and retries
- Monitoring Kafka performance

**In Simple Words:**
Setting up Kafka producers and consumers is like creating a reliable mail delivery system:
1. The producer is like a person who collects and sends letters (metrics)
2. Batch processing is like bundling multiple letters into one package for efficiency
3. Error handling and retries ensure that if a letter can't be delivered, it will be tried again
4. Monitoring the system itself helps ensure the mail service stays reliable

```mermaid
flowchart TD
    subgraph "Kafka Producer Implementation"
        A[Application] -->|"Collects metrics"| B[Metrics Data]
        B -->|"Batches"| C[Kafka Producer]
        C -->|"Sends to"| D[Kafka Topic]
        
        C -->|"If fails"| E[Retry Logic]
        E -->|"Try again"| C
        
        F[Configuration] -->|"Sets batch size,<br>timeout, etc."| C
    end
    
    subgraph "Kafka Consumer Implementation"
        D -->|"Reads from"| G[Kafka Consumer]
        G -->|"Processes"| H[Processing Logic]
        H -->|"Stores/Analyzes"| I[Result]
        
        J[Consumer Group] -->|"Coordinates"| G
        K[Offset Management] -->|"Tracks progress"| G
    end
```

### Creating the Knowledge Base
- Organizing knowledge documents
- Building the vector index
- Testing query capabilities
- Optimizing retrieval performance

**In Simple Words:**
Creating a knowledge base is like building a specialized library:
1. First, you collect and organize important documents about your system
2. Then, you create a special index that helps find information quickly
3. Next, you test the library by asking questions and seeing if it finds good answers
4. Finally, you fine-tune the system to make it faster and more accurate

```mermaid
graph TD
    subgraph "Knowledge Base Creation"
        A[Knowledge Documents] -->|"Organize by category"| B[Structured Documents]
        B -->|"Process with"| C[LlamaIndex]
        C -->|"Create"| D[Vector Index]
        D -->|"Store in"| E[Qdrant]
        
        F[Test Queries] -->|"Evaluate"| G[Query Engine]
        G -->|"Uses"| D
        G -->|"Returns"| H[Search Results]
        
        I[Performance Analysis] -->|"Optimize"| J[Improved Index]
        J -->|"Replace"| D
    end
```

### Exercise: Complete Pipeline Integration
- Connect Prometheus exporter to application
- Stream metrics to Kafka
- Process metrics with consumer
- Query knowledge base for context

**In Simple Words:**
In this exercise, you'll connect all the pieces to create a complete monitoring system:
1. Add sensors (Prometheus exporters) to your application to collect measurements
2. Send these measurements through a delivery system (Kafka) for processing
3. Have workers (consumers) process and analyze these measurements
4. Use a smart library (knowledge base) to provide context and help understand the measurements

```mermaid
flowchart LR
    subgraph "Complete Monitoring Pipeline"
        A[Your Application] -->|"Exposes metrics"| B[Prometheus Exporter]
        B -->|"Scraped by"| C[Prometheus]
        C -->|"Metrics sent to"| D[Kafka Bridge]
        D -->|"Publishes to"| E[Kafka Topic]
        E -->|"Consumed by"| F[Metrics Consumer]
        F -->|"Analyzes with"| G[AI Agents]
        G -->|"Queries"| H[Knowledge Base]
        H -->|"Provides context"| G
        G -->|"Generates"| I[Insights & Alerts]
    end
