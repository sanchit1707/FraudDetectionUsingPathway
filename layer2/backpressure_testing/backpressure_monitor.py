import time
import threading
from collections import deque 

class BackpressureMonitor:
    def __init__(
            self,
            rate_threshold: int =1000,
            queue_threshold: int=5000,
            window_seconds: int=5
    ):
        self.rate_threshold = rate_threshold
        self.queue_threshold = queue_threshold
        self.window_seconds=window_seconds

        self._event_times=deque()
        self._queue_depth=0
        self._lock=threading.Lock()

    def record_event(self):
        now=time.monotonic()
        with self._lock:
            self._event_times.append(now)
        cutoff=now-self.window_seconds
        while self._event_times and self._event_times[0]<cutoff:
            self._event_times.popleft()
        
    def set_queue_depth(self,depth:int):
        with self._lock:
            self._queue_depth=depth
    
    def current_rate(self)->float:
        with self._lock:
            return len(self._event_times)/self.window_seconds
    def is_shedding(self)->bool:
        return(self.current_rate()>self.rate_threshold or self._queue_depth>self.queue_threshold)
    def status(self)-> dict:
        return {
            "current_rate":self.current_rate(),
            "queue_depth":self._queue_depth,
            "is_shedding":self.is_shedding(),
            "rate_threshold":self.rate_threshold

        }
monitor=BackpressureMonitor()
