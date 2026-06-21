import time
import concurrent.futures

# Import the class from your other file (monitor.py)
from backpressure_monitor import BackpressureMonitor

def print_status(phase: str, monitor: BackpressureMonitor):
    """Helper function to cleanly print the current state of the monitor."""
    stats = monitor.status()
    # Visual indicator if shedding is active
    alert = "🚨 SHEDDING LOAD!" if stats['is_shedding'] else "✅ NORMAL"
    
    print(f"{phase:<25} | Rate: {stats['current_rate']:<6.1f} | "
          f"Queue: {stats['queue_depth']:<5} | Status: {alert}")

def blast_requests(monitor: BackpressureMonitor, num_requests: int, concurrent_users: int = 50):
    """Simulates a massive spike in traffic hitting the server."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrent_users) as executor:
        # Launch thousands of record_event calls across multiple threads instantly
        futures = [executor.submit(monitor.record_event) for _ in range(num_requests)]
        
        # Wait for all threads to finish their work
        concurrent.futures.wait(futures)

def run_stress_test():
    # 1. Initialize with low thresholds so it's easy to trigger
    # Max 200 requests per second (1000 per 5s window)
    sys_monitor = BackpressureMonitor(rate_threshold=200, queue_threshold=500, window_seconds=5)
    
    print("--- STARTING MULTI-THREADED STRESS TEST ---\n")
    print_status("1. Server Started (Idle)", sys_monitor)

    # 2. Simulate light, normal traffic
    print("\n[ Incoming normal traffic... ]")
    blast_requests(sys_monitor, num_requests=150) # Safe: 150 events in 5s
    print_status("2. After Normal Traffic", sys_monitor)

    # 3. Simulate a massive DDoS attack or viral spike
    print("\n[ ⚠️ SIMULATING TRAFFIC SPIKE: 1500 concurrent requests! ]")
    blast_requests(sys_monitor, num_requests=1500) 
    print_status("3. During Traffic Spike", sys_monitor)

    # 4. Wait for the sliding window to clear the old events
    print("\n[ Traffic stopped. Waiting 6 seconds for sliding window to clear... ]")
    time.sleep(6)
    sys_monitor.record_event() # Trigger one event to force the cleanup loop
    print_status("4. After 6s Cooldown", sys_monitor)

    # 5. Simulate a downstream database slowing down (queue fills up)
    print("\n[ ⚠️ SIMULATING DATABASE SLOWDOWN: Queue backing up! ]")
    sys_monitor.set_queue_depth(800) # Exceeds queue_threshold of 500
    print_status("5. High Queue Depth", sys_monitor)

if __name__ == "__main__":
    run_stress_test()