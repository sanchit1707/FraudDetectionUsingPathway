# stream_buffer.py
import json
import time
import redis

r = redis.Redis(host="localhost", port=6379, decode_responses=True)

STREAM_KEY    = "flashguard:shed_stream"      # Redis Stream
CONSUMER_GRP  = "flashguard:replay_workers"
ANALYTICS_KEY = "flashguard:shed_analytics"  # Redis List for analytics log
MAX_BUFFER    = 100_000                       # cap stream at 100k events


def append_to_buffer(event: dict, reason: str):
    """
    Append shed event to Redis Stream.
    XADD is O(1) — much faster than writing to a file.
    """
    r.xadd(
        STREAM_KEY,
        {
            "event":       json.dumps(event),
            "shed_reason": reason,
            "shed_at":     str(time.time()),
        },
        maxlen=MAX_BUFFER,    # auto-trim oldest events if buffer full
        approximate=True      # ~maxlen, faster trim
    )

    # Also log to analytics list (capped at 10k entries)
    r.lpush(ANALYTICS_KEY, json.dumps({
        "tx_id":       event.get("TransactionID"),
        "amount":      event.get("TransactionAmount"),
        "shed_reason": reason,
        "shed_at":     time.time(),
    }))
    r.ltrim(ANALYTICS_KEY, 0, 9999)


def get_buffer_size() -> int:
    """O(1) — Redis tracks stream length natively."""
    return r.xlen(STREAM_KEY)


def ensure_consumer_group():
    """Create consumer group if it doesn't exist."""
    try:
        r.xgroup_create(STREAM_KEY, CONSUMER_GRP, id="0", mkstream=True)
    except redis.exceptions.ResponseError:
        pass  # group already exists


def replay_buffer(process_fn, batch_size: int = 100, worker_id: str = "worker-1") -> int:
    """
    Replay shed events using Redis consumer group.
    Consumer groups give you:
    - Each event delivered to exactly one worker (no duplicates)
    - Acknowledgement — failed events stay in PEL for retry
    - Multiple workers can replay in parallel
    """
    ensure_consumer_group()
    replayed = 0

    while True:
        # Read batch from stream
        messages = r.xreadgroup(
            CONSUMER_GRP,
            worker_id,
            {STREAM_KEY: ">"},    # ">" means undelivered messages only
            count=batch_size,
            block=0               # 0 = don't block, return immediately
        )

        if not messages or not messages[0][1]:
            break  # nothing left to replay

        for stream_name, events in messages:
            for msg_id, fields in events:
                event = json.loads(fields["event"])
                try:
                    process_fn(event)
                    # Acknowledge — removes from PEL (Pending Entry List)
                    r.xack(STREAM_KEY, CONSUMER_GRP, msg_id)
                    replayed += 1
                except Exception as e:
                    print(f"[BUFFER] Replay failed for {msg_id}: {e}")
                    # Don't ack — stays in PEL for retry

    return replayed


def get_pending_count() -> int:
    """Events delivered but not yet acknowledged (in-flight or failed)."""
    try:
        ensure_consumer_group()
        info = r.xpending(STREAM_KEY, CONSUMER_GRP)
        return info["pending"]
    except Exception:
        return 0


def get_analytics(limit: int = 100) -> list:
    """Last N shed events for dashboard."""
    raw = r.lrange(ANALYTICS_KEY, 0, limit - 1)
    return [json.loads(r) for r in raw]
