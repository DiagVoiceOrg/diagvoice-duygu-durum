"""
F1 — API anahtarı, scope, limit ve /v1 testleri.

Gerçek fusion `app`'i kullanılır; Mongo yerine bellek içi anahtar deposu, iç model servisleri yerine
sahte upstream yanıtları. GPU/model gerekmez.

  pytest tests/test_apikeys.py -q
"""
from __future__ import annotations

import asyncio
import os

os.environ.setdefault("CMS_ENABLED", "1")
os.environ["AUDIT_LOG_ENABLED"] = "0"
os.environ["AUDIT_AUDIO_STORAGE_ENABLED"] = "0"
os.environ.setdefault("MONGO_URI", "mongodb://127.0.0.1:1")
os.environ["JWT_SECRET"] = "test-jwt-secret-0123456789abcdef0123456789"
os.environ.pop("DIAGVOICE_ENV", None)
os.environ.pop("REDIS_URL", None)  # konteynerde çalışırken gerçek Redis'e dokunma (testler fakeredis kullanır)

import httpx  # noqa: E402
import pytest  # noqa: E402

import fusion_service.app as A  # noqa: E402
from cms.auth_utils import create_access_token  # noqa: E402
from fusion_service.apikeys import keys as K  # noqa: E402
from fusion_service.apikeys import security  # noqa: E402
from fusion_service.apikeys.limiter import limiter  # noqa: E402
from fusion_service.apikeys.store import MemoryKeyStore, set_store  # noqa: E402

AUDIO = ("kayit.m4a", b"\x00" * 2048, "audio/mp4")
FAKE_AUDIO = {"pred_id": 2, "pred_label": "happiness", "probs": [0.1, 0.1, 0.7, 0.1], "intensity": 0.4}
FAKE_DISEASE = {"pred_id": 0, "pred_label": "healthy", "probs": [0.9, 0.1]}


@pytest.fixture(autouse=True)
def env(monkeypatch):
    store = MemoryKeyStore()
    set_store(store)
    limiter.reset()
    monkeypatch.setattr(A, "_upstream_httpx", object())
    state = {"delay": 0.0, "disease_error": None}

    async def fake_post(client, url, tmp_path, **kw):
        if state["delay"]:
            await asyncio.sleep(state["delay"])
        if url == A.DISEASE_SERVICE_URL:
            if state["disease_error"]:
                return None, state["disease_error"]
            return dict(FAKE_DISEASE), None
        return dict(FAKE_AUDIO), None

    monkeypatch.setattr(A, "_fusion_post_multipart_file", fake_post)
    monkeypatch.setenv("API_KEY_LEGACY_MODE", "optional")
    yield store, state


def run(coro):
    return asyncio.run(coro)


def client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=A.app), base_url="http://test")


ADMIN = {"Authorization": "Bearer " + create_access_token("admin@test", "admin")}


async def make_key(c: httpx.AsyncClient, *, scopes=("analyze:togg",), key_type="sk", limits=None, origins=None):
    r = await c.post("/admin/clients", json={"name": "TOGG"}, headers=ADMIN)
    assert r.status_code == 201, r.text
    cid = r.json()["id"]
    body = {"type": key_type, "name": "test", "scopes": list(scopes), "limits": limits or {}}
    if origins:
        body["allowed_origins"] = origins
    r = await c.post(f"/admin/clients/{cid}/keys", json=body, headers=ADMIN)
    assert r.status_code == 201, r.text
    return r.json()["api_key"], r.json()["key"]["key_id"], cid


def togg(c, key=None, path="/v1/analyze/togg", headers=None):
    h = dict(headers or {})
    if key:
        h["Authorization"] = f"Bearer {key}"
    return c.post(path, files={"file": AUDIO}, headers=h)


# ----------------------------------------------------------------------------- anahtar biçimi
def test_key_format_and_verify():
    raw, key_id, h = K.generate("sk")
    p = K.parse(raw)
    assert p and p.type == "sk" and p.key_id == key_id
    assert K.verify(p.secret, h)
    assert not K.verify(p.secret[:-1] + "x", h)
    assert K.parse("dv_sk_short") is None
    assert K.extract_from_headers({"x-api-key": raw}) == raw
    assert K.extract_from_headers({"authorization": f"Bearer {raw}"}) == raw


