"""Redis bağlantısı (REDIS_URL). Testlerde set_redis ile fakeredis verilir."""
from __future__ import annotations

import os
from typing import Any, Optional

_redis: Optional[Any] = None


def enabled() -> bool:
    return bool(os.environ.get("REDIS_URL")) or _redis is not None


def get_redis():
    global _redis
    if _redis is None:
        import redis.asyncio as aioredis

        _redis = aioredis.from_url(os.environ["REDIS_URL"], decode_responses=True, health_check_interval=30)
    return _redis


def set_redis(r) -> None:
    global _redis
    _redis = r
