# backpressure_monitor.py
import time
import redis

r = redis.Redis(host="localhost", port=6379, decode_responses=True)

RATE_KEY        = "flashguard:event_rate"    # Redis ZSET
QUEUE_DEPTH_KEY = "flashguard:queue_depth"   # Redis string
RATE_THRESHOLD  = 1000    # events/sec
QUEUE_THRESHOLD = 5000    # queue depth
WINDOW_SECONDS  = 5       # sliding window size

class BackpressureMonitor:

    def record_event(self):
        now = time.time()
        pipe = r.pipeline()
        # Add event with timestamp as score
        pipe.zadd(RATE_KEY, {str(now): now})
        # Remove events outside the window
        pipe.zremrangebyscore(RATE_KEY, 0, now - WINDOW_SECONDS)
        # Auto-expire the key after 60s of inactivity
        pipe.expire(RATE_KEY, 60)
        pipe.execute()

    def current_rate(self) -> float:
        now = time.time()
        count = r.zcount(RATE_KEY, now - WINDOW_SECONDS, now)
        return count / WINDOW_SECONDS

    def set_queue_depth(self, depth: int):
        r.set(QUEUE_DEPTH_KEY, depth, ex=60)

    def get_queue_depth(self) -> int:
        val = r.get(QUEUE_DEPTH_KEY)
        return int(val) if val else 0

    def is_shedding(self) -> bool:
        return (
            self.current_rate()    > RATE_THRESHOLD or
            self.get_queue_depth() > QUEUE_THRESHOLD
        )

    def status(self) -> dict:
        return {
            "current_rate":   self.current_rate(),
            "queue_depth":    self.get_queue_depth(),
            "is_shedding":    self.is_shedding(),
            "rate_threshold": RATE_THRESHOLD,
        }

# Singleton
monitor = BackpressureMonitor()
