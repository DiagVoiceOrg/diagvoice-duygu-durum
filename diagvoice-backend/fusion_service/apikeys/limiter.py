"""
Anahtar başına rate limit, eşzamanlılık sınırı ve aylık kota.

İki uygulama, aynı arayüz:
  MemoryLimiter  tek süreç (testler, REDIS_URL yokken)
  RedisLimiter   REDIS_URL varsa (çok süreç/konteyner güvenli)

Dakikalık sınır: bellek → token bucket; Redis → sabit 1 dakikalık pencere (INCR + EXPIRE).
"""
from __future__ import annotations

import asyncio
import math
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Awaitable, Callable


@dataclass
class Decision:
    ok: bool
    limit: int = 0
    remaining: int = 0
    retry_after: int = 0


def month() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


@dataclass
class _Bucket:
    tokens: float
    updated: float = field(default_factory=time.monotonic)


class MemoryLimiter:
    def __init__(self) -> None:
        self._buckets: dict[str, _Bucket] = {}
        self._active: dict[str, int] = {}
        self._monthly: dict[tuple[str, str], int] = {}
        self._lock = asyncio.Lock()

    month = staticmethod(month)

    async def hit(self, key_id: str, rpm: int) -> Decision:
        if rpm <= 0:
            return Decision(ok=True)
        now = time.monotonic()
        async with self._lock:
            b = self._buckets.get(key_id)
            if b is None:
                b = self._buckets[key_id] = _Bucket(tokens=float(rpm), updated=now)
            rate = rpm / 60.0
            b.tokens = min(float(rpm), b.tokens + (now - b.updated) * rate)
            b.updated = now
            if b.tokens >= 1.0:
                b.tokens -= 1.0
                return Decision(ok=True, limit=rpm, remaining=int(b.tokens))
            return Decision(ok=False, limit=rpm, remaining=0, retry_after=max(1, math.ceil((1.0 - b.tokens) / rate)))

    async def acquire(self, key_id: str, max_concurrent: int) -> bool:
        if max_concurrent <= 0:
            return True
        async with self._lock:
            n = self._active.get(key_id, 0)
            if n >= max_concurrent:
                return False
            self._active[key_id] = n + 1
            return True

    async def release(self, key_id: str, max_concurrent: int) -> None:
        if max_concurrent <= 0:
            return
        async with self._lock:
            n = self._active.get(key_id, 0) - 1
            if n <= 0:
                self._active.pop(key_id, None)
            else:
                self._active[key_id] = n

    async def active(self, key_id: str) -> int:
        return self._active.get(key_id, 0)

    async def ensure_monthly(self, key_id: str, loader: Callable[[], Awaitable[int]]) -> None:
        k = (key_id, month())
        if k not in self._monthly:
            self._monthly[k] = int(await loader())

    async def quota(self, key_id: str, monthly_quota: int) -> Decision:
        if monthly_quota <= 0:
            return Decision(ok=True)
        k = (key_id, month())
        async with self._lock:
            used = self._monthly.get(k, 0)
            if used >= monthly_quota:
                return Decision(ok=False, limit=monthly_quota, remaining=0)
            self._monthly[k] = used + 1
            return Decision(ok=True, limit=monthly_quota, remaining=monthly_quota - used - 1)

    def reset(self) -> None:
        self._buckets.clear()
        self._active.clear()
        self._monthly.clear()


class RedisLimiter:
    """Anahtarlar: dv:rl:<key>:<dakika>, dv:cc:<key>, dv:mq:<key>:<YYYY-MM>."""

    CC_TTL = 900  # eşzamanlılık sayacı sızarsa (süreç çökmesi) 15 dk'da kendini temizler

    def __init__(self, redis_factory: Callable) -> None:
        self._r = redis_factory

    month = staticmethod(month)

    async def hit(self, key_id: str, rpm: int) -> Decision:
        if rpm <= 0:
            return Decision(ok=True)
        now = time.time()
        window = int(now // 60)
        k = f"dv:rl:{key_id}:{window}"
        r = self._r()
        n = await r.incr(k)
        if n == 1:
            await r.expire(k, 70)
        if n > rpm:
            return Decision(ok=False, limit=rpm, remaining=0, retry_after=max(1, math.ceil((window + 1) * 60 - now)))
        return Decision(ok=True, limit=rpm, remaining=max(0, rpm - n))

    async def acquire(self, key_id: str, max_concurrent: int) -> bool:
        if max_concurrent <= 0:
            return True
        r = self._r()
        k = f"dv:cc:{key_id}"
        n = await r.incr(k)
        await r.expire(k, self.CC_TTL)
        if n > max_concurrent:
            await r.decr(k)
            return False
        return True

    async def release(self, key_id: str, max_concurrent: int) -> None:
        if max_concurrent <= 0:
            return
        r = self._r()
        k = f"dv:cc:{key_id}"
        n = await r.decr(k)
        if n <= 0:
            await r.delete(k)

    async def active(self, key_id: str) -> int:
        v = await self._r().get(f"dv:cc:{key_id}")
        return max(0, int(v or 0))

    async def ensure_monthly(self, key_id: str, loader: Callable[[], Awaitable[int]]) -> None:
        k = f"dv:mq:{key_id}:{month()}"
        r = self._r()
        if not await r.exists(k):
            await r.set(k, int(await loader()), nx=True, ex=40 * 86400)

    async def quota(self, key_id: str, monthly_quota: int) -> Decision:
        if monthly_quota <= 0:
            return Decision(ok=True)
        r = self._r()
        k = f"dv:mq:{key_id}:{month()}"
        n = await r.incr(k)
        if n > monthly_quota:
            await r.decr(k)
            return Decision(ok=False, limit=monthly_quota, remaining=0)
        return Decision(ok=True, limit=monthly_quota, remaining=monthly_quota - n)

    def reset(self) -> None:  # testler
        pass


def _make():
    if os.environ.get("REDIS_URL"):
        from fusion_service.jobs.store import get_redis

        return RedisLimiter(get_redis)
    return MemoryLimiter()


# Geriye dönük ad
Limiter = MemoryLimiter
limiter = _make()
