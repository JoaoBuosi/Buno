from collections import deque
from threading import Lock
from time import monotonic

from fastapi import HTTPException

_windows: dict[str, deque[float]] = {}
_lock = Lock()


def check_rate_limit(key: str, limit: int) -> None:
    """Per-process sliding window. Use a shared limiter before multiple replicas."""
    now = monotonic()
    with _lock:
        for expired in [k for k, values in _windows.items() if not values or values[-1] <= now - 60]:
            del _windows[expired]
        if key not in _windows and len(_windows) >= 10000:
            raise HTTPException(429, "Serviço ocupado. Tente novamente em instantes.", headers={"Retry-After": "60"})
        values = _windows.setdefault(key, deque())
        while values and values[0] <= now - 60:
            values.popleft()
        if len(values) >= limit:
            raise HTTPException(429, "Você enviou muitas mensagens. Aguarde um minuto.", headers={"Retry-After": "60"})
        values.append(now)
