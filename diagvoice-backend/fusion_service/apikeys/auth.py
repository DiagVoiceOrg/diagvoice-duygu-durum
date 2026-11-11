"""
API anahtarı doğrulama middleware'i.

Akış (istek başına):
  1. Anahtar: `Authorization: Bearer dv_...` veya `X-API-Key: dv_...`
  2. Biçim + key_id ile kayıt + sabit zamanlı hash karşılaştırma → yoksa 401
  3. Durum (iptal, süre, müşteri kapalı), pk için Origin, scope → 401/403
  4. Dakikalık istek sınırı → 429 rate_limited (+ Retry-After, X-RateLimit-*)
  5. Aylık kota → 429 quota_exceeded
  6. Eşzamanlı istek sınırı → 429 concurrency_limited
  7. request.state.api_key doldurulur (audit log'a key_id/client_id geçer), kullanım kaydedilir

/v1/* yollarında anahtar zorunludur. Eski uçlarda API_KEY_LEGACY_MODE belirler:
  optional (varsayılan)  anahtar yoksa eskisi gibi çalışır, varsa doğrulanır ve limitler uygulanır
  required               anahtar zorunlu (geçiş tamamlanınca)
"""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import datetime, timezone

from fastapi import Request

from fusion_service.apikeys import keys as K
from fusion_service.apikeys import scopes as S
from fusion_service.apikeys.errors import ApiError, error_response
from fusion_service.apikeys.limiter import limiter
from fusion_service.apikeys.store import ApiKey, get_store

_log = logging.getLogger("diagvoice.apikeys")


def legacy_mode() -> str:
    v = os.environ.get("API_KEY_LEGACY_MODE", "optional").strip().lower()
    return v if v in ("optional", "required") else "optional"


def route_path(request: Request) -> str:
    path = request.scope.get("path", "")
    root = request.scope.get("root_path", "") or ""
    if root and (path == root or path.startswith(root + "/")):
        return path[len(root):] or "/"
    return path


async def authenticate(raw: str, request: Request, scope: str | None) -> ApiKey:
    parsed = K.parse(raw)
    if parsed is None:
        raise ApiError(401, "invalid_api_key", "API anahtarı geçersiz.")
    key = await get_store().get_key(parsed.key_id)
    if key is None or key.type != parsed.type or not K.verify(parsed.secret, key.secret_hash):
        raise ApiError(401, "invalid_api_key", "API anahtarı geçersiz.")
    if key.status != "active":
        raise ApiError(401, "key_revoked", "API anahtarı iptal edilmiş.")
    if key.expires_at is not None:
        exp = key.expires_at if key.expires_at.tzinfo else key.expires_at.replace(tzinfo=timezone.utc)
        if exp <= datetime.now(timezone.utc):
            raise ApiError(401, "key_expired", "API anahtarının süresi dolmuş.")
    if key.client_status != "active":
        raise ApiError(403, "client_disabled", "Bu müşterinin erişimi kapalı.")
    if key.type == "pk":
        origin = (request.headers.get("origin") or "").rstrip("/")
        if not origin or origin not in [o.rstrip("/") for o in key.allowed_origins]:
            raise ApiError(403, "origin_not_allowed", "Bu anahtar bu kaynaktan (Origin) kullanılamaz.")
    if not S.allowed(key.scopes, scope):
        raise ApiError(403, "scope_denied", f"Bu anahtarın '{scope}' erişimi yok.")
    return key


async def _enforce_limits(key: ApiKey) -> dict:
    """Limitleri uygular; yanıta eklenecek başlıkları döner. Aşımda ApiError."""
    d = await limiter.hit(key.key_id, key.limit("rpm"))
    headers = {}
    if d.limit:
        headers = {"X-RateLimit-Limit": str(d.limit), "X-RateLimit-Remaining": str(d.remaining)}
    if not d.ok:
        raise ApiError(429, "rate_limited", "Dakikalık istek sınırı aşıldı.",
                       {**headers, "Retry-After": str(d.retry_after)})
    quota = key.limit("monthly_quota")
    if quota > 0:
        async def _load_month() -> int:
            try:
                return await get_store().monthly_count(key.key_id, limiter.month())
            except Exception:
                _log.exception("aylık kullanım okunamadı key_id=%s", key.key_id)
                return 0

        await limiter.ensure_monthly(key.key_id, _load_month)
        q = await limiter.quota(key.key_id, quota)
        if not q.ok:
            raise ApiError(429, "quota_exceeded", "Aylık kota doldu.", headers)
    if not await limiter.acquire(key.key_id, key.limit("max_concurrent")):
        raise ApiError(429, "concurrency_limited",
                       f"Aynı anda en fazla {key.limit('max_concurrent')} istek gönderilebilir.",
                       {**headers, "Retry-After": "1"})
    return headers


async def api_key_middleware(request: Request, call_next):
    rid = (request.headers.get("x-request-id") or "").strip()[:64] or uuid.uuid4().hex[:16]
    request.state.request_id = rid
    request.state.api_key = None

    path = route_path(request)
    scope, is_v1 = S.scope_for_path(path)
    protected = is_v1 or scope is not None
    if request.method == "OPTIONS" or not protected:
        resp = await call_next(request)
        resp.headers.setdefault("X-Request-ID", rid)
        return resp

    legacy = not is_v1
    raw = K.extract_from_headers(request.headers)
    if raw is None:
        if legacy and legacy_mode() == "optional":
            resp = await call_next(request)
            resp.headers.setdefault("X-Request-ID", rid)
            return resp
        return error_response(request, 401, "missing_api_key",
                              "API anahtarı gerekli: 'Authorization: Bearer <anahtar>' veya 'X-API-Key' başlığı.",
                              legacy=legacy, headers={"WWW-Authenticate": "Bearer"})

    try:
        key = await authenticate(raw, request, scope)
        limit_headers = await _enforce_limits(key)
    except ApiError as e:
        return error_response(request, e.status, e.code, e.message, legacy=legacy, headers=e.headers)

    request.state.api_key = key
    store = get_store()
    error = True
    try:
        resp = await call_next(request)
        error = resp.status_code >= 500
    finally:
        await limiter.release(key.key_id, key.limit("max_concurrent"))
        asyncio.create_task(store.record_usage(key, path, error))
        asyncio.create_task(store.touch(key))
    for h, v in limit_headers.items():
        resp.headers[h] = v
    resp.headers.setdefault("X-Request-ID", rid)
    return resp


def audit_fields(request: Request) -> dict:
    """Audit kaydına eklenecek anahtar bilgisi."""
    key = getattr(request.state, "api_key", None)
    if key is None:
        return {}
    return {"key_id": key.key_id, "client_id": key.client_id, "client_name": key.client_name}
