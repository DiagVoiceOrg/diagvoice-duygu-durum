"""
İş sağlığı (benchmark v2) — Flask inference_api'nin FastAPI karşılığı.

Aynı motoru (inference_api.engine) kullanır, aynı HTTP sözleşmesini korur:
  POST /predict   multipart `audio` + form `transcript` → engine.predict_from_uploaded_file
  GET  /health
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from inference_api import engine

app = FastAPI(title="occupational_health (benchmark v2)")

_ALLOWED = (".wav", ".mp3", ".flac", ".ogg", ".m4a", ".webm", ".aac")


def warmup() -> None:
    engine.load_bundle()


@app.get("/health")
async def health():
    try:
        return engine.health_info()
    except Exception as e:  # pragma: no cover - aynı Flask davranışı
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.post("/predict")
async def predict(audio: Optional[UploadFile] = File(None), transcript: str = Form("")):
    if audio is None or not audio.filename:
        return JSONResponse({"error": "multipart alan 'audio' (ses dosyası) gerekli"}, status_code=400)
    ext = Path(audio.filename or "x.wav").suffix.lower() or ".wav"
    if ext not in _ALLOWED:
        return JSONResponse({"error": f"desteklenmeyen uzantı: {ext}"}, status_code=400)
    try:
        _, bundle = await run_in_threadpool(engine.load_bundle)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
            tmp_path = tmp.name
            while chunk := await audio.read(1024 * 1024):
                tmp.write(chunk)
        body = await run_in_threadpool(engine.predict_from_uploaded_file, tmp_path, (transcript or "").strip(), ext)
    except NotImplementedError as e:
        return JSONResponse({"error": str(e), "mode": bundle.get("mode")}, status_code=501)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
    return body
