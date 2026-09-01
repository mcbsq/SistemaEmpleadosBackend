import threading
import time


class RegistrationRateLimiter:
    def __init__(self, max_attempts=5, window_seconds=3600, clock=None):
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self.clock = clock or time.monotonic
        self._attempts = {}
        self._lock = threading.Lock()

    def allow(self, client_key):
        now = self.clock()
        cutoff = now - self.window_seconds
        with self._lock:
            recent = [stamp for stamp in self._attempts.get(client_key, []) if stamp > cutoff]
            if len(recent) >= self.max_attempts:
                self._attempts[client_key] = recent
                return False
            recent.append(now)
            self._attempts[client_key] = recent
            return True
