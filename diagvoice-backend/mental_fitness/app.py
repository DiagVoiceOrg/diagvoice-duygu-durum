import contextlib
import logging
import os
import tempfile
import threading
import time
import traceback
from typing import Any

import fastapi
import joblib
import numpy as np
import uvicorn
from fastapi import File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sklearn.base import BaseEstimator
from starlette.concurrency import run_in_threadpool

from deepseek_transcript import validate_transcript_meaningfulness
from mental_fitness_classifier_v1 import extract_features

app = fastapi.FastAPI()

_cors_origins_raw = os.environ.get(
    "CORS_ALLOW_ORIGINS",
    "https://diagvoice.huseyinalav.me,http://localhost:5173,http://127.0.0.1:5173,http://localhost:5174,http://127.0.0.1:5174,https://duygudurum.diagvoice.com,https://emosyon.diagvoice.com,https://algoritmalar.diagvoice.com,https://yolarkadasim.diagvoice.com",
)
_cors_allow_origins = [o.strip() for o in _cors_origins_raw.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

MODEL_PATH = os.environ.get(
    "MENTAL_FITNESS_MODEL_PATH",
    "/app/models/extratreesclassifier.joblib",
)

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "").strip()
_REQUIRE_DEEPSEEK = os.environ.get("REQUIRE_DEEPSEEK_TRANSCRIPT_VALIDATION", "").strip().lower() in (
    "1",
    "true",
    "yes",
)


class TranscriptMeaningRequest(BaseModel):
    text: str = Field(..., description="STT metni")
    language: str = Field(..., description="UI/STT dili: turkish | english | arabic vb.")

print("Starting mental-fitness service and loading model...")
try:
    _model: BaseEstimator | None = joblib.load(MODEL_PATH)
    print(f"Mental fitness model loaded from {MODEL_PATH}")
except Exception:
    print("!!! FATAL: Failed to load mental fitness model !!!")
    print(traceback.format_exc())
    _model = None

_log = logging.getLogger("diagvoice.mental_fitness")
_log.setLevel(getattr(logging, os.environ.get("DIAGVOICE_LOG_LEVEL", "INFO").upper(), logging.INFO))
if not _log.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [diagvoice.mental_fitness] %(message)s"))
    _log.addHandler(_h)
    _log.propagate = False

_infer_lock = threading.Lock()
_MENTAL_USE_INFER_LOCK = os.environ.get("MENTAL_FITNESS_USE_INFER_LOCK", "1").strip().lower() not in (
    "0",
    "false",
    "no",
)


def _bytes_to_temp_file(audio_bytes: bytes, filename: str) -> str:
    """
    Gelen ses bytes'ını geçici bir dosyaya yazar ve yolunu döner.
    mental_fitness_classifier_v1.extract_features fonksiyonuyla
    aynı veri akışını kullanmak için sadece dosya yolu veriyoruz.
    """
    with tempfile.NamedTemporaryFile(delete=False, suffix=f"_{filename}") as tmp:
        tmp.write(audio_bytes)
        return tmp.name


