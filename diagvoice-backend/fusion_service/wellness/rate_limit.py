"""Basit IP başına dakikalık rate limit (in-memory)."""

from __future__ import annotations

import os
import time
from collections import defaultdict
from threading import Lock

_lock = Lock()
_hits: dict[str, list[float]] = defaultdict(list)

WELLNESS_RATE_LIMIT_PER_MIN = max(1, int(os.environ.get("WELLNESS_RATE_LIMIT_PER_MIN", "20")))


def check_rate_limit(client_ip: str) -> bool:
    """True = izin verildi, False = limit aşıldı."""
    ip = (client_ip or "unknown").strip()[:200] or "unknown"
    now = time.monotonic()
    window = 60.0
    with _lock:
        bucket = _hits[ip]
        cutoff = now - window
        _hits[ip] = [t for t in bucket if t > cutoff]
        if len(_hits[ip]) >= WELLNESS_RATE_LIMIT_PER_MIN:
            return False
        _hits[ip].append(now)
        return True
