from prometheus_api_client import PrometheusConnect
from kafka import KafkaProducer, KafkaAdminClient
from kafka.admin import NewTopic
from kafka.errors import TopicAlreadyExistsError, NoBrokersAvailable
import json
import time
import logging
import backoff
import os

# Set up logging
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('prometheus_to_kafka')


class PrometheusToKafkaBridge:
    def __init__(self, prometheus_url, kafka_brokers, topic="prom_metrics",
                 polling_interval=60, batch_size=100, max_wait_time=None):
        self.prometheus_url = prometheus_url
        self.kafka_brokers = kafka_brokers
        self.topic = topic
        self.polling_interval = polling_interval
        self.batch_size = batch_size
        self.max_wait_time = max_wait_time  # If None, will wait indefinitely for metrics
        self.prom = None
        self.producer = None
        self.health_check_interval = 60  # How often to do a full health check in seconds

    def ensure_topic_exists(self, kafka_brokers, topic_name, num_partitions=3, replication_factor=1):
        """Check if the topic exists and create it if it doesn't"""
        try:
            logger.info(f"Checking if topic '{topic_name}' exists using broker: {kafka_brokers}")

            # Ensure we're not using any Docker hostnames
            if "kafka:" in kafka_brokers and not os.environ.get("RUNNING_IN_DOCKER"):
                fixed_brokers = kafka_brokers.replace("kafka:", "localhost:")
                logger.info(f"Fixed broker address for topic creation: {fixed_brokers}")
                kafka_brokers = fixed_brokers

            # Create AdminClient with short timeouts to fail faster if there's an issue
            admin_client = KafkaAdminClient(
                bootstrap_servers=kafka_brokers,
                client_id='prometheus-to-kafka-admin',
                request_timeout_ms=10000,
                connections_max_idle_ms=10000
            )

            try:
                # Get topics
                existing_topics = admin_client.list_topics()

                # Check if topic exists
                if topic_name in existing_topics:
                    logger.info(f"Topic '{topic_name}' already exists")
                    admin_client.close()
                    return True

                # Topic doesn't exist, create it
                logger.info(f"Topic '{topic_name}' does not exist. Creating it...")

                # Create topic
                new_topics = [NewTopic(
                    name=topic_name,
                    num_partitions=num_partitions,
                    replication_factor=replication_factor
                )]

                try:
                    admin_client.create_topics(new_topics)
                    logger.info(f"Topic '{topic_name}' created successfully")
                except TopicAlreadyExistsError:
                    logger.info(f"Topic '{topic_name}' already exists")

                admin_client.close()
                return True
            except NoBrokersAvailable:
                logger.warning(
                    "No brokers available. This is normal if you're running outside Docker and Kafka is inside Docker.")
                logger.warning(
                    "Will continue without topic creation - the topic should be created automatically when we send data.")
                return True

        except Exception as e:
            logger.error(f"Error ensuring topic exists: {str(e)}")
            logger.warning(
                "Will continue without topic creation - the topic should be created automatically when we send data.")
            return True  # Return True to continue trying to produce messages

    def connect(self):
        """Establish connections to Prometheus and Kafka with retries"""
        try:
            logger.info(f"Connecting to Prometheus at {self.prometheus_url}")
            self.prom = PrometheusConnect(url=self.prometheus_url, disable_ssl=True)

            # Make sure we're always using the right hostname format based on environment
            original_brokers = self.kafka_brokers

            # Handle Docker vs local execution - replace all instances of "kafka:" with "localhost:"
            if not os.environ.get("RUNNING_IN_DOCKER"):
                self.kafka_brokers = self.kafka_brokers.replace("kafka:", "localhost:")
                if original_brokers != self.kafka_brokers:
                    logger.info(
                        f"Detected local execution, using {self.kafka_brokers} instead of the original Docker hostname")

            # Force localhost if not in Docker and no localhost in brokers
            if not os.environ.get("RUNNING_IN_DOCKER") and "localhost" not in self.kafka_brokers:
                # Extract port if present
                if ":" in self.kafka_brokers:
                    port = self.kafka_brokers.split(":")[-1]
                    self.kafka_brokers = f"localhost:{port}"
                else:
                    self.kafka_brokers = "localhost:9092"
                logger.info(f"Forced local connectivity: {self.kafka_brokers}")

            logger.info(f"Connecting to Kafka at {self.kafka_brokers}")

            # Ensure the topic exists
            self.ensure_topic_exists(self.kafka_brokers, self.topic)

            # Configure Kafka Producer with basic settings
            # Close old producer if it exists
            if self.producer is not None:
                try:
                    self.producer.flush()
                    self.producer.close()
                except Exception as e:
                    logger.warning(f"Failed to close producer: {str(e)}")

            # Create a new producer with configuration for DNS issues
            logger.info(f"Creating Kafka producer with bootstrap servers: {self.kafka_brokers}")
            self.producer = KafkaProducer(
                bootstrap_servers=self.kafka_brokers,
                acks='all',
                retries=5,
                retry_backoff_ms=500,
                request_timeout_ms=30000,  # Increase timeout for better error handling
                client_id='prometheus-to-kafka-producer',
                value_serializer=lambda v: json.dumps(v).encode('utf-8'),
                reconnect_backoff_ms=1000,  # Add backoff for reconnection attempts
                reconnect_backoff_max_ms=10000  # Maximum backoff time
            )

            logger.info("Successfully connected to Kafka")
            return True
        except Exception as e:
            logger.error(f"Connection error: {str(e)}")
            return False

    @backoff.on_exception(backoff.expo, Exception, max_tries=5)
    def query_prometheus(self, query='{__name__!=""}'):
        """Query Prometheus with exponential backoff retry"""
        try:
            logger.info(f"Querying Prometheus: {query}")
            results = self.prom.custom_query(query)

            # Ensure results is not None before checking its length
            if results is None:
                logger.warning("Prometheus returned None instead of empty list. Converting to empty list.")
                return []

            # Check if results are empty
            if not results:
                logger.debug(
                    "Prometheus returned empty results. Prometheus server may need more time to collect metrics.")
                return []

            # Sanitize results - remove any None values or elements that might cause issues
            sanitized_results = []
            for item in results:
                if item is None:
                    continue

                # Ensure the item is a dictionary or convert it to one
                if not isinstance(item, dict):
                    try:
                        # Try to convert to dict if possible
                        item = dict(item)
                    except (TypeError, ValueError):
                        logger.warning(f"Skipping non-dict metric: {type(item)}")
                        continue

                # Check for any None values in the item and replace them with safe defaults
                sanitized_item = {}
                for k, v in item.items():
                    if v is None:
                        if k == 'value':
                            sanitized_item[k] = 0
                        else:
                            sanitized_item[k] = ''
                    else:
                        sanitized_item[k] = v

                sanitized_results.append(sanitized_item)

            logger.info(f"Retrieved {len(sanitized_results)} metrics from Prometheus (after sanitization)")
            return sanitized_results

        except Exception as e:
            logger.error(f"Prometheus query error: {str(e)}")
            # Don't immediately give up on query errors - Prometheus might be starting up
            if "connection" in str(e).lower() or "refused" in str(e).lower():
                logger.warning(
                    "Connection issue with Prometheus. It may be starting up or experiencing temporary issues.")
            raise

    def send_to_kafka(self, metrics):
        """Send metrics to Kafka topic"""
        try:
            # Split metrics into batches to avoid large messages
            sent_count = 0
            batch_futures = []

            for i in range(0, len(metrics), self.batch_size):
                batch = metrics[i:i + self.batch_size]
                # Produce message to topic (serialization is handled by KafkaProducer config)
                try:
                    future = self.producer.send(self.topic, batch)
                    batch_futures.append(future)
                    sent_count += len(batch)
                except Exception as e:
                    # Handle specific send errors
                    logger.error(f"Error sending batch: {str(e)}")
                    # If we get DNS errors at this point, try to reconnect with corrected settings
                    if "nodename nor servname provided" in str(e) or "DNS lookup failed" in str(e):
                        logger.warning("DNS lookup issue detected. Attempting to reconnect with corrected settings.")
                        if self.connect():
                            # Retry this batch
                            logger.info("Reconnected successfully, retrying batch")
                            future = self.producer.send(self.topic, batch)
                            batch_futures.append(future)
                            sent_count += len(batch)
                        else:
                            logger.error("Failed to reconnect. Skipping this batch.")

            # Wait for all messages to be delivered
            success_count = 0
            for future in batch_futures:
                try:
                    # Wait for each message to be sent
                    record_metadata = future.get(timeout=10)
                    success_count += 1
                    logger.debug(
                        f"Message delivered to {record_metadata.topic} [{record_metadata.partition}] at offset {record_metadata.offset}")
                except Exception as e:
                    logger.error(f"Message delivery failed: {str(e)}")

            # Flush to ensure all messages are sent
            remaining = self.producer.flush(timeout=10)
            if remaining > 0:
                logger.warning(f"{remaining} messages were not delivered within timeout")

            logger.info(
                f"Successfully sent {success_count}/{len(batch_futures)} batches ({sent_count} metrics) to Kafka")
            return True
        except Exception as e:
            logger.error(f"Kafka delivery error: {str(e)}")
            # Try to reconnect in case of severe errors
            logger.info("Attempting to reconnect to Kafka")
            if self.connect():
                logger.info("Reconnected successfully")
            return False

    def run(self, custom_queries=None):
        """Main loop to poll Prometheus and send metrics to Kafka"""
        if not self.connect():
            logger.error("Failed to connect. Exiting.")
            return False

        queries = custom_queries or ['{__name__!=""}']

        # Log the actual configuration being used
        logger.info(f"Using Kafka broker: {self.kafka_brokers}")
        logger.info(f"Using topic: {self.topic}")
        logger.info("Starting Prometheus to Kafka bridge")
        while True:
            try:
                all_metrics = []

                # Execute all queries
                for query in queries:
                    metrics = self.query_prometheus(query)
                    if metrics:
                        all_metrics.extend(metrics)

                if all_metrics:
                    self.send_to_kafka(all_metrics)
                else:
                    logger.warning("No metrics returned from Prometheus")

                # Sleep until next polling interval
                time.sleep(self.polling_interval)

            except KeyboardInterrupt:
                logger.info("Received shutdown signal")
                # Flush any remaining messages
                self.producer.flush(timeout=30)
                self.producer.close()
                break
            except Exception as e:
                logger.error(f"Unexpected error: {str(e)}")
                # Try to reconnect in case of persistent failures
                if not self.connect():
                    logger.error("Failed to reconnect. Retrying in 30 seconds.")
                    time.sleep(30)