def _analyze_mental_sync(tmp_path: str) -> dict[str, Any]:
    t0 = time.perf_counter()
    _cm = _infer_lock if _MENTAL_USE_INFER_LOCK else contextlib.nullcontext()
    with _cm:
        t_feat = time.perf_counter()
        feats = extract_features(tmp_path, feature_set="rich")
        feat_ms = (time.perf_counter() - t_feat) * 1000

        if feats is None:
            raise ValueError("Feature extraction returned no features.")
        if _model is None:
            raise RuntimeError("Model not loaded")

        feats_reshaped = np.asarray(feats, dtype=np.float32).reshape(1, -1)

        t_pred = time.perf_counter()
        raw_pred = _model.predict(feats_reshaped)[0]
        probs = None
        mental_fitness_score = None
        if hasattr(_model, "predict_proba"):
            probs_arr = _model.predict_proba(feats_reshaped)[0]
            probs = [float(x) for x in probs_arr.tolist()]

            classes = getattr(_model, "classes_", None)
            if classes is not None:
                classes_list = list(classes)
                if "healthy" in classes_list:
                    healthy_idx = classes_list.index("healthy")
                    mental_fitness_score = float(probs_arr[healthy_idx] * 100.0)
                elif "depression" in classes_list:
                    depression_idx = classes_list.index("depression")
                    mental_fitness_score = float((1.0 - probs_arr[depression_idx]) * 100.0)
        pred_ms = (time.perf_counter() - t_pred) * 1000

        label = None
        pred_id = None
        classes = getattr(_model, "classes_", None)
        if classes is not None:
            classes_list = list(classes)
            if raw_pred in classes_list:
                pred_id = int(classes_list.index(raw_pred))
                label = str(raw_pred)
            else:
                try:
                    idx = int(raw_pred)
                    if 0 <= idx < len(classes_list):
                        pred_id = idx
                        label = str(classes_list[idx])
                except (TypeError, ValueError):
                    label = str(raw_pred)

    total_ms = (time.perf_counter() - t0) * 1000
    _log.info("analyze_mental_done feat_ms=%.0f pred_ms=%.0f total_ms=%.0f", feat_ms, pred_ms, total_ms)

    return {
        "pred_id": pred_id,
        "pred_label": label,
        "probs": probs,
        "mental_fitness_score": None if mental_fitness_score is None else float(f"{mental_fitness_score:.2f}"),
    }


@app.get("/")
async def root():
    return {
        "message": "Mental fitness (canlıda olan) servisi. Ses dosyanızı /analyze-mental endpoint'ine gönderin.",
        "model_path": MODEL_PATH,
        "transcript_validation": (
            "POST /validate-transcript-meaning — önce yerel tekrar filtresi; DeepSeek için "
            "DEEPSEEK_TRANSCRIPT_VALIDATION=1 ve DEEPSEEK_API_KEY gerekir (varsayılan: LLM kapalı)."
        ),
    }


@app.post("/validate-transcript-meaning")
async def validate_transcript_meaning(body: TranscriptMeaningRequest):
    """
    Seçilen dile göre transkript anlamlı konuşma mı — mental fitness öncesi koruma.
    DEEPSEEK_API_KEY yoksa (ve REQUIRE_DEEPSEEK_TRANSCRIPT_VALIDATION kapalıysa) meaningful=true döner (geliştirme uyumu).
    """
    raw = (body.text or "").strip()
    if not raw:
        return {
            "meaningful": True,
            "reason": "empty_transcript_no_text_gate",
            "validation_skipped": False,
        }

    _llm_on = os.environ.get("DEEPSEEK_TRANSCRIPT_VALIDATION", "").strip().lower() in ("1", "true", "yes")
    if _REQUIRE_DEEPSEEK and _llm_on and not DEEPSEEK_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="Transcript validation required (LLM on) but DEEPSEEK_API_KEY is not set.",
        )

    try:
        meaningful, reason = validate_transcript_meaningfulness(
            raw,
            body.language,
            api_key=DEEPSEEK_API_KEY or None,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e

    validation_skipped = not (_llm_on and bool(DEEPSEEK_API_KEY))
    return {"meaningful": meaningful, "reason": reason, "validation_skipped": validation_skipped}


@app.post("/analyze-mental")
async def analyze_mental(file: UploadFile = File(...)):
    if _model is None:
        raise HTTPException(status_code=500, detail="Mental fitness model could not be loaded. Check server logs.")

    tmp_path = None
    try:
        audio_bytes = await file.read()
        if not audio_bytes:
            raise HTTPException(status_code=400, detail="Empty audio file.")

        tmp_path = _bytes_to_temp_file(audio_bytes, file.filename or "audio")
        _log.info("analyze_mental_begin file=%s bytes=%d", file.filename or "", len(audio_bytes))

        try:
            return await run_in_threadpool(_analyze_mental_sync, tmp_path)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Mental fitness analysis failed: {e}") from e
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass


if __name__ == "__main__":
    _port = int(os.environ.get("MENTAL_FITNESS_PORT", "8055"))
    uvicorn.run(app, host="0.0.0.0", port=_port)

