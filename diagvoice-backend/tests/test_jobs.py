"""
F4 — iş kuyruğu (/v1/jobs) ve Redis limiter testleri. Gerçek Redis yerine fakeredis.

  pytest tests/test_jobs.py -q
"""
from __future__ import annotations

import asyncio

import pytest

fakeredis = pytest.importorskip("fakeredis")

from tests.test_apikeys import A, AUDIO, client, make_key, env  # noqa: E402,F401  (fixture'lar)
from fusion_service.apikeys.errors import ApiError  # noqa: E402
from fusion_service.apikeys.limiter import RedisLimiter  # noqa: E402
from fusion_service.jobs import queue as JQ  # noqa: E402
from fusion_service.jobs import store as JS  # noqa: E402


@pytest.fixture()
def redis_env(tmp_path, monkeypatch):
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    JS.set_redis(r)
    monkeypatch.setenv("JOBS_DIR", str(tmp_path))
    yield r
    JS.set_redis(None)


def run(coro):
    return asyncio.run(coro)


def submit(c, key, kind="togg", **form):
    return c.post("/v1/jobs", files={"file": AUDIO}, data={"kind": kind, **form}, headers={"X-API-Key": key})


def test_job_lifecycle(redis_env, env):
    async def t():
        runner = JQ.JobRunner(A._V1_HANDLERS, concurrency=1)
        async with client() as c:
            raw, _, _ = await make_key(c, scopes=["analyze:togg"])
            r = await submit(c, raw)
            assert r.status_code == 202, r.text
            job = r.json()
            assert job["status"] == "queued" and job["position"] == 1
            await runner.start()
            try:
                r = await c.get(f"/v1/jobs/{job['job_id']}?wait=5", headers={"X-API-Key": raw})
            finally:
                await runner.stop()
            assert r.status_code == 200
            j = r.json()
            assert j["status"] == "succeeded", j
            assert j["result"]["audio"]["pred_label"] == "happiness" and j["result"]["partial"] is False
    run(t())


def test_job_submit_with_wait_returns_result(redis_env, env):
    async def t():
        runner = JQ.JobRunner(A._V1_HANDLERS, concurrency=1)
        await runner.start()
        try:
            async with client() as c:
                raw, _, _ = await make_key(c, scopes=["analyze:togg"])
                r = await c.post("/v1/jobs?wait=5", files={"file": AUDIO}, data={"kind": "togg"}, headers={"X-API-Key": raw})
        finally:
            await runner.stop()
        assert r.status_code == 200 and r.json()["status"] == "succeeded"
    run(t())


def test_job_scope_owner_and_cancel(redis_env):
    async def t():
        async with client() as c:
            raw, _, _ = await make_key(c, scopes=["analyze:togg"])
            r = await submit(c, raw, kind="fused")
            assert r.status_code == 403 and r.json()["error"]["code"] == "scope_denied"
            r = await submit(c, raw, kind="nope")
            assert r.status_code == 422
            job_id = (await submit(c, raw)).json()["job_id"]
            other, _, _ = await make_key(c, scopes=["*"])
            assert (await c.get(f"/v1/jobs/{job_id}", headers={"X-API-Key": other})).status_code == 404
            r = await c.delete(f"/v1/jobs/{job_id}", headers={"X-API-Key": raw})
            assert r.status_code == 200 and r.json()["status"] == "cancelled"
            assert await redis_env.llen(JQ.Q) == 0
    run(t())


def test_cancelled_job_is_not_run(redis_env, env):
    _, state = env
    calls = {"n": 0}
    orig = A._fusion_post_multipart_file

    async def counting(*a, **k):
        calls["n"] += 1
        return await orig(*a, **k)

    async def t():
        async with client() as c:
            raw, _, _ = await make_key(c, scopes=["analyze:togg"])
            job_id = (await submit(c, raw)).json()["job_id"]
            await c.delete(f"/v1/jobs/{job_id}", headers={"X-API-Key": raw})
        A._fusion_post_multipart_file = counting
        try:
            await JQ.JobRunner(A._V1_HANDLERS).run_one(job_id)
        finally:
            A._fusion_post_multipart_file = orig
        assert calls["n"] == 0
    run(t())


def test_queue_full(redis_env, monkeypatch):
    monkeypatch.setattr(JQ, "MAX_QUEUE", 1)

    async def t():
        async with client() as c:
            raw, _, _ = await make_key(c, scopes=["analyze:togg"])
            assert (await submit(c, raw)).status_code == 202
            r = await submit(c, raw)
            assert r.status_code == 503 and r.json()["error"]["code"] == "queue_full"
            assert r.headers["Retry-After"] == "30"
    run(t())


def test_recover_requeues_running_jobs(redis_env):
    async def t():
        await redis_env.hset("dv:job:abc", mapping={"id": "abc", "kind": "togg", "status": "running", "attempts": 1,
                                                    "key_id": "k", "created_at": 1})
        await redis_env.sadd(JQ.RUNNING, "abc")
        await JQ.JobRunner(A._V1_HANDLERS)._recover()
        assert await redis_env.hget("dv:job:abc", "status") == "queued"
        assert await redis_env.lrange(JQ.Q, 0, -1) == ["abc"]
    run(t())


def test_jobs_disabled_without_redis():
    JS.set_redis(None)

    async def t():
        async with client() as c:
            raw, _, _ = await make_key(c, scopes=["analyze:togg"])
            r = await submit(c, raw)
            assert r.status_code == 503 and r.json()["error"]["code"] == "jobs_disabled"
    run(t())


@pytest.mark.parametrize("url", ["http://example.com/h", "https://127.0.0.1/h", "https://10.0.0.5/h",
                                 "https://169.254.169.254/latest", "https://localhost/h"])
def test_webhook_url_ssrf_guard(url):
    with pytest.raises(ApiError):
        JQ.validate_webhook_url(url)


# ----------------------------------------------------------------------------- Redis limiter
def test_redis_limiter(redis_env):
    lim = RedisLimiter(lambda: redis_env)

    async def t():
        assert (await lim.hit("k", 2)).ok and (await lim.hit("k", 2)).ok
        d = await lim.hit("k", 2)
        assert not d.ok and d.retry_after >= 1
        assert await lim.acquire("k", 1) and not await lim.acquire("k", 1)
        await lim.release("k", 1)
        assert await lim.active("k") == 0

        async def load():
            return 4

        await lim.ensure_monthly("k", load)
        assert (await lim.quota("k", 5)).ok
        assert not (await lim.quota("k", 5)).ok
    run(t())