if __name__ == "__main__":
    import argparse
    import socket

    parser = argparse.ArgumentParser(description='Prometheus to Kafka metric bridge')
    parser.add_argument('--prometheus-url', default='http://localhost:9090',
                        help='Prometheus server URL')
    parser.add_argument('--kafka-brokers', default='localhost:9092',
                        help='Kafka broker addresses (comma-separated)')
    parser.add_argument('--topic', default='prom_metrics',
                        help='Kafka topic to send metrics to')
    parser.add_argument('--interval', type=int, default=60,
                        help='Polling interval in seconds')
    parser.add_argument('--init-wait', type=int, default=300,
                        help='Maximum time to wait for initial metrics in seconds (0 = wait forever)')
    parser.add_argument('--batch-size', type=int, default=100,
                        help='Number of metrics to send in each batch')
    parser.add_argument('--docker', action='store_true',
                        help='Set this flag if running inside Docker')
    parser.add_argument('--auto-detect', action='store_true', default=True,
                        help='Auto-detect if running in Docker (default: True)')
    # Add custom query filter options
    parser.add_argument('--queries', nargs='+',
                        help='Custom Prometheus queries (space-separated)')
    parser.add_argument('--exclude-internal', action='store_true', default=True,
                        help='Exclude Prometheus internal metrics (default: True)')
    parser.add_argument('--include-prefix', nargs='+', default=[],
                        help='Include metrics with specific prefixes (space-separated)')
    parser.add_argument('--exclude-prefix', nargs='+', default=['prometheus_', 'go_'],
                        help='Exclude metrics with specific prefixes (space-separated)')
    parser.add_argument('--include-job', nargs='+', default=[],
                        help='Include metrics from specific jobs (space-separated)')
    parser.add_argument('--exclude-job', nargs='+', default=['prometheus'],
                        help='Exclude metrics from specific jobs (space-separated)')
    args = parser.parse_args()

    # Configure logging level based on environment
    if os.environ.get("DEBUG"):
        logging.getLogger().setLevel(logging.DEBUG)
        logging.getLogger("kafka").setLevel(logging.INFO)  # Keep Kafka at INFO to avoid too much noise
        logger.info("Debug logging enabled")

    # Auto-detect Docker environment if not explicitly set
    if args.auto_detect and not args.docker:
        try:
            # Try to detect if we're in Docker by checking if we have a hostname containing "docker"
            if "docker" in socket.gethostname() or os.path.exists("/.dockerenv"):
                args.docker = True
                logger.info("Auto-detected Docker environment")
        except:
            pass

    # Set environment variable if running in Docker
    if args.docker:
        os.environ["RUNNING_IN_DOCKER"] = "1"
        logger.info("Running in Docker mode")

    # If connecting from host to Docker Kafka, ensure we use localhost
    kafka_brokers = args.kafka_brokers
    if "kafka:" in kafka_brokers and not os.environ.get("RUNNING_IN_DOCKER"):
        kafka_brokers = kafka_brokers.replace("kafka:", "localhost:")
        logger.info(f"Adjusted Kafka brokers for host-to-Docker connectivity: {kafka_brokers}")

    # Force localhost if not in Docker
    if not os.environ.get("RUNNING_IN_DOCKER") and "localhost" not in kafka_brokers:
        # This is a backup mechanism to ensure we're using localhost
        if ":" in kafka_brokers:
            port = kafka_brokers.split(":")[-1]
            kafka_brokers = f"localhost:{port}"
        else:
            kafka_brokers = "localhost:9092"
        logger.info(f"Forced local connectivity: {kafka_brokers}")

    # Try to check connectivity before starting
    logger.info(f"Checking Kafka connectivity to {kafka_brokers}")
    try:
        # Try to resolve all broker hostnames before starting
        for broker in kafka_brokers.split(','):
            host = broker.split(':')[0].strip()
            port = int(broker.split(':')[1].strip())
            try:
                socket.getaddrinfo(host, port)
                logger.info(f"Successfully resolved {host}:{port}")
            except socket.gaierror:
                logger.warning(f"Could not resolve {host}:{port} - this might cause issues")
                if host == "kafka" and not os.environ.get("RUNNING_IN_DOCKER"):
                    logger.warning("You're trying to connect to 'kafka' from outside Docker.")
                    logger.warning("Consider using 'localhost' instead or use the --docker flag if running in Docker.")
                    # Automatically fix this common issue
                    kafka_brokers = kafka_brokers.replace(broker, f"localhost:{port}")
                    logger.info(f"Automatically switched to {kafka_brokers}")
    except Exception as e:
        logger.warning(f"Error checking connectivity: {str(e)}")

    # Set max_wait_time to None for infinite wait if init-wait is 0
    max_wait_time = None if args.init_wait == 0 else args.init_wait
    if max_wait_time is None:
        logger.info("Will wait indefinitely for metrics to become available")
    else:
        logger.info(f"Will wait up to {max_wait_time} seconds for initial metrics")

    # Build a list of custom queries based on parameters if no explicit queries provided
    custom_queries = None
    if args.queries:
        custom_queries = args.queries
        logger.info(f"Using custom queries: {custom_queries}")
    elif args.exclude_internal or args.include_prefix or args.exclude_prefix or args.include_job or args.exclude_job:
        custom_queries = []

        # Build metric name filter
        name_filters = []

        # Handle include prefixes
        if args.include_prefix:
            prefix_filter = '|'.join([f"{prefix}.*" for prefix in args.include_prefix])
            name_filters.append(f'__name__=~"{prefix_filter}"')

        # Handle exclude prefixes
        if args.exclude_prefix:
            prefix_filter = '|'.join([f"{prefix}.*" for prefix in args.exclude_prefix])
            name_filters.append(f'__name__!~"{prefix_filter}"')

        # Handle job labels
        job_filters = []

        # Handle include jobs
        if args.include_job:
            job_filter = '|'.join(args.include_job)
            job_filters.append(f'job=~"{job_filter}"')

        # Handle exclude jobs
        if args.exclude_job:
            job_filter = '|'.join(args.exclude_job)
            job_filters.append(f'job!~"{job_filter}"')

        # Combine filters
        if name_filters or job_filters:
            # Start with a base query that includes all metrics
            base_query = '{__name__=~".+"}'

            exclude_queries = []

            # Handle exclude prefixes
            if args.exclude_prefix:
                for prefix in args.exclude_prefix:
                    exclude_queries.append(f'{{__name__=~"{prefix}.*"}}')

            # Handle exclude jobs
            if args.exclude_job:
                for job in args.exclude_job:
                    exclude_queries.append(f'{{job="{job}"}}')

            # Combine using 'unless' operator
            if exclude_queries:
                combined_filter = f"{base_query} unless ({' or '.join(exclude_queries)})"
            else:
                combined_filter = base_query

            custom_queries.append(combined_filter)
            logger.info(f"Generated query from filters: {combined_filter}")

        # Add fallback query if no filters were applied
        if not custom_queries:
            custom_queries.append('{__name__!=""}')
            logger.info("No filters applied, using default query")

    bridge = PrometheusToKafkaBridge(
        prometheus_url=args.prometheus_url,
        kafka_brokers=kafka_brokers,
        topic=args.topic,
        polling_interval=args.interval,
        batch_size=args.batch_size,
        max_wait_time=max_wait_time
    )

    # Run the bridge with custom queries if provided
    bridge.run(custom_queries)