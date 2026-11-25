from collections import deque
from threading import Lock
from time import monotonic


class RateLimiter:
    def __init__(self):
        self.requests = {}
        self.lock = Lock()
        self.last_cleanup = monotonic()

    def allow(self, address: str, bucket: str, limit: int):
        now = monotonic()
        with self.lock:
            if now - self.last_cleanup >= 60 or len(self.requests) >= 10000:
                self.requests = {key: values for key, values in self.requests.items()
                                 if values and values[-1] > now - 60}
                self.last_cleanup = now
            key = (address, bucket)
            if key not in self.requests and len(self.requests) >= 10000:
                return False
            events = self.requests.setdefault(key, deque())
            while events and events[0] <= now - 60:
                events.popleft()
            if len(events) >= limit:
                return False
            events.append(now)
            return True