# ----------------------------------------------------------------------------- 401 / 403
def test_v1_requires_key():
    async def t():
        async with client() as c:
            r = await togg(c)
            assert r.status_code == 401
            err = r.json()["error"]
            assert err["code"] == "missing_api_key" and err["request_id"]
            assert r.headers["X-Request-ID"] == err["request_id"]
            r = await togg(c, "dv_sk_abcdefgh_" + "A" * 32)
            assert r.status_code == 401 and r.json()["error"]["code"] == "invalid_api_key"
    run(t())


def test_valid_key_and_partial_flag(env):
    _, state = env

    async def t():
        async with client() as c:
            raw, _, _ = await make_key(c)
            r = await togg(c, raw)
            assert r.status_code == 200, r.text
            b = r.json()
            assert b["audio"]["pred_label"] == "happiness" and b["partial"] is False
            assert "X-RateLimit-Limit" in r.headers
            state["disease_error"] = "boom"
            r = await togg(c, raw)
            assert r.status_code == 200 and r.json()["partial"] is True and r.json()["disease"] is None
    run(t())


def test_scope_denied():
    async def t():
        async with client() as c:
            raw, _, _ = await make_key(c, scopes=["analyze:togg"])
            r = await c.post("/v1/analyze/text_sentiment", json={"text": "merhaba"}, headers={"X-API-Key": raw})
            assert r.status_code == 403 and r.json()["error"]["code"] == "scope_denied"
            r = await c.get("/v1/models", headers={"X-API-Key": raw})
            assert r.status_code == 200
            assert [m["id"] for m in r.json()["models"]] == ["togg"]
            r = await c.get("/v1/me", headers={"X-API-Key": raw})
            assert r.status_code == 200 and r.json()["client"] == "TOGG"
    run(t())


def test_revoke_and_rotate():
    async def t():
        async with client() as c:
            raw, key_id, _ = await make_key(c)
            r = await c.post(f"/admin/keys/{key_id}/rotate", headers=ADMIN)
            assert r.status_code == 201
            new_raw = r.json()["api_key"]
            assert (await togg(c, raw)).json()["error"]["code"] == "key_revoked"
            assert (await togg(c, new_raw)).status_code == 200
            new_id = r.json()["key"]["key_id"]
            assert (await c.post(f"/admin/keys/{new_id}/revoke", headers=ADMIN)).status_code == 200
            assert (await togg(c, new_raw)).status_code == 401
    run(t())


def test_disabled_client():
    async def t():
        async with client() as c:
            raw, _, cid = await make_key(c)
            r = await c.patch(f"/admin/clients/{cid}", json={"status": "disabled"}, headers=ADMIN)
            assert r.status_code == 200
            r = await togg(c, raw)
            assert r.status_code == 403 and r.json()["error"]["code"] == "client_disabled"
    run(t())


def test_admin_requires_admin_token():
    async def t():
        async with client() as c:
            assert (await c.get("/admin/keys")).status_code == 401
            user = {"Authorization": "Bearer " + create_access_token("u@test", "editor")}
            assert (await c.get("/admin/keys", headers=user)).status_code == 403
            assert (await c.post("/admin/clients", json={"name": "X"}, headers=ADMIN)).status_code == 422
            r = await c.post("/admin/clients", json={"name": "XY"}, headers=ADMIN)
            r = await c.post(f"/admin/clients/{r.json()['id']}/keys", json={"name": "kk", "scopes": ["yok:boyle"]}, headers=ADMIN)
            assert r.status_code == 400
    run(t())


# ----------------------------------------------------------------------------- 429
def test_rate_limit():
    async def t():
        async with client() as c:
            raw, _, _ = await make_key(c, limits={"rpm": 2})
            assert (await togg(c, raw)).status_code == 200
            assert (await togg(c, raw)).status_code == 200
            r = await togg(c, raw)
            assert r.status_code == 429 and r.json()["error"]["code"] == "rate_limited"
            assert int(r.headers["Retry-After"]) >= 1
    run(t())


def test_monthly_quota():
    async def t():
        async with client() as c:
            raw, _, _ = await make_key(c, limits={"monthly_quota": 1})
            assert (await togg(c, raw)).status_code == 200
            r = await togg(c, raw)
            assert r.status_code == 429 and r.json()["error"]["code"] == "quota_exceeded"
    run(t())


def test_concurrency_limit(env):
    _, state = env
    state["delay"] = 0.3

    async def t():
        async with client() as c:
            raw, key_id, _ = await make_key(c, limits={"max_concurrent": 1})
            r1, r2 = await asyncio.gather(togg(c, raw), togg(c, raw))
            codes = sorted([r1.status_code, r2.status_code])
            assert codes == [200, 429]
            limited = r1 if r1.status_code == 429 else r2
            assert limited.json()["error"]["code"] == "concurrency_limited"
            assert await limiter.active(key_id) == 0  # slot geri bırakıldı
    run(t())


