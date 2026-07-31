import os
import json
import time
import logging
import pandas as pd
from deltalake import write_deltalake
import redis

logging.basicConfig(level=logging.INFO, format="%(asctime)s [LakeWriter] %(levelname)s %(message)s")
logger = logging.getLogger("lake_writer")

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
LAKE_PATH = os.getenv("LAKE_PATH", "/app/data/lake")
STREAM_KEY = "pathway:events"
CONSUMER_GROUP = "lake_writer_group"
CONSUMER_NAME = "lake_writer_1"

def get_redis():
    return redis.Redis.from_url(REDIS_URL, decode_responses=True)

def ensure_group(r):
    try:
        r.xgroup_create(STREAM_KEY, CONSUMER_GROUP, id="0", mkstream=True)
        logger.info(f"Created consumer group {CONSUMER_GROUP}")
    except redis.exceptions.ResponseError as e:
        if "BUSYGROUP" not in str(e):
            logger.warning(f"Consumer group error: {e}")

def main():
    r = get_redis()
    while True:
        try:
            r.ping()
            break
        except redis.exceptions.ConnectionError:
            logger.warning("Waiting for Redis...")
            time.sleep(2)
            
    ensure_group(r)
    
    logger.info(f"Lake Writer started. Sinking to {LAKE_PATH}")
    
    while True:
        try:
            messages = r.xreadgroup(
                CONSUMER_GROUP, CONSUMER_NAME, {STREAM_KEY: ">"}, count=100, block=2000
            )
            
            if not messages:
                continue
                
            records = []
            msg_ids_to_ack = []
            
            for stream_name, stream_messages in messages:
                for msg_id, msg_data in stream_messages:
                    records.append({
                        "msg_id": msg_id,
                        "event_type": msg_data.get("event_type", "unknown"),
                        "txn_id": msg_data.get("txn_id", ""),
                        "source": msg_data.get("source", ""),
                        "timestamp": msg_data.get("timestamp", ""),
                        "payload": msg_data.get("payload", "{}")
                    })
                    msg_ids_to_ack.append(msg_id)
            
            if records:
                df = pd.DataFrame(records)
                # Convert timestamp to float then to datetime if needed, but string is fine for now
                try:
                    # Write to Delta table using overwrite or append depending on if it exists
                    # We will use mode="append" and engine="rust" (default).
                    # If table doesn't exist, append will create it.
                    write_deltalake(
                        LAKE_PATH, 
                        df, 
                        mode="append", 
                        schema_mode="merge" # In case payload or other fields change
                    )
                    logger.info(f"Wrote {len(records)} events to Delta Lake at {LAKE_PATH}")
                    r.xack(STREAM_KEY, CONSUMER_GROUP, *msg_ids_to_ack)
                except Exception as e:
                    logger.error(f"Failed to write to Delta Lake: {e}")
                    time.sleep(2)
                    
        except redis.exceptions.ConnectionError:
            logger.warning("Redis disconnected, retrying in 5s")
            time.sleep(5)
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            time.sleep(2)

if __name__ == "__main__":
    main()
