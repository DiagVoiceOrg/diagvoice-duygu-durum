"""
Anahtar başına rate limit, eşzamanlılık sınırı ve aylık kota — bellek içi.

Tek fusion süreci (uvicorn tek worker) için doğrudur. F4'te aynı arayüz Redis ile değiştirilecek;
çağıran kod (auth.py) değişmez.
"""
from __future__ import annotations

import asyncio
import math
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class Decision:
    ok: bool
    limit: int = 0
    remaining: int = 0
    retry_after: int = 0


@dataclass
class _Bucket:
    tokens: float
    updated: float = field(default_factory=time.monotonic)


class Limiter:
    def __init__(self) -> None:
        self._buckets: dict[str, _Bucket] = {}
        self._active: dict[str, int] = {}
        self._monthly: dict[tuple[str, str], int] = {}
        self._lock = asyncio.Lock()

    # --- dakikalık istek sınırı (token bucket: kapasite = rpm, dolum = rpm/60 per sn) ---
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
            wait = math.ceil((1.0 - b.tokens) / rate)
            return Decision(ok=False, limit=rpm, remaining=0, retry_after=max(1, wait))

    # --- eşzamanlı istek sınırı ---
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

    def active(self, key_id: str) -> int:
        return self._active.get(key_id, 0)

    # --- aylık kota ---
    @staticmethod
    def month() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m")

    def seed_monthly(self, key_id: str, count: int) -> None:
        """Süreç açılışında Mongo'daki bu ayın kullanımıyla başlat."""
        k = (key_id, self.month())
        self._monthly[k] = max(self._monthly.get(k, 0), int(count))

    def has_monthly(self, key_id: str) -> bool:
        return (key_id, self.month()) in self._monthly

    async def quota(self, key_id: str, monthly_quota: int) -> Decision:
        if monthly_quota <= 0:
            return Decision(ok=True)
        k = (key_id, self.month())
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


limiter = Limiter()
