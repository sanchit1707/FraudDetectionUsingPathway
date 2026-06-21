# layer0_sources/replay_scheduler.py
import time
import threading
from backpressure_monitor import monitor
from stream_buffer import replay_buffer, get_buffer_size

def start_replay_scheduler(process_fn, check_interval: int = 30):
    """
    Runs in background. When load drops below threshold,
    automatically replays shed events from the buffer.
    """
    def _loop():
        while True:
            time.sleep(check_interval)

            if monitor.is_shedding():
                print(f"[REPLAY] System still under load ({monitor.current_rate():.0f}/s) — skipping replay")
                continue

            buffer_size = get_buffer_size()
            if buffer_size == 0:
                continue

            print(f"[REPLAY] Load normal. Replaying {buffer_size} shed events...")
            replayed = replay_buffer(process_fn, batch_size=50)
            print(f"[REPLAY] Replayed {replayed} events")

    thread = threading.Thread(target=_loop, daemon=True)
    thread.start()
    print("[REPLAY] Scheduler started — checks every 30s")