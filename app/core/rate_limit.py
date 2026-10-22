import time
from collections import defaultdict
from threading import Lock

"""
In-process rate limiter for authentication attempt protection.

Limitations:
- Stored in-memory per process.
- State is not shared across multi-process workers or server instances.
- Cleared upon process restart.
In a distributed production environment, an external distributed store like Redis
would be used. For this single-process FastAPI modular monolith, it provides
effective local brute-force protection.
"""

_attempts: dict[str, list[float]] = defaultdict(list)
_lock = Lock()


def check_rate_limit(
    key: str,
    max_attempts: int = 10,
    window_seconds: int = 300,
) -> bool:
    """
    Returns True if the action is allowed under the rate limit.
    Returns False if the maximum number of attempts has been exceeded within the window.
    """
    now = time.monotonic()
    cutoff = now - window_seconds

    with _lock:
        timestamps = _attempts[key]
        # Prune old timestamps
        _attempts[key] = [t for t in timestamps if t > cutoff]
        if len(_attempts[key]) >= max_attempts:
            return False
        return True


def record_attempt(key: str) -> None:
    """Records an attempt for the given key."""
    now = time.monotonic()
    with _lock:
        _attempts[key].append(now)


def clear_attempts(key: str) -> None:
    """Clears recorded attempts for the given key (e.g. after successful login)."""
    with _lock:
        if key in _attempts:
            del _attempts[key]
