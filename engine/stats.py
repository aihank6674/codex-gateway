"""
In-memory request statistics tracker for the codex-gateway dashboard.
Stores recent request logs and aggregate counters.
"""

import time
from collections import deque
from threading import Lock

# Maximum number of recent requests to keep in memory
MAX_RECENT = 100

_lock = Lock()
_start_time = time.time()
_total_requests = 0
_requests_by_model = {}   # target_model -> count
_requests_by_backend = {} # backend_name -> count
_recent_requests = deque(maxlen=MAX_RECENT)


def record_request(client_model: str, target_backend: str, target_model: str, stream: bool):
    """Record a single proxied request."""
    global _total_requests
    with _lock:
        _total_requests += 1
        _requests_by_model[target_model] = _requests_by_model.get(target_model, 0) + 1
        _requests_by_backend[target_backend] = _requests_by_backend.get(target_backend, 0) + 1
        _recent_requests.appendleft({
            "time": time.strftime("%H:%M:%S"),
            "timestamp": time.time(),
            "client_model": client_model,
            "target_backend": target_backend,
            "target_model": target_model,
            "stream": stream,
        })


def get_stats() -> dict:
    """Return current stats snapshot."""
    with _lock:
        uptime_secs = int(time.time() - _start_time)
        hours, remainder = divmod(uptime_secs, 3600)
        minutes, seconds = divmod(remainder, 60)
        uptime_str = f"{hours}h {minutes}m {seconds}s"

        return {
            "uptime": uptime_str,
            "uptime_seconds": uptime_secs,
            "total_requests": _total_requests,
            "requests_by_model": dict(_requests_by_model),
            "requests_by_backend": dict(_requests_by_backend),
            "recent_requests": list(_recent_requests),
        }
