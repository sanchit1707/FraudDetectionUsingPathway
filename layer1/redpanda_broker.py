from kafka.admin import KafkaAdminClient,NewTopic
from config import Config

def setup_redpanda_topics():
    admin=KafkaAdminClient(bootstrap_servers=Config.KAFKA_HOST)

    topics=[
        NewTopic(
            name="transactions",
            num_partitions=8,
            replication_factor=1
        ),
        NewTopic(
            name="fraud_alerts",
            num_partitions=4,
            replication_factor=1
        ),
        NewTopic(
            name="audit",
            num_partitions=2,
            replication_factor=1
        )
    ]
    admin.create_topics(topics)
