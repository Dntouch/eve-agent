"""Process-local execution activity, independent of conversation contents."""
from contextlib import contextmanager
import threading


class WorkActivity:
    """Count overlapping and nested work; always release activity on exit."""

    def __init__(self):
        self._lock = threading.Lock()
        self._active = 0

    @contextmanager
    def track(self):
        with self._lock:
            self._active += 1
        try:
            yield
        finally:
            with self._lock:
                self._active -= 1

    def is_working(self):
        with self._lock:
            return self._active > 0
