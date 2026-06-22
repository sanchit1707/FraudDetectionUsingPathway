import time
from backpressure_monitor import monitor
from priority_router import route_event
from stream_buffer import get_buffer_size, replay_buffer, get_analytics

def process_p0(e): print(f"  [P0] {e['TransactionID']}")
def process_p1(e): print(f"  [P1] {e['TransactionID']}")
def process_p2(e): print(f"  [P2] {e['TransactionID']}")

EVENTS = [
    {"TransactionID": "TX001", "TransactionAmount": 5000,
     "Location": "Mumbai", "sanctions_hit": True},
    {"TransactionID": "TX002", "TransactionAmount": 1000,
     "Location": "Mumbai", "geo_jump_km": 800},
    {"TransactionID": "TX003", "TransactionAmount": 2000,
     "Location": "Delhi",  "is_new_device": True},
    {"TransactionID": "TX004", "TransactionAmount": 500,
     "Location": "Pune",   "hour_of_day": 3},
    {"TransactionID": "TX005", "TransactionAmount": 300,
     "Location": "Chennai"},
    {"TransactionID": "TX006", "TransactionAmount": 150,
     "Location": "Indore"},
]

print("\n=== TEST 1: Normal routing ===")
for e in EVENTS:
    p = route_event(e, process_p0, process_p1, process_p2)
    print(f"  {e['TransactionID']} → {p}")

print("\n=== TEST 2: Backpressure → P3 shedding ===")
for _ in range(6000):
    monitor.record_event()
print(f"  Rate: {monitor.current_rate():.0f}/s | Shedding: {monitor.is_shedding()}")

for e in EVENTS:
    p = route_event(e, process_p0, process_p1, process_p2)
    print(f"  {e['TransactionID']} → {p}")

print(f"\n  Buffer size: {get_buffer_size()}")
print(f"  Analytics: {get_analytics(limit=5)}")

print("\n=== TEST 3: Wait + Replay ===")
time.sleep(6)
print(f"  Rate after wait: {monitor.current_rate():.0f}/s")
replayed = replay_buffer(process_p2)
print(f"  Replayed: {replayed} | Buffer remaining: {get_buffer_size()}")
