# layer0_sources/stream_buffer.py
import json
import os
import time
import threading
from pathlib import Path

BUFFER_DIR  = "./data/stream_buffer/"
BUFFER_FILE = "./data/stream_buffer/shed_events.jsonl"   # one JSON per line

os.makedirs(BUFFER_DIR, exist_ok=True)

_write_lock = threading.Lock()


def append_to_buffer(event: dict, reason: str):
    """
    Append a shed event to the replay buffer.
    Format: one JSON object per line (JSONL) — easy to replay later.
    """
    record = {
        "shed_at":     time.time(),
        "shed_reason": reason,
        "event":       event
    }
    with _write_lock:
        with open(BUFFER_FILE, "a") as f:
            f.write(json.dumps(record) + "\n")


def get_buffer_size() -> int:
    """How many events are waiting in the replay buffer."""
    if not Path(BUFFER_FILE).exists():
        return 0
    with open(BUFFER_FILE) as f:
        return sum(1 for _ in f)


def replay_buffer(process_fn, batch_size: int = 100) -> int:
    """
    Replay shed events when system load drops.
    process_fn: your normal event processing function
    Returns: number of events replayed
    """
    if not Path(BUFFER_FILE).exists():
        print("[BUFFER] No events to replay")
        return 0

    replayed = 0
    remaining = []

    with open(BUFFER_FILE) as f:
        lines = f.readlines()

    print(f"[BUFFER] Replaying {len(lines)} shed events...")

    for i, line in enumerate(lines):
        record = json.loads(line.strip())
        try:
            process_fn(record["event"])
            replayed += 1
        except Exception as e:
            print(f"[BUFFER] Replay failed for event {i}: {e}")
            remaining.append(line)   # keep failed ones

        if replayed % batch_size == 0:
            print(f"[BUFFER] Replayed {replayed}/{len(lines)}")

    # Rewrite buffer with only failed events
    with _write_lock:
        with open(BUFFER_FILE, "w") as f:
            f.writelines(remaining)

    print(f"[BUFFER] Done. Replayed={replayed}, Failed={len(remaining)}")
    return replayed