# ----------------------------------------------------------------------------- pk / origin / CORS
def test_publishable_key_origin():
    async def t():
        async with client() as c:
            origin = "https://algoritmalar.diagvoice.com"
            raw, _, _ = await make_key(c, key_type="pk", origins=[origin])
            r = await togg(c, raw)
            assert r.status_code == 403 and r.json()["error"]["code"] == "origin_not_allowed"
            r = await togg(c, raw, headers={"Origin": origin})
            assert r.status_code == 200
    run(t())


def test_cors_headers_on_401():
    async def t():
        async with client() as c:
            r = await togg(c, headers={"Origin": "https://algoritmalar.diagvoice.com"})
            assert r.status_code == 401
            assert r.headers.get("access-control-allow-origin") == "https://algoritmalar.diagvoice.com"
    run(t())


# ----------------------------------------------------------------------------- eski uçlar
def test_legacy_optional_and_required(monkeypatch):
    async def t():
        async with client() as c:
            r = await togg(c, path="/togg-analyze")
            assert r.status_code == 200 and "partial" not in r.json()  # eski yanıt biçimi aynen
            r = await togg(c, "dv_sk_abcdefgh_" + "A" * 32, path="/togg-analyze")
            assert r.status_code == 401 and r.json()["detail"]  # eski istemciler için 'detail' de var
            raw, _, _ = await make_key(c, scopes=["analyze:fused"])
            r = await togg(c, raw, path="/togg-analyze")
            assert r.status_code == 403
            monkeypatch.setenv("API_KEY_LEGACY_MODE", "required")
            r = await togg(c, path="/togg-analyze")
            assert r.status_code == 401 and r.json()["error"]["code"] == "missing_api_key"
    run(t())


def test_unprotected_paths_stay_open():
    async def t():
        async with client() as c:
            assert (await c.get("/openapi.json")).status_code == 200
    run(t())


# ----------------------------------------------------------------------------- hata biçimi
def test_v1_validation_error_format():
    async def t():
        async with client() as c:
            raw, _, _ = await make_key(c)
            r = await c.post("/v1/analyze/togg", headers={"X-API-Key": raw})
            assert r.status_code == 422
            assert r.json()["error"]["code"] == "invalid_request"
    run(t())


# ----------------------------------------------------------------------------- registry'den otomatik uçlar
def test_registry_model_route(monkeypatch):
    from fusion_service.apikeys import scopes as S

    monkeypatch.setitem(S.REGISTRY_V1, "voice_fatigue", {"group": "cpu", "endpoint": "/analyze", "input": "audio", "title": "VF"})
    monkeypatch.setitem(S.MODELS, "model:voice_fatigue", {"title": "VF", "path": "/v1/analyze/voice_fatigue"})
    monkeypatch.setitem(S.V1_PATHS, "/v1/analyze/voice_fatigue", "model:voice_fatigue")
    seen = {}

    class FakeClient:
        async def post(self, url, files=None, data=None, json=None):
            seen["url"] = url
            return httpx.Response(200, json={"score": 0.5})

    monkeypatch.setattr(A, "_upstream_httpx", FakeClient())  # _upstream_client() bunu döner

    async def t():
        async with client() as c:
            raw, _, _ = await make_key(c, scopes=["model:voice_fatigue"])
            r = await togg(c, raw, path="/v1/analyze/voice_fatigue")
            return r

    r = run(t())
    assert r.status_code == 200, r.text
    assert r.json() == {"score": 0.5}
    assert seen["url"].endswith(":8061/voice_fatigue/analyze")


# ----------------------------------------------------------------------------- sır kontrolü
def test_weak_secrets_block_production(monkeypatch):
    monkeypatch.setenv("DIAGVOICE_ENV", "production")
    monkeypatch.setenv("API_KEY_PEPPER", "short")
    with pytest.raises(SystemExit):
        security.check_or_exit(cms_enabled=False)
    monkeypatch.setenv("API_KEY_PEPPER", "x" * 40)
    security.check_or_exit(cms_enabled=False)
    monkeypatch.setenv("DIAGVOICE_ENV", "")
    monkeypatch.setenv("API_KEY_PEPPER", "")
    security.check_or_exit(cms_enabled=False)  # geliştirmede yalnızca uyarı
