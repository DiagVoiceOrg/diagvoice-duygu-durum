import contextlib
import logging
import os
import tempfile
import threading
import time
import traceback
from typing import Any

import fastapi
import librosa
import torch
import uvicorn
from fastapi import File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from starlette.concurrency import run_in_threadpool
from transformers import AutoFeatureExtractor, AutoModelForAudioClassification


TARGET_SR = 16000
MAX_SEC = float(os.environ.get("DISEASE_MAX_SEC", "30"))
MAX_SEC = max(1.0, min(300.0, MAX_SEC))
MAX_SAMPLES = int(TARGET_SR * MAX_SEC)

MODEL_DIR = os.environ.get("DISEASE_MODEL_DIR", "/app/models/usye")

_log = logging.getLogger("diagvoice.disease")
_log.setLevel(getattr(logging, os.environ.get("DIAGVOICE_LOG_LEVEL", "INFO").upper(), logging.INFO))
if not _log.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [diagvoice.disease] %(message)s"))
    _log.addHandler(_h)
    _log.propagate = False

_infer_lock = threading.Lock()
_DISEASE_USE_INFER_LOCK = os.environ.get("DISEASE_USE_INFER_LOCK", "1").strip().lower() not in (
    "0",
    "false",
    "no",
)

app = fastapi.FastAPI()

_cors_origins_raw = os.environ.get(
    "CORS_ALLOW_ORIGINS",
    "https://diagvoice.huseyinalav.me,http://localhost:5173,http://127.0.0.1:5173,https://duygudurum.diagvoice.com,https://emosyon.diagvoice.com,https://algoritmalar.diagvoice.com,https://yolarkadasim.diagvoice.com",
)
_cors_allow_origins = [o.strip() for o in _cors_origins_raw.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

print("Starting disease-service and loading model...")
try:
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Using device: {device}")

    feature_extractor = AutoFeatureExtractor.from_pretrained(
        MODEL_DIR,
        local_files_only=True,
    )
    model = AutoModelForAudioClassification.from_pretrained(
        MODEL_DIR,
        local_files_only=True,
    )
    model.to(device)
    model.eval()

    id2label = {int(k): v for k, v in model.config.id2label.items()} if hasattr(model.config, "id2label") else None
except Exception:
    print("!!! FATAL: Failed to load disease model !!!")
    print(traceback.format_exc())
    model = None
    feature_extractor = None
    id2label = None
    device = "cpu"


def _decode_to_float32_16k(path: str):
    from audio_io import load_mono_float32

    y, sr = load_mono_float32(path, sr=TARGET_SR, mono=True)
    y = y.astype("float32")

    if y is None or len(y) == 0:
        raise RuntimeError("Empty audio")

    if sr != TARGET_SR:
        y = librosa.resample(y, orig_sr=sr, target_sr=TARGET_SR).astype("float32")

    if len(y) > MAX_SAMPLES:
        start = (len(y) - MAX_SAMPLES) // 2
        y = y[start : start + MAX_SAMPLES]

    m = float(abs(y).max() + 1e-6)
    y = y / m
    return y


def _analyze_disease_sync(tmp_path: str) -> dict[str, Any]:
    t0 = time.perf_counter()
    _cm = _infer_lock if _DISEASE_USE_INFER_LOCK else contextlib.nullcontext()
    with _cm:
        t_dec = time.perf_counter()
        y = _decode_to_float32_16k(tmp_path)
        decode_ms = (time.perf_counter() - t_dec) * 1000

        if model is None or feature_extractor is None:
            raise RuntimeError("Model not loaded")

        t_inf = time.perf_counter()
        inputs = feature_extractor(y, sampling_rate=TARGET_SR, return_tensors="pt")
        inputs = {k: v.to(device) for k, v in inputs.items()}

        with torch.no_grad():
            out = model(**inputs)
            logits = out.logits.squeeze(0)
            probs = torch.softmax(logits, dim=-1)

        pred_id_raw = int(torch.argmax(probs).item())
        probs_list = probs.detach().cpu().tolist()
        infer_ms = (time.perf_counter() - t_inf) * 1000

        pred_id = 1 - pred_id_raw
        pred_label = id2label.get(pred_id) if isinstance(id2label, dict) else str(pred_id)
        probs_swapped = [probs_list[1], probs_list[0]]

    total_ms = (time.perf_counter() - t0) * 1000
    _log.info("analyze_disease_done decode_ms=%.0f infer_ms=%.0f total_ms=%.0f", decode_ms, infer_ms, total_ms)

    return {
        "pred_id": pred_id,
        "pred_label": pred_label,
        "probs": probs_swapped,
        "labels": id2label,
    }


@app.get("/")
async def root():
    return {
        "message": "Disease (healthy/sick) audio classifier. Send audio to /analyze-disease (multipart/form-data file).",
        "model_dir": MODEL_DIR,
    }


@app.post("/analyze-disease")
async def analyze_disease(file: UploadFile = File(...)):
    if model is None or feature_extractor is None:
        raise HTTPException(status_code=500, detail="Model could not be loaded. Check server logs.")

    tmp_path = None
    try:
        suffix = ""
        if file.filename:
            safe = file.filename.replace("/", "_").replace("\\", "_")
            suffix = f"_{safe}"

        t_recv = time.perf_counter()
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp_path = tmp.name
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                tmp.write(chunk)
        recv_ms = (time.perf_counter() - t_recv) * 1000
        nbytes = os.path.getsize(tmp_path) if tmp_path else 0
        _log.info("analyze_disease_begin file=%s bytes=%d recv_ms=%.0f", file.filename or "", nbytes, recv_ms)

        return await run_in_threadpool(_analyze_disease_sync, tmp_path)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Disease analysis failed: {e}") from e
    finally:
        try:
            if tmp_path and os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass


if __name__ == "__main__":
    _port = int(os.environ.get("DISEASE_SERVICE_PORT", "8054"))
    uvicorn.run(app, host="0.0.0.0", port=_port)
