# replay_scheduler.py
import time
import threading
import redis
from backpressure_monitor import monitor
from stream_buffer import replay_buffer, get_buffer_size

r = redis.Redis(host="localhost", port=6379, decode_responses=True)
REPLAY_CHANNEL = "flashguard:replay_trigger"


def trigger_replay():
    """Publish replay signal — any scheduler listening will react."""
    r.publish(REPLAY_CHANNEL, "replay_now")


def start_replay_scheduler(process_fn, worker_id: str = "worker-1"):
    """
    Two mechanisms:
    1. Pub/Sub listener — instant replay when triggered
    2. Polling fallback — catches anything missed by pub/sub
    """

    # ── Mechanism 1: Pub/Sub listener ────────────────────
    def pubsub_listener():
        pubsub = r.pubsub()
        pubsub.subscribe(REPLAY_CHANNEL)
        print(f"[REPLAY] Listening on channel {REPLAY_CHANNEL}")

        for message in pubsub.listen():
            if message["type"] != "message":
                continue
            if monitor.is_shedding():
                print("[REPLAY] Trigger received but still under load — skipping")
                continue
            size = get_buffer_size()
            if size > 0:
                print(f"[REPLAY] Triggered — replaying {size} events")
                replay_buffer(process_fn, worker_id=worker_id)

    # ── Mechanism 2: Polling fallback every 30s ───────────
    def polling_loop():
        while True:
            time.sleep(30)
            if monitor.is_shedding():
                continue
            size = get_buffer_size()
            if size > 0:
                print(f"[REPLAY] Poll — replaying {size} buffered events")
                replay_buffer(process_fn, worker_id=worker_id)

    threading.Thread(target=pubsub_listener, daemon=True).start()
    threading.Thread(target=polling_loop,    daemon=True).start()
    print("[REPLAY] Scheduler started")
