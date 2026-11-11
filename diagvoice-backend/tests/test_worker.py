"""
F2 — registry.yaml ve dv_worker testleri (GPU/model gerekmez).

  pytest tests/test_worker.py -q
"""
from __future__ import annotations

import asyncio
import hashlib
import importlib
import importlib.util
import os
from pathlib import Path

import httpx
import pytest

from dv_worker import registry as R


# ----------------------------------------------------------------------------- gerçek registry
def test_real_registry_is_consistent():
    reg = R.load(R.DEFAULT_REGISTRY)
    assert set(reg.pipelines["togg"]) == {"emotion_audio", "disease_wurss"}
    assert {m.group for m in reg.models.values()} <= {"gpu", "cpu"}
    for m in reg.models.values():
        for a in m.artifacts:
            assert a.sha256 and len(a.sha256) == 64, f"{m.id}.{a.name} sha256 eksik"
        # Her modül bulunabilir olmalı
        if m.module.endswith(".py"):
            assert (R.BACKEND_ROOT / m.module).is_file(), m.module
        else:
            assert importlib.util.find_spec(m.module.rsplit(".", 1)[0]) is not None, m.module


def test_worker_conf_urls_match_registry():
    """supervisord.worker.conf'taki fusion URL'leri registry'deki model id'lerine işaret etmeli."""
    reg = R.load(R.DEFAULT_REGISTRY)
    conf = (R.BACKEND_ROOT / "supervisord.worker.conf").read_text(encoding="utf-8")
    import re

    for port, mid in re.findall(r"127\.0\.0\.1:(806[01])/([a-z_0-9]+)", conf):
        assert mid in reg.models, f"bilinmeyen model id: {mid}"
        assert reg.models[mid].group == ("gpu" if port == "8060" else "cpu"), mid


# ----------------------------------------------------------------------------- worker (sahte servis)
def _write_registry(tmp: Path, sha: str, *, silent_fail: bool = False) -> Path:
    weights = tmp / "dummy.bin"
    if not weights.exists():
        weights.write_bytes(b"agirliklar")
    reg = tmp / "registry.yaml"
    reg.write_text(
        f"""
model_root: {tmp.as_posix()}
models:
  dummy:
    title: Dummy
    version: v1
    group: gpu
    module: tests/fixtures/dummy_service.py
    startup: [load]
    require: [model]
    artifacts:
      weights: {{path: dummy.bin, sha256: "{sha}", env: DUMMY_MODEL_PATH}}
    env: {{DUMMY_FAIL_SILENTLY: "{'1' if silent_fail else '0'}"}}
pipelines: {{}}
""",
        encoding="utf-8",
    )
    return reg


def _run_worker(monkeypatch, reg: Path):
    monkeypatch.setenv("REGISTRY_PATH", str(reg))
    monkeypatch.setenv("WORKER_GROUP", "gpu")
    monkeypatch.setenv("DV_SHA_CACHE", str(reg.parent / "sha.json"))
    import sys

    for name in [n for n in sys.modules if n.startswith("dvsvc_tests") or n == "dv_worker.app"]:
        del sys.modules[name]
    wa = importlib.import_module("dv_worker.app")

    async def go():
        async with wa.lifespan(wa.app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=wa.app), base_url="http://w") as c:
                ready = await c.get("/ready")
                r = None
                if ready.status_code == 200:
                    r = await c.post("/dummy/analyze", files={"file": ("a.wav", b"12345")})
                return ready, r

    return asyncio.run(go())


def test_worker_loads_and_mounts(tmp_path, monkeypatch):
    sha = hashlib.sha256(b"agirliklar").hexdigest()
    ready, r = _run_worker(monkeypatch, _write_registry(tmp_path, sha))
    assert ready.status_code == 200, ready.text
    assert ready.json()["models"]["dummy"]["state"] == "ready"
    assert r.status_code == 200
    assert r.json() == {"bytes": 5, "loaded_from": str(tmp_path / "dummy.bin")}


def test_worker_rejects_wrong_sha(tmp_path, monkeypatch):
    ready, _ = _run_worker(monkeypatch, _write_registry(tmp_path, "0" * 64))
    assert ready.status_code == 503
    st = ready.json()["models"]["dummy"]
    assert st["state"] == "failed" and "SHA256" in st["error"]


def test_worker_detects_silent_load_failure(tmp_path, monkeypatch):
    sha = hashlib.sha256(b"agirliklar").hexdigest()
    ready, _ = _run_worker(monkeypatch, _write_registry(tmp_path, sha, silent_fail=True))
    assert ready.status_code == 503
    assert "None kaldı: model" in ready.json()["models"]["dummy"]["error"]


def test_missing_artifact_reported(tmp_path, monkeypatch):
    reg = _write_registry(tmp_path, "a" * 64)
    (tmp_path / "dummy.bin").unlink()
    ready, _ = _run_worker(monkeypatch, reg)
    assert ready.status_code == 503
    assert "dosya yok" in ready.json()["models"]["dummy"]["error"]
