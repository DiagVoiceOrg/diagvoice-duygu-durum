import contextlib
import io
import logging
import os
import threading
import time
from typing import Any

import joblib
import numpy as np
import torch
import torchaudio
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool
from transformers import pipeline

app = FastAPI()

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

TEXT_SENTIMENT_MODEL = os.environ.get("TEXT_SENTIMENT_MODEL", "kaixkhazaki/turkish-sentiment")
sentiment_pipeline = pipeline("sentiment-analysis", model=TEXT_SENTIMENT_MODEL)

_log = logging.getLogger("diagvoice.text_sentiment")
_log.setLevel(getattr(logging, os.environ.get("DIAGVOICE_LOG_LEVEL", "INFO").upper(), logging.INFO))
if not _log.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [diagvoice.text_sentiment] %(message)s"))
    _log.addHandler(_h)
    _log.propagate = False

_infer_lock = threading.Lock()
_TEXT_SENTIMENT_USE_INFER_LOCK = os.environ.get("TEXT_SENTIMENT_USE_INFER_LOCK", "1").strip().lower() not in (
    "0",
    "false",
    "no",
)


class SentimentRequest(BaseModel):
    text: str


def text_to_valence(label: str, score: float) -> float:
    lab = str(label).upper()
    s = float(score)
    if lab == "POSITIVE":
        return s
    return 1.0 - s


DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

AUDIO_MODEL_PATH = os.environ.get(
    "AUDIO_VALENCE_MODEL_PATH",
    "/app/models/audio_valence_model.joblib",
)

WAV2VEC_BUNDLE = torchaudio.pipelines.WAV2VEC2_BASE
wav2vec_model = None
audio_regressor = None


@app.on_event("startup")
def _load_audio_models():
    global wav2vec_model, audio_regressor
    wav2vec_model = WAV2VEC_BUNDLE.get_model().to(DEVICE).eval()
    if os.path.exists(AUDIO_MODEL_PATH):
        audio_regressor = joblib.load(AUDIO_MODEL_PATH)
    else:
        audio_regressor = None


def _load_wav_from_bytes(b: bytes) -> torch.Tensor:
    wav, sr = torchaudio.load(io.BytesIO(b))
    if wav.size(0) > 1:
        wav = wav.mean(dim=0, keepdim=True)
    if sr != WAV2VEC_BUNDLE.sample_rate:
        wav = torchaudio.transforms.Resample(sr, WAV2VEC_BUNDLE.sample_rate)(wav)
    return wav.to(DEVICE)


@torch.no_grad()
def _embed_wav2vec(wav: torch.Tensor, max_sec: float = 10.0) -> np.ndarray:
    max_len = int(max_sec * WAV2VEC_BUNDLE.sample_rate)
    if wav.size(-1) > max_len:
        wav = wav[..., :max_len]
    feats, _ = wav2vec_model.extract_features(wav)
    last = feats[-1]
    emb = last.mean(dim=1).squeeze(0)
    return emb.detach().cpu().numpy()


def predict_audio_valence(audio_bytes: bytes) -> float:
    if audio_regressor is None or wav2vec_model is None:
        raise RuntimeError("Audio valence model not loaded")
    wav = _load_wav_from_bytes(audio_bytes)
    emb = _embed_wav2vec(wav).reshape(1, -1)
    pred = float(audio_regressor.predict(emb)[0])
    return max(0.0, min(1.0, pred))


def fuse_valence(valence_text: float, valence_audio: float, score: float, mode: str = "dynamic") -> tuple[float, float]:
    vt = float(valence_text)
    va = float(valence_audio)

    if mode == "fixed":
        w_text = 0.92
    else:
        conf = min(1.0, max(0.0, abs(vt - 0.5) * 2.0))
        w_text = 0.85 + 0.10 * conf

    vf = w_text * vt + (1.0 - w_text) * va
    vf = max(0.0, min(1.0, vf))
    return vf, w_text


def _analyze_text_sync(text: str) -> dict[str, Any]:
    t0 = time.perf_counter()
    _cm = _infer_lock if _TEXT_SENTIMENT_USE_INFER_LOCK else contextlib.nullcontext()
    with _cm:
        result = sentiment_pipeline(text)
        label = result[0]["label"]
        score = float(result[0]["score"])
    _log.info("analyze_text_done ms=%.0f", (time.perf_counter() - t0) * 1000)
    return {"sentiment": label, "score": score}


def _analyze_fusion_sync(text: str, audio_bytes: bytes, fusion_mode: str) -> dict[str, Any]:
    t0 = time.perf_counter()
    _cm = _infer_lock if _TEXT_SENTIMENT_USE_INFER_LOCK else contextlib.nullcontext()
    with _cm:
        t_txt = time.perf_counter()
        result = sentiment_pipeline(text)
        label = result[0]["label"]
        score = float(result[0]["score"])
        valence_text = text_to_valence(label, score)
        txt_ms = (time.perf_counter() - t_txt) * 1000

        t_aud = time.perf_counter()
        valence_audio = predict_audio_valence(audio_bytes)
        aud_ms = (time.perf_counter() - t_aud) * 1000

        valence_fused, w_text = fuse_valence(valence_text, valence_audio, score, mode=fusion_mode)

    _log.info(
        "analyze_fusion_done text_ms=%.0f audio_ms=%.0f total_ms=%.0f",
        txt_ms,
        aud_ms,
        (time.perf_counter() - t0) * 1000,
    )

    return {
        "text": {
            "sentiment": label,
            "score": score,
            "valence_text": valence_text,
        },
        "audio": {
            "valence_audio": valence_audio,
        },
        "fusion": {
            "mode": fusion_mode,
            "w_text": w_text,
            "valence_fused": valence_fused,
        },
    }


@app.post("/analyze")
async def analyze_sentiment(request: SentimentRequest):
    return await run_in_threadpool(_analyze_text_sync, request.text)


@app.post("/analyze_fusion")
async def analyze_fusion(
    text: str = Form(...),
    audio: UploadFile = File(...),
    fusion_mode: str = Form("dynamic"),
):
    if audio_regressor is None:
        raise HTTPException(
            status_code=503,
            detail=(
                f"Audio valence model yüklenmedi ({AUDIO_MODEL_PATH} bulunamadı). "
                "AUDIO_VALENCE_MODEL_PATH ile yol belirtin."
            ),
        )
    audio_bytes = await audio.read()
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="Empty audio file.")

    try:
        return await run_in_threadpool(_analyze_fusion_sync, text, audio_bytes, fusion_mode)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@app.get("/")
async def root():
    return {
        "message": "Turkish Sentiment Analysis API. Use /analyze for text-only, /analyze_fusion for text+audio fusion.",
        "text_model": TEXT_SENTIMENT_MODEL,
    }


if __name__ == "__main__":
    import uvicorn

    _port = int(os.environ.get("TEXT_TO_SENTIMENT_PORT", "8050"))
    uvicorn.run(app, host="0.0.0.0", port=_port)
