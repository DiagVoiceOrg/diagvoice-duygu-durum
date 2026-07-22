from __future__ import annotations

import asyncio
import logging
import os
import sys
import tempfile
import threading
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

_BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from code.stt.language import normalize_speech_language_code, resolve_whisper_language
from emotion_runtime import MultimodalEmotionPredictor, RuntimeConfig

_log = logging.getLogger("diagvoice.emotion_v2")
_log.setLevel(getattr(logging, os.environ.get("DIAGVOICE_LOG_LEVEL", "INFO").upper(), logging.INFO))
if not _log.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [diagvoice.emotion_v2] %(message)s"))
    _log.addHandler(_h)
    _log.propagate = False

MODEL_PATH = os.environ.get(
    "EMOTION_V2_MODEL_PATH",
    "/app/models/final_multimodal_stacking_model.joblib",
)
DEVICE = os.environ.get("EMOTION_V2_DEVICE") or None
MAX_UPLOAD_MB = int(os.environ.get("EMOTION_V2_MAX_UPLOAD_MB", "100"))
MAX_AUDIO_SECONDS = float(os.environ.get("EMOTION_V2_MAX_AUDIO_SECONDS", "300"))
MIN_AUDIO_SECONDS = float(os.environ.get("EMOTION_V2_MIN_AUDIO_SECONDS", "0.25"))

SUPPORTED_EXTENSIONS = {
    ".wav",
    ".flac",
    ".mp3",
    ".m4a",
    ".ogg",
    ".webm",
    ".aac",
}

_cors_origins_raw = os.environ.get(
    "CORS_ALLOW_ORIGINS",
    "https://diagvoice.huseyinalav.me,http://localhost:5173,http://127.0.0.1:5173,http://localhost:5174,http://127.0.0.1:5174,https://duygudurum.diagvoice.com,https://emosyon.diagvoice.com,https://algoritmalar.diagvoice.com,https://yolarkadasim.diagvoice.com",
)
_cors_allow_origins = [o.strip() for o in _cors_origins_raw.split(",") if o.strip()]

_EMOTION_V2_USE_INFER_LOCK = os.environ.get("EMOTION_V2_USE_INFER_LOCK", "1").strip().lower() not in (
    "0",
    "false",
    "no",
)
_infer_lock = threading.Lock()
_predict_lock = asyncio.Lock()


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.predictor = None
    app.state.load_error = None
    app.state.started_at = time.time()

    _log.info("Model yükleniyor: %s", MODEL_PATH)

    try:
        config = RuntimeConfig(
            model_path=MODEL_PATH,
            device=DEVICE,
            min_audio_seconds=MIN_AUDIO_SECONDS,
            max_audio_seconds=MAX_AUDIO_SECONDS,
            stt_url=os.environ.get("VOICE_TO_TEXT_URL", "http://127.0.0.1:8051/transcribe"),
        )
        app.state.predictor = await run_in_threadpool(MultimodalEmotionPredictor, config)
        _log.info("Model hazır: %s", app.state.predictor.model_info())
    except Exception as exc:
        app.state.load_error = f"{type(exc).__name__}: {exc}"
        _log.exception("Model yüklenemedi.")

    yield

    predictor = getattr(app.state, "predictor", None)
    if predictor is not None:
        await run_in_threadpool(predictor.close)

    _log.info("Uygulama kapatıldı.")


app = FastAPI(
    title="DiagVoice Emotion v2",
    version="2.0.0",
    description=(
        "Multimodal stacking emosyon tanıma: merkezi STT (Whisper v3 turbo) transkript, "
        "E5 metin embedding, WavLM ses embedding ve 137 akustik özellik → anger/fear/happiness/sadness."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root() -> dict[str, Any]:
    return {
        "service": "DiagVoice Emotion v2",
        "message": "Ses dosyanızı POST /analyze-audio endpoint'ine gönderin.",
        "model_path": MODEL_PATH,
        "health": "/health",
        "model_info": "/model-info",
    }


@app.get("/health")
async def health(request: Request) -> JSONResponse:
    predictor = getattr(request.app.state, "predictor", None)
    load_error = getattr(request.app.state, "load_error", None)

    if predictor is None:
        return JSONResponse(
            status_code=503,
            content={
                "ok": False,
                "status": "not_ready",
                "error": load_error,
            },
        )

    return JSONResponse(
        {
            "ok": True,
            "status": "ok",
            "uptime_seconds": round(time.time() - request.app.state.started_at, 1),
            **predictor.model_info(),
        }
    )


@app.get("/model-info")
async def model_info(request: Request) -> dict[str, Any]:
    predictor = getattr(request.app.state, "predictor", None)

    if predictor is None:
        raise HTTPException(
            status_code=503,
            detail=getattr(request.app.state, "load_error", "Model henüz hazır değil."),
        )

    return predictor.model_info()


async def _save_upload(upload: UploadFile) -> Path:
    suffix = Path(upload.filename or "audio.wav").suffix.lower()

    if suffix not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail=(
                "Desteklenmeyen dosya türü. Desteklenen uzantılar: "
                + ", ".join(sorted(SUPPORTED_EXTENSIONS))
            ),
        )

    max_bytes = MAX_UPLOAD_MB * 1024 * 1024
    written = 0

    temporary = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    temporary_path = Path(temporary.name)

    try:
        with temporary:
            while True:
                chunk = await upload.read(1024 * 1024)
                if not chunk:
                    break

                written += len(chunk)
                if written > max_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"Dosya çok büyük. Maksimum boyut: {MAX_UPLOAD_MB} MB.",
                    )

                temporary.write(chunk)

        if written == 0:
            raise HTTPException(status_code=422, detail="Yüklenen dosya boş.")

        return temporary_path
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


