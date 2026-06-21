import time
import random
from backpressure_monitor import monitor
from priority_router import route_event
from replay_scheduler import start_replay_scheduler
from stream_buffer import get_buffer_size

# ── Dummy processors ─────────────────────────────────────
def process_p0(event):
    print(f"  [P0 CRITICAL] {event['TransactionID']} — {event.get('p0_reason', '')}")

def process_p1(event):
    print(f"  [P1 HIGH]     {event['TransactionID']} — amount={event['TransactionAmount']}")

def process_p2(event):
    print(f"  [P2 NORMAL]   {event['TransactionID']}")

# ── Sample transactions ───────────────────────────────────
SAMPLE_EVENTS = [
    # P0 — sanctions hit
    {"TransactionID": "TX001", "AccountID": "AC001", "TransactionAmount": 5000,
     "Location": "Mumbai", "LoginAttempts": 1, "sanctions_hit": True},

    # P0 — geo jump
    {"TransactionID": "TX002", "AccountID": "AC002", "TransactionAmount": 1000,
     "Location": "Mumbai", "LoginAttempts": 1, "geo_jump_km": 800},

    # P1 — new device
    {"TransactionID": "TX003", "AccountID": "AC003", "TransactionAmount": 2000,
     "Location": "Delhi", "LoginAttempts": 1, "is_new_device": True},

    # P1 — unusual hour
    {"TransactionID": "TX004", "AccountID": "AC004", "TransactionAmount": 500,
     "Location": "Pune", "LoginAttempts": 1, "hour_of_day": 3},

    # P2 — normal
    {"TransactionID": "TX005", "AccountID": "AC005", "TransactionAmount": 300,
     "Location": "Chennai", "LoginAttempts": 1},

    # P2 — normal
    {"TransactionID": "TX006", "AccountID": "AC006", "TransactionAmount": 150,
     "Location": "Indore", "LoginAttempts": 1},
]

# ── TEST 1: Normal routing (no backpressure) ──────────────
print("\n" + "="*50)
print("TEST 1 — Normal routing (no backpressure)")
print("="*50)
for event in SAMPLE_EVENTS:
    priority = route_event(event, process_p0, process_p1, process_p2)
    print(f"  → Routed to {priority}")

# ── TEST 2: Simulate backpressure → P3 shedding ──────────
print("\n" + "="*50)
print("TEST 2 — Backpressure active (P3 shedding)")
print("="*50)

# Force backpressure by flooding the monitor
print("  Flooding monitor to trigger backpressure...")
for _ in range(6000):
    monitor.record_event()

print(f"  Current rate: {monitor.current_rate():.0f}/s | Shedding: {monitor.is_shedding()}")

for event in SAMPLE_EVENTS:
    priority = route_event(event, process_p0, process_p1, process_p2)
    print(f"  {event['TransactionID']} → {priority}")

print(f"\n  Events in replay buffer: {get_buffer_size()}")

# ── TEST 3: Replay after load drops ──────────────────────
print("\n" + "="*50)
print("TEST 3 — Waiting for load to drop, then replay")
print("="*50)
print("  Waiting 6 seconds for rate window to clear...")
time.sleep(6)

print(f"  Current rate: {monitor.current_rate():.0f}/s | Shedding: {monitor.is_shedding()}")
print(f"  Buffer size before replay: {get_buffer_size()}")

from stream_buffer import replay_buffer
replayed = replay_buffer(process_p2, batch_size=10)
print(f"  Replayed {replayed} events from buffer")
print(f"  Buffer size after replay: {get_buffer_size()}")