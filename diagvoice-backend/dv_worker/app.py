"""
DiagVoice model worker — registry'deki bir gruptaki (gpu | cpu) tüm servisleri TEK süreçte çalıştırır.

Önceden her model ayrı bir Python süreciydi (8 GPU süreci = 8 CUDA context + 8× RAM). Worker:
  - registry.yaml'dan grubunu okur, SHA256 doğrular,
  - servis modüllerini sırayla import eder (model kodu değişmeden), startup/lifespan'lerini çalıştırır,
  - her servisin mevcut FastAPI uygulamasını `/<model_id>` altına bağlar.

Çalıştırma:
  WORKER_GROUP=gpu WORKER_PORT=8060 python -m dv_worker.app

Uçlar:
  GET /health                  süreç ayakta mı
  GET /ready                   model bazında durum; hepsi yüklüyse 200, değilse 503
  ANY /<model_id>/...          servisin kendi uçları (ör. /emotion_audio/analyze-audio)

Ortam: WORKER_GROUP, WORKER_PORT, REGISTRY_PATH, MODEL_ROOT, WORKER_MODELS (virgüllü filtre, isteğe bağlı),
       DV_VERIFY_SHA (varsayılan 1).
"""
from __future__ import annotations

import importlib
import importlib.util
import inspect
import logging
import os
import sys
import time
from contextlib import AsyncExitStack, asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from dv_worker import registry as R

logging.basicConfig(level=os.environ.get("DIAGVOICE_LOG_LEVEL", "INFO").upper(),
                    format="%(asctime)s %(levelname)s %(name)s %(message)s")
_log = logging.getLogger("diagvoice.worker")

GROUP = os.environ.get("WORKER_GROUP", "gpu").strip()
PORT = int(os.environ.get("WORKER_PORT", "8060"))
ONLY = {s.strip() for s in os.environ.get("WORKER_MODELS", "").split(",") if s.strip()}
VERIFY_SHA = os.environ.get("DV_VERIFY_SHA", "1").strip().lower() not in ("0", "false", "no")

_status: dict[str, dict[str, Any]] = {}


def _import_module(spec: str):
    """`paket.modul` veya backend köküne göre `klasor/dosya.py`."""
    if spec.endswith(".py"):
        path = R.BACKEND_ROOT / spec
        name = "dvsvc_" + spec.replace("/", "_").replace("-", "_").removesuffix(".py")
        if name in sys.modules:
            return sys.modules[name]
        s = importlib.util.spec_from_file_location(name, path)
        mod = importlib.util.module_from_spec(s)
        sys.modules[name] = mod
        try:
            s.loader.exec_module(mod)
        except BaseException:
            sys.modules.pop(name, None)
            raise
        return mod
    return importlib.import_module(spec)


def _apply_env(entry: R.ModelEntry) -> None:
    for a in entry.artifacts:
        if a.env:
            os.environ[a.env] = str(a.path)
    for k, v in entry.env_dirs.items():
        os.environ[k] = str(v)
    for k, v in entry.env.items():
        os.environ[k] = v
    for k, v in entry.env_urls.items():
        os.environ[k] = f"http://127.0.0.1:{PORT}{v}"
    for p in entry.sys_path:
        if str(p) not in sys.path:
            sys.path.insert(0, str(p))


async def _load_one(app: FastAPI, stack: AsyncExitStack, entry: R.ModelEntry) -> None:
    st = _status[entry.id] = {"title": entry.title, "version": entry.version, "state": "loading", "error": None}
    t0 = time.perf_counter()
    try:
        if VERIFY_SHA:
            errs = await run_in_threadpool(R.verify, entry)
            if errs:
                raise RuntimeError("; ".join(errs))
        _apply_env(entry)
        mod = await run_in_threadpool(_import_module, entry.module)
        for fn_name in entry.startup:
            fn = getattr(mod, fn_name)
            if inspect.iscoroutinefunction(fn):
                await fn()
            else:
                await run_in_threadpool(fn)
        missing = [a for a in entry.require if getattr(mod, a, None) is None]
        if missing:
            raise RuntimeError(f"model yüklenemedi (None kaldı: {', '.join(missing)}); servis logunu kontrol edin")
        sub = getattr(mod, "app")
        if entry.lifespan:
            await stack.enter_async_context(getattr(mod, entry.lifespan)(sub))
            err = getattr(sub.state, "load_error", None)
            if err:
                raise RuntimeError(str(err))
        app.mount(f"/{entry.id}", sub)
        st.update(state="ready", load_sec=round(time.perf_counter() - t0, 1))
        _log.info("model_ready id=%s load_sec=%.1f", entry.id, time.perf_counter() - t0)
    except BaseException as e:  # SystemExit dahil: bir model diğerlerini düşürmesin
        st.update(state="failed", error=f"{type(e).__name__}: {e}"[:1000], load_sec=round(time.perf_counter() - t0, 1))
        _log.exception("model_failed id=%s", entry.id)
        if isinstance(e, KeyboardInterrupt):
            raise


@asynccontextmanager
async def lifespan(app: FastAPI):
    reg = R.load()
    entries = [e for e in reg.group(GROUP) if not ONLY or e.id in ONLY]
    _log.info("worker_start group=%s port=%s models=%s registry=%s", GROUP, PORT, [e.id for e in entries], reg.path)
    for e in entries:
        _status[e.id] = {"title": e.title, "version": e.version, "state": "pending", "error": None}
    async with AsyncExitStack() as stack:
        for e in entries:
            await _load_one(app, stack, e)
        _log.info("worker_loaded group=%s ready=%d/%d", GROUP,
                  sum(1 for s in _status.values() if s["state"] == "ready"), len(entries))
        yield


app = FastAPI(title=f"DiagVoice worker ({GROUP})", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"ok": True, "group": GROUP}


@app.get("/ready")
async def ready():
    ok = bool(_status) and all(s["state"] == "ready" for s in _status.values())
    return JSONResponse({"ready": ok, "group": GROUP, "models": _status}, status_code=200 if ok else 503)


if __name__ == "__main__":
    import uvicorn

    # Tek konteyner (supervisord): 127.0.0.1. Ayrı konteynerler (docker-compose): WORKER_HOST=0.0.0.0 (yalnızca iç ağ).
    uvicorn.run(app, host=os.environ.get("WORKER_HOST", "127.0.0.1"), port=PORT, log_level="info")