async def _run_prediction(
    request: Request,
    file: UploadFile,
    speech_language: Optional[str],
    language: Optional[str],
    transcript: Optional[str],
    include_branches: bool,
) -> JSONResponse:
    predictor = getattr(request.app.state, "predictor", None)

    if predictor is None:
        raise HTTPException(
            status_code=503,
            detail=getattr(request.app.state, "load_error", "Model henüz hazır değil."),
        )

    request_id = str(uuid.uuid4())
    temporary_path: Optional[Path] = None
    started_at = time.perf_counter()

    try:
        temporary_path = await _save_upload(file)

        raw_speech_language = (
            speech_language.strip()
            if speech_language and speech_language.strip()
            else None
        )
        if raw_speech_language is None and language and language.strip():
            whisper_lang = resolve_whisper_language(language)
            if whisper_lang is None:
                raw_speech_language = "auto"
            else:
                raw_speech_language = {
                    "turkish": "tr",
                    "english": "en",
                    "arabic": "ar",
                }.get(whisper_lang, language.strip())

        resolved_speech_language = normalize_speech_language_code(raw_speech_language)
        resolved_transcript = transcript.strip() if transcript and transcript.strip() else None

        def _predict_with_lock() -> dict[str, Any]:
            if _EMOTION_V2_USE_INFER_LOCK:
                with _infer_lock:
                    return predictor.predict(
                        temporary_path,
                        resolved_speech_language,
                        resolved_transcript,
                    )
            return predictor.predict(
                temporary_path,
                resolved_speech_language,
                resolved_transcript,
            )

        async with _predict_lock:
            result = await run_in_threadpool(_predict_with_lock)

        if not include_branches:
            result.pop("branch_probabilities", None)

        result["request_id"] = request_id
        result["processing_time_ms"] = round((time.perf_counter() - started_at) * 1000, 2)

        _log.info(
            "analyze_done request_id=%s prediction=%s confidence=%.4f ms=%.0f",
            request_id,
            result["prediction"],
            result["confidence"],
            result["processing_time_ms"],
        )

        return JSONResponse(result)

    except HTTPException:
        raise
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        _log.exception("Tahmin hatası request_id=%s", request_id)
        raise HTTPException(
            status_code=500,
            detail=f"Tahmin sırasında hata oluştu. request_id={request_id}",
        ) from exc
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        await file.close()


@app.post("/analyze-audio")
async def analyze_audio(
    request: Request,
    file: UploadFile = File(..., description="Ses dosyası"),
    speech_language: str = Form(
        "tr",
        description="Konuşma dili: tr | en | ar | auto",
    ),
    language: Optional[str] = Form(
        None,
        description="(Geriye dönük) turkish, english, arabic veya auto",
    ),
    transcript: Optional[str] = Form(
        None,
        description="Verilirse STT çalıştırılmaz ve doğrudan bu transkript kullanılır.",
    ),
    include_branches: bool = Query(
        False,
        description="Model dallarının olasılıklarını yanıta ekler.",
    ),
) -> JSONResponse:
    return await _run_prediction(
        request=request,
        file=file,
        speech_language=speech_language,
        language=language,
        transcript=transcript,
        include_branches=include_branches,
    )


if __name__ == "__main__":
    _port = int(os.environ.get("EMOTION_V2_PORT", "8059"))
    uvicorn.run(app, host="0.0.0.0", port=_port, reload=False)
