import contextlib
import io
import logging
import os
import tempfile
import threading
import time
import traceback

import fastapi
import librosa
import numpy as np
import torch
import uvicorn
from fastapi import File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydub import AudioSegment
from starlette.concurrency import run_in_threadpool
from transformers import AutoModelForSpeechSeq2Seq, AutoProcessor

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

STT_CHUNK_SEC = float(os.environ.get("STT_CHUNK_SEC", "25"))
STT_CHUNK_SEC = max(5.0, min(120.0, STT_CHUNK_SEC))
STT_NUM_BEAMS = max(1, int(os.environ.get("STT_NUM_BEAMS", "1")))
STT_MAX_NEW_TOKENS = max(32, int(os.environ.get("STT_MAX_NEW_TOKENS", "256")))
_max_audio_raw = os.environ.get("VOICE_TO_TEXT_MAX_AUDIO_SEC", "0").strip()
VOICE_TO_TEXT_MAX_AUDIO_SEC = float(_max_audio_raw) if _max_audio_raw else 0.0
if VOICE_TO_TEXT_MAX_AUDIO_SEC > 0:
    VOICE_TO_TEXT_MAX_AUDIO_SEC = max(1.0, min(3600.0, VOICE_TO_TEXT_MAX_AUDIO_SEC))

_log = logging.getLogger("diagvoice.stt")
_log.setLevel(getattr(logging, os.environ.get("DIAGVOICE_LOG_LEVEL", "INFO").upper(), logging.INFO))
if not _log.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [diagvoice.stt] %(message)s"))
    _log.addHandler(_h)
    _log.propagate = False

_stt_parallel_raw = int(os.environ.get("STT_MAX_PARALLEL_CHUNKS", "1"))
if _stt_parallel_raw > 1:
    _log.warning(
        "STT_MAX_PARALLEL_CHUNKS=%s ignored (paylaşımlı Whisper modeli; güvenli değer 1).",
        _stt_parallel_raw,
    )

_infer_lock = threading.Lock()
_VOICE_TO_TEXT_USE_INFER_LOCK = os.environ.get("VOICE_TO_TEXT_USE_INFER_LOCK", "1").strip().lower() not in (
    "0",
    "false",
    "no",
)

print("Starting server and loading model...")
try:
    model_id = os.environ.get("VOICE_TO_TEXT_MODEL", "openai/whisper-base")
    use_cuda = torch.cuda.is_available()
    device = "cuda" if use_cuda else "cpu"
    dtype = torch.float16 if use_cuda else torch.float32
    print(f"Using device: {device}")

    processor = AutoProcessor.from_pretrained(model_id)
    speech_to_text_model = AutoModelForSpeechSeq2Seq.from_pretrained(
        model_id,
        dtype=dtype,
        low_cpu_mem_usage=True,
    )
    speech_to_text_model.to(device)
    speech_to_text_model.eval()
    print("Model loaded successfully.")
except Exception:
    print("!!! FATAL: Failed to load model !!!")
    print(traceback.format_exc())
    processor = None
    speech_to_text_model = None
    device = "cpu"
    dtype = torch.float32


def resolve_whisper_language(language: str | None) -> str:
    if not language or not str(language).strip():
        return "turkish"
    key = str(language).strip().lower()
    mapping = {
        "tr": "turkish",
        "turkish": "turkish",
        "türkçe": "turkish",
        "turkce": "turkish",
        "en": "english",
        "english": "english",
        "ingilizce": "english",
        "ar": "arabic",
        "arabic": "arabic",
        "arab": "arabic",
        "عربي": "arabic",
        "العربية": "arabic",
    }
    return mapping.get(key, "turkish")


def _load_audio_16k_mono(path: str) -> tuple[np.ndarray, int]:
    sample_rate = 16000
    try:
        audio_input, sr = librosa.load(path, sr=sample_rate, mono=True)
        if audio_input is not None and len(audio_input) > 0:
            return audio_input.astype(np.float32), int(sr)
    except Exception:
        pass

    try:
        audio_segment = AudioSegment.from_file(path)
    except FileNotFoundError as e:
        raise HTTPException(
            status_code=500,
            detail=(
                "Audio conversion failed because ffmpeg/ffprobe was not found on the system. "
                "Install ffmpeg and ensure it is on PATH, or upload a .wav file. "
                f"Original error: {e}"
            ),
        ) from e

    audio_segment = audio_segment.set_frame_rate(16000).set_channels(1).set_sample_width(2)
    wav_buffer = io.BytesIO()
    audio_segment.export(wav_buffer, format="wav")
    wav_buffer.seek(0)
    audio_input, sr = librosa.load(wav_buffer, sr=16000, mono=True)
    return audio_input.astype(np.float32), int(sr)


