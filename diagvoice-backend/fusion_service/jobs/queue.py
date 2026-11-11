"""
Asenkron iş kuyruğu (PROD_PLAN F4) — Redis.

Neden: senkron istek, sıra uzayınca Cloudflare'in 100 sn sınırına takılıyor ve istemci koptuğunda sunucu
işi boşuna bitiriyordu. İş API'sinde istemci işi gönderir (202 + job_id), sonucu sorgular veya webhook alır;
iptal edilen iş hiç çalıştırılmaz.

Redis anahtarları:
  dv:q                kuyruk (LIST, job_id)
  dv:job:<id>         iş kaydı (HASH, 24 saat TTL)
  dv:running          çalışan işler (SET) — süreç çökerse açılışta yeniden kuyruğa alınır
  dv:kq:<key_id>      anahtarın bekleyen/çalışan işleri (SET) — anahtar başı sınır
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import ipaddress
import json
import logging
import os
import shutil
import socket
import time
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Optional
from urllib.parse import urlparse

from fastapi import HTTPException

from fusion_service.apikeys.errors import ApiError
from fusion_service.jobs.store import get_redis

_log = logging.getLogger("diagvoice.jobs")

Q = "dv:q"
RUNNING = "dv:running"
TTL_SEC = int(os.environ.get("JOBS_RESULT_TTL_SEC", str(24 * 3600)))
MAX_QUEUE = int(os.environ.get("JOBS_MAX_QUEUE", "500"))
MAX_PER_KEY = int(os.environ.get("JOBS_MAX_PER_KEY", "50"))
TIMEOUT_SEC = float(os.environ.get("JOBS_TIMEOUT_SEC", "600"))
CONCURRENCY = int(os.environ.get("JOBS_CONCURRENCY", "2"))
MAX_ATTEMPTS = 2

# iş türü → (scope, handler adı, ek form alanları)
KINDS: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "togg": ("analyze:togg", "togg_analyze", ()),
    "fused": ("analyze:fused", "analyze_fused", ("speech_language",)),
    "stt": ("model:stt", "proxy_analyze_voice_to_text", ("speech_language",)),
    "emotion_audio": ("model:emotion_audio", "proxy_analyze_voice_sentiment", ()),
    "disease_wurss": ("model:disease_wurss", "proxy_analyze_disease", ()),
    "depression": ("model:depression", "proxy_analyze_depression", ()),
    "age_gender": ("model:age_gender", "proxy_analyze_age_gender", ()),
    "mental_fitness": ("model:mental_fitness", "proxy_analyze_mental_fitness", ()),
    "emotion_v2": ("model:emotion_v2", "proxy_analyze_emotion_v2", ("speech_language", "transcript")),
    "occupational_health": ("model:occupational_health", "proxy_analyze_benchmark_v2", ("transcript",)),
}


def jobs_dir() -> Path:
    return Path(os.environ.get("JOBS_DIR", "/data/jobs"))


def _job_key(job_id: str) -> str:
    return f"dv:job:{job_id}"


def _now() -> float:
    return round(time.time(), 3)


# --------------------------------------------------------------------------- webhook güvenliği
def validate_webhook_url(url: str) -> str:
    """Yalnızca https ve herkese açık adresler (SSRF: iç ağa, metadata servisine istek atılmasın)."""
    u = urlparse(url)
    if u.scheme != "https" or not u.hostname:
        raise ApiError(422, "invalid_request", "webhook_url https:// ile başlamalı.")
    try:
        infos = socket.getaddrinfo(u.hostname, u.port or 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        raise ApiError(422, "invalid_request", "webhook_url çözümlenemedi.")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            raise ApiError(422, "invalid_request", "webhook_url herkese açık bir adres olmalı.")
    return url


def sign(body: bytes) -> str:
    secret = (os.environ.get("JOBS_WEBHOOK_SECRET") or os.environ.get("API_KEY_PEPPER") or "dev").encode()
    return "sha256=" + hmac.new(secret, body, hashlib.sha256).hexdigest()


# --------------------------------------------------------------------------- istemci tarafı
async def submit(*, key, kind: str, filename: str, content: bytes, content_type: str,
                 params: dict[str, str], webhook_url: Optional[str]) -> dict:
    if kind not in KINDS:
        raise ApiError(422, "invalid_request", f"Bilinmeyen iş türü: {kind}. Geçerli: {', '.join(KINDS)}")
    r = get_redis()
    if await r.llen(Q) >= MAX_QUEUE:
        raise ApiError(503, "queue_full", "İş kuyruğu dolu, daha sonra tekrar deneyin.", {"Retry-After": "30"})
    kq = f"dv:kq:{key.key_id}"
    if await r.scard(kq) >= MAX_PER_KEY:
        raise ApiError(429, "too_many_jobs", f"Bu anahtarın aynı anda en fazla {MAX_PER_KEY} bekleyen işi olabilir.",
                       {"Retry-After": "10"})
    job_id = uuid.uuid4().hex
    d = jobs_dir() / job_id
    d.mkdir(parents=True, exist_ok=True)
    safe = (filename or "audio").replace("/", "_").replace("\\", "_")[:120]
    (d / safe).write_bytes(content)
    rec = {
        "id": job_id, "kind": kind, "status": "queued", "key_id": key.key_id, "client_id": key.client_id,
        "filename": safe, "content_type": content_type or "application/octet-stream",
        "params": json.dumps(params, ensure_ascii=False), "webhook_url": webhook_url or "",
        "created_at": _now(), "attempts": 0,
    }
    pipe = r.pipeline()
    pipe.hset(_job_key(job_id), mapping=rec)
    pipe.expire(_job_key(job_id), TTL_SEC)
    pipe.sadd(kq, job_id)
    pipe.expire(kq, TTL_SEC)
    pipe.rpush(Q, job_id)
    await pipe.execute()
    return await get(job_id, key.key_id)


def _public(h: dict, position: Optional[int]) -> dict:
    out: dict[str, Any] = {
        "job_id": h["id"],
        "kind": h["kind"],
        "status": h["status"],
        "created_at": float(h["created_at"]),
    }
    if position is not None:
        out["position"] = position
    for f in ("started_at", "finished_at"):
        if h.get(f):
            out[f] = float(h[f])
    if h.get("result"):
        out["result"] = json.loads(h["result"])
    if h.get("error"):
        out["error"] = json.loads(h["error"])
    return out


async def get(job_id: str, key_id: str) -> Optional[dict]:
    r = get_redis()
    h = await r.hgetall(_job_key(job_id))
    if not h or h.get("key_id") != key_id:
        return None
    pos = None
    if h["status"] == "queued":
        p = await r.lpos(Q, job_id)
        pos = None if p is None else int(p) + 1
    return _public(h, pos)


async def cancel(job_id: str, key_id: str) -> Optional[dict]:
    r = get_redis()
    h = await r.hgetall(_job_key(job_id))
    if not h or h.get("key_id") != key_id:
        return None
    if h["status"] == "queued":
        await r.lrem(Q, 0, job_id)
        await r.hset(_job_key(job_id), mapping={"status": "cancelled", "finished_at": _now()})
        await r.srem(f"dv:kq:{key_id}", job_id)
        shutil.rmtree(jobs_dir() / job_id, ignore_errors=True)
    return await get(job_id, key_id)


async def wait_for(job_id: str, key_id: str, seconds: float) -> Optional[dict]:
    deadline = time.monotonic() + max(0.0, seconds)
    while True:
        j = await get(job_id, key_id)
        if j is None or j["status"] in ("succeeded", "failed", "cancelled") or time.monotonic() >= deadline:
            return j
        await asyncio.sleep(0.25)


# --------------------------------------------------------------------------- çalıştırıcı
def _fake_request(path: str):
    from starlette.requests import Request

    scope = {"type": "http", "method": "POST", "path": path, "root_path": "", "headers": [],
             "query_string": b"", "client": None, "server": None, "scheme": "http"}
    return Request(scope)


async def _normalize(result) -> tuple[int, Any]:
    from fastapi.responses import JSONResponse

    if isinstance(result, JSONResponse):
        try:
            return result.status_code, json.loads(result.body)
        except Exception:
            return result.status_code, {"raw": result.body.decode("utf-8", "replace")[:2000]}
    return 200, result


class JobRunner:
    def __init__(self, handlers: SimpleNamespace, concurrency: int = CONCURRENCY) -> None:
        self.h = handlers
        self.concurrency = max(1, concurrency)
        self._tasks: list[asyncio.Task] = []
        self._stop = asyncio.Event()

    async def start(self) -> None:
        await self._recover()
        self._tasks = [asyncio.create_task(self._loop(i)) for i in range(self.concurrency)]
        _log.info("job_runner_started concurrency=%d", self.concurrency)

    async def stop(self) -> None:
        self._stop.set()
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)

    async def _recover(self) -> None:
        r = get_redis()
        for job_id in await r.smembers(RUNNING):
            h = await r.hgetall(_job_key(job_id))
            await r.srem(RUNNING, job_id)
            if not h:
                continue
            if int(h.get("attempts", 0)) < MAX_ATTEMPTS:
                await r.hset(_job_key(job_id), mapping={"status": "queued"})
                await r.lpush(Q, job_id)
                _log.warning("job_requeued id=%s", job_id)
            else:
                await self._finish(job_id, h, "failed", error={"code": "worker_crashed", "message": "İş çalışırken sunucu yeniden başladı."})

    async def _loop(self, n: int) -> None:
        r = get_redis()
        while not self._stop.is_set():
            try:
                item = await r.blpop([Q], timeout=5)
                if not item:
                    continue
                await self.run_one(item[1])
            except asyncio.CancelledError:
                raise
            except Exception:
                _log.exception("job_loop_error worker=%d", n)
                await asyncio.sleep(1)

    async def run_one(self, job_id: str) -> None:
        r = get_redis()
        h = await r.hgetall(_job_key(job_id))
        if not h or h.get("status") != "queued":
            return  # iptal edilmiş veya süresi dolmuş
        attempts = int(h.get("attempts", 0)) + 1
        await r.hset(_job_key(job_id), mapping={"status": "running", "started_at": _now(), "attempts": attempts})
        await r.sadd(RUNNING, job_id)
        t0 = time.perf_counter()
        try:
            status, body = await asyncio.wait_for(self._execute(h), timeout=TIMEOUT_SEC)
            if status >= 400:
                await self._finish(job_id, h, "failed", error={"code": "analysis_failed", "http_status": status, "details": body})
            else:
                if isinstance(body, dict) and h["kind"] in ("togg", "fused"):
                    body["partial"] = any(body.get(k) for k in body if k.endswith("_error"))
                await self._finish(job_id, h, "succeeded", result=body)
        except asyncio.TimeoutError:
            await self._finish(job_id, h, "failed", error={"code": "timeout", "message": f"İş {int(TIMEOUT_SEC)} sn içinde bitmedi."})
        except HTTPException as e:
            await self._finish(job_id, h, "failed", error={"code": "analysis_failed", "http_status": e.status_code,
                                                           "details": e.detail})
        except Exception as e:
            _log.exception("job_failed id=%s", job_id)
            await self._finish(job_id, h, "failed", error={"code": "internal_error", "message": type(e).__name__})
        finally:
            await r.srem(RUNNING, job_id)
            _log.info("job_done id=%s kind=%s ms=%.0f", job_id, h.get("kind"), (time.perf_counter() - t0) * 1000)

    async def _execute(self, h: dict) -> tuple[int, Any]:
        from starlette.datastructures import Headers, UploadFile

        kind = h["kind"]
        _, handler_name, extra = KINDS[kind]
        params = json.loads(h.get("params") or "{}")
        path = jobs_dir() / h["id"] / h["filename"]
        request = _fake_request(f"/v1/jobs/{kind}")
        with open(path, "rb") as fh:
            up = UploadFile(file=fh, filename=h["filename"], headers=Headers({"content-type": h["content_type"]}))
            fn = getattr(self.h, handler_name)
            if kind == "fused" or kind == "stt":
                res = await fn(request, up, params.get("speech_language") or "tr")
            elif kind == "emotion_v2":
                res = await fn(request, up, params.get("speech_language") or "tr", None, params.get("transcript"))
            elif kind == "occupational_health":
                res = await fn(request, up, params.get("transcript") or "")
            else:
                res = await fn(request, up)
        return await _normalize(res)

    async def _finish(self, job_id: str, h: dict, status: str, *, result: Any = None, error: Any = None) -> None:
        r = get_redis()
        fields: dict[str, Any] = {"status": status, "finished_at": _now()}
        if result is not None:
            fields["result"] = json.dumps(result, ensure_ascii=False, default=str)
        if error is not None:
            fields["error"] = json.dumps(error, ensure_ascii=False, default=str)
        await r.hset(_job_key(job_id), mapping=fields)
        await r.expire(_job_key(job_id), TTL_SEC)
        await r.srem(f"dv:kq:{h.get('key_id')}", job_id)
        shutil.rmtree(jobs_dir() / job_id, ignore_errors=True)
        if h.get("webhook_url"):
            asyncio.create_task(self._webhook(h["webhook_url"], job_id, status, result, error))

    async def _webhook(self, url: str, job_id: str, status: str, result: Any, error: Any) -> None:
        import httpx

        body = json.dumps({"job_id": job_id, "status": status, "result": result, "error": error},
                          ensure_ascii=False, default=str).encode("utf-8")
        headers = {"Content-Type": "application/json", "X-DiagVoice-Signature": sign(body), "X-DiagVoice-Job-ID": job_id}
        for attempt in range(3):
            try:
                validate_webhook_url(url)  # DNS değişmiş olabilir: her denemede yeniden doğrula
                async with httpx.AsyncClient(timeout=10, follow_redirects=False) as c:
                    resp = await c.post(url, content=body, headers=headers)
                if resp.status_code < 500:
                    return
            except Exception as e:
                _log.warning("webhook_failed id=%s attempt=%d err=%s", job_id, attempt + 1, type(e).__name__)
            await asyncio.sleep(2 ** attempt)