def _transcribe_sync(temp_file_path: str, whisper_lang: str) -> dict[str, str]:
    t0 = time.perf_counter()
    _cm = _infer_lock if _VOICE_TO_TEXT_USE_INFER_LOCK else contextlib.nullcontext()
    with _cm:
        if speech_to_text_model is None or processor is None:
            raise RuntimeError("Model is not loaded.")

        t_load = time.perf_counter()
        audio_input, sample_rate = _load_audio_16k_mono(temp_file_path)
        load_ms = (time.perf_counter() - t_load) * 1000

        if VOICE_TO_TEXT_MAX_AUDIO_SEC > 0:
            max_samples = int(VOICE_TO_TEXT_MAX_AUDIO_SEC * sample_rate)
            if len(audio_input) > max_samples:
                audio_input = audio_input[:max_samples]
                _log.info("audio_trimmed_to_sec=%s", VOICE_TO_TEXT_MAX_AUDIO_SEC)

        chunk_size = int(STT_CHUNK_SEC * sample_rate)
        total_samples = len(audio_input)
        chunk_texts: list[str] = []
        t_gen = time.perf_counter()
        for start_idx in range(0, total_samples, chunk_size):
            end_idx = min(start_idx + chunk_size, total_samples)
            chunk = audio_input[start_idx:end_idx]

            input_features = processor(
                chunk.astype(np.float32),
                sampling_rate=sample_rate,
                return_tensors="pt",
            )
            features = input_features["input_features"].to(device=device, dtype=dtype)

            with torch.no_grad():
                gen_kw: dict = dict(
                    input_features=features,
                    language=whisper_lang,
                    task="transcribe",
                    max_new_tokens=STT_MAX_NEW_TOKENS,
                    num_beams=STT_NUM_BEAMS,
                )
                generated_ids = speech_to_text_model.generate(**gen_kw)

            chunk_text = processor.batch_decode(generated_ids, skip_special_tokens=True)[0].strip()
            if chunk_text:
                chunk_texts.append(chunk_text)

        gen_ms = (time.perf_counter() - t_gen) * 1000
        total_ms = (time.perf_counter() - t0) * 1000
        _log.info(
            "transcribe_done load_ms=%.0f generate_ms=%.0f total_ms=%.0f samples=%d chunks=%d",
            load_ms,
            gen_ms,
            total_ms,
            total_samples,
            max(1, (total_samples + chunk_size - 1) // chunk_size),
        )

    return {"text": " ".join(chunk_texts).strip(), "language": whisper_lang}


@app.get("/")
async def root():
    return {
        "message": "Voice-to-Text API. POST audio to /transcribe.",
        "transcribe": "multipart: file + optional Form field 'language' (turkish|english|arabic or tr|en|ar). Default turkish.",
    }


@app.post("/transcribe")
async def transcribe_audio(
    file: UploadFile = File(...),
    language: str = Form("turkish"),
):
    if speech_to_text_model is None or processor is None:
        raise HTTPException(status_code=500, detail="Model could not be loaded. Check server logs.")

    whisper_lang = resolve_whisper_language(language)
    _log.info("transcribe_begin file=%s language=%s", file.filename, whisper_lang)

    temp_file_path = None
    try:
        suffix = ""
        if file.filename:
            safe = str(file.filename).replace("/", "_").replace("\\", "_")
            suffix = f"_{safe}"
        t_recv = time.perf_counter()
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                temp_file.write(chunk)
            temp_file_path = temp_file.name
        recv_ms = (time.perf_counter() - t_recv) * 1000
        nbytes = os.path.getsize(temp_file_path) if temp_file_path else 0
        _log.info("upload_saved bytes=%d recv_ms=%.0f", nbytes, recv_ms)

        return await run_in_threadpool(_transcribe_sync, temp_file_path, whisper_lang)
    except HTTPException:
        raise
    except Exception as e:
        _log.exception("transcribe_failed")
        raise HTTPException(
            status_code=500,
            detail=f"An internal server error occurred during transcription. Check server logs. Error: {e}",
        ) from e
    finally:
        if temp_file_path and os.path.exists(temp_file_path):
            try:
                os.remove(temp_file_path)
            except PermissionError:
                pass


if __name__ == "__main__":
    _port = int(os.environ.get("VOICE_TO_TEXT_PORT", "8051"))
    uvicorn.run(app, host="0.0.0.0", port=_port)
