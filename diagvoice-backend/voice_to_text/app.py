import contextlib
import io
import logging
import os
import re
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

from code.stt.language import resolve_whisper_language

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

STT_CHUNK_SEC = float(os.environ.get("STT_CHUNK_SEC", "30"))
STT_CHUNK_SEC = max(5.0, min(120.0, STT_CHUNK_SEC))
STT_CHUNK_OVERLAP_SEC = float(os.environ.get("STT_CHUNK_OVERLAP_SEC", "5"))
STT_CHUNK_OVERLAP_SEC = max(0.0, min(STT_CHUNK_SEC - 1.0, STT_CHUNK_OVERLAP_SEC))
STT_NUM_BEAMS = max(1, int(os.environ.get("STT_NUM_BEAMS", "5")))
STT_CPU_GREEDY = os.environ.get("STT_CPU_GREEDY", "1").strip().lower() not in ("0", "false", "no")
STT_MAX_NEW_TOKENS = max(32, int(os.environ.get("STT_MAX_NEW_TOKENS", "444")))
STT_TRIM_TOP_DB = float(os.environ.get("STT_TRIM_TOP_DB", "25"))
STT_MIN_KEEP_SEC = float(os.environ.get("STT_MIN_KEEP_SEC", "0.4"))
STT_MIN_CHUNK_SEC = float(os.environ.get("STT_MIN_CHUNK_SEC", "0.35"))
STT_CONDITION_ON_PREV = os.environ.get("STT_CONDITION_ON_PREV", "1").strip().lower() not in (
    "0",
    "false",
    "no",
)
STT_FORCE_LANGUAGE = os.environ.get("STT_FORCE_LANGUAGE", "1").strip().lower() not in (
    "0",
    "false",
    "no",
)
STT_PROMPT_MAX_CHARS = max(32, int(os.environ.get("STT_PROMPT_MAX_CHARS", "220")))
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


def _effective_num_beams() -> int:
    """CPU'da beam=5 tek istekte dakikalar sürebilir; varsayılan greedy (1)."""
    if device == "cpu" and STT_CPU_GREEDY and STT_NUM_BEAMS > 1:
        return 1
    return STT_NUM_BEAMS


print("Starting server and loading model...")
try:
    model_id = os.environ.get("VOICE_TO_TEXT_MODEL", "openai/whisper-large-v3-turbo")
    use_cuda = torch.cuda.is_available()
    device = "cuda" if use_cuda else "cpu"
    dtype = torch.float16 if use_cuda else torch.float32
    print(f"Using device: {device}, model: {model_id}")

    processor = AutoProcessor.from_pretrained(model_id)
    speech_to_text_model = AutoModelForSpeechSeq2Seq.from_pretrained(
        model_id,
        dtype=dtype,
        low_cpu_mem_usage=True,
    )
    speech_to_text_model.to(device)
    speech_to_text_model.eval()
    _effective_beams = _effective_num_beams()
    print(f"Model loaded successfully. STT num_beams={_effective_beams} (configured={STT_NUM_BEAMS}, cpu_greedy={STT_CPU_GREEDY}).")
except Exception:
    print("!!! FATAL: Failed to load model !!!")
    print(traceback.format_exc())
    processor = None
    speech_to_text_model = None
    device = "cpu"
    dtype = torch.float32


_FFMPEG_FIRST_EXTENSIONS = {
    ".webm",
    ".opus",
    ".ogg",
    ".m4a",
    ".mp4",
    ".aac",
    ".mp3",
    ".flac",
    ".wma",
}


def _load_via_pydub(path: str, sample_rate: int) -> tuple[np.ndarray, int]:
    if AudioSegment is None:
        raise RuntimeError("pydub not available")
    audio_segment = AudioSegment.from_file(path)
    audio_segment = audio_segment.set_frame_rate(sample_rate).set_channels(1).set_sample_width(2)
    wav_buffer = io.BytesIO()
    audio_segment.export(wav_buffer, format="wav")
    wav_buffer.seek(0)
    audio_input, sr = librosa.load(wav_buffer, sr=sample_rate, mono=True)
    if audio_input is None or len(audio_input) == 0:
        raise RuntimeError("empty audio after pydub decode")
    return audio_input.astype(np.float32), int(sr)


def _load_audio_16k_mono(path: str) -> tuple[np.ndarray, int]:
    sample_rate = 16000
    ext = os.path.splitext(str(path).lower())[1]
    if ext in _FFMPEG_FIRST_EXTENSIONS:
        try:
            return _load_via_pydub(path, sample_rate)
        except FileNotFoundError as e:
            raise HTTPException(
                status_code=500,
                detail=(
                    "Audio conversion failed because ffmpeg/ffprobe was not found on the system. "
                    "Install ffmpeg and ensure it is on PATH, or upload a .wav file. "
                    f"Original error: {e}"
                ),
            ) from e
        except Exception as e:
            _log.warning("pydub_decode_failed path=%s ext=%s err=%s; trying librosa", path, ext, e)

    try:
        audio_input, sr = librosa.load(path, sr=sample_rate, mono=True)
        if audio_input is not None and len(audio_input) > 0:
            return audio_input.astype(np.float32), int(sr)
    except Exception:
        pass

    try:
        return _load_via_pydub(path, sample_rate)
    except FileNotFoundError as e:
        raise HTTPException(
            status_code=500,
            detail=(
                "Audio conversion failed because ffmpeg/ffprobe was not found on the system. "
                "Install ffmpeg and ensure it is on PATH, or upload a .wav file. "
                f"Original error: {e}"
            ),
        ) from e
    except Exception as e:
        raise RuntimeError(f"Could not decode audio file: {e}") from e


def _preprocess_audio(audio: np.ndarray, sample_rate: int) -> np.ndarray:
    y = np.asarray(audio, dtype=np.float32)
    y = np.nan_to_num(y, nan=0.0, posinf=0.0, neginf=0.0)
    if y.size == 0:
        return y

    try:
        y_trim, _ = librosa.effects.trim(y, top_db=STT_TRIM_TOP_DB)
        if y_trim.size >= int(STT_MIN_KEEP_SEC * sample_rate):
            y = y_trim
    except Exception:
        pass

    peak = float(np.max(np.abs(y)) + 1e-8)
    y = (y / peak).astype(np.float32)
    return y


def _chunk_starts(total_samples: int, chunk_samples: int, hop_samples: int) -> list[int]:
    if total_samples <= chunk_samples:
        return [0]
    hop = max(1, hop_samples)
    starts = list(range(0, total_samples, hop))
    last = max(0, total_samples - chunk_samples)
    if not starts or starts[-1] != last:
        if last not in starts:
            starts.append(last)
    return sorted(set(starts))


def _normalize_words(text: str) -> list[str]:
    return [w for w in re.split(r"\s+", (text or "").strip()) if w]


def _merge_chunk_texts(parts: list[str]) -> str:
    if not parts:
        return ""
    merged = parts[0].strip()
    for nxt in parts[1:]:
        nxt = nxt.strip()
        if not nxt:
            continue
        if not merged:
            merged = nxt
            continue
        out_words = _normalize_words(merged)
        nxt_words = _normalize_words(nxt)
        best = 0
        max_k = min(len(out_words), len(nxt_words), 16)
        for k in range(max_k, 0, -1):
            if out_words[-k:] == nxt_words[:k]:
                best = k
                break
        if best:
            merged = merged + " " + " ".join(nxt_words[best:])
        else:
            merged = merged + " " + nxt
    return re.sub(r"\s+", " ", merged).strip()


def _normalize_whisper_lang_code(lang: str) -> str:
    s = str(lang).strip().lower().strip("<>|")
    iso_map = {
        "tr": "turkish",
        "en": "english",
        "ar": "arabic",
    }
    if s in iso_map:
        return iso_map[s]
    if s in {"turkish", "english", "arabic", "turkce", "türkçe"}:
        return "turkish" if s in {"turkce", "türkçe"} else s
    return s


def _detect_whisper_language(input_features: torch.Tensor) -> str | None:
    if speech_to_text_model is None:
        return None
    detect_fn = getattr(speech_to_text_model, "detect_language", None)
    if not callable(detect_fn):
        return None
    try:
        with torch.no_grad():
            lang, _probs = detect_fn(input_features)
        if isinstance(lang, (list, tuple)):
            lang = lang[0] if lang else None
        if lang is None:
            return None
        return _normalize_whisper_lang_code(str(lang))
    except Exception:
        _log.exception("whisper_language_detect_failed")
        return None


def _prompt_ids_from_text(prev_text: str | None) -> torch.Tensor | None:
    if not prev_text or not STT_CONDITION_ON_PREV or processor is None:
        return None
    snippet = prev_text.strip()[-STT_PROMPT_MAX_CHARS:]
    if not snippet:
        return None
    try:
        ids = processor.get_prompt_ids(snippet, return_tensors="pt")
        if hasattr(ids, "input_ids"):
            ids = ids.input_ids
        return ids.to(device)
    except Exception:
        return None


def _effective_max_new_tokens(prompt_ids: torch.Tensor | None) -> int:
    """Whisper: len(decoder_prefix) + max_new_tokens <= max_target_positions (448 on small)."""
    max_pos = int(getattr(speech_to_text_model.config, "max_target_positions", 448) or 448)
    # Zorunlu decoder öneki: start + language + task + notimestamps
    prefix_tokens = 4
    if prompt_ids is not None:
        prefix_tokens += int(prompt_ids.shape[-1])
    budget = max_pos - prefix_tokens
    effective = min(STT_MAX_NEW_TOKENS, budget)
    if effective < STT_MAX_NEW_TOKENS:
        _log.debug(
            "stt max_new_tokens capped %s -> %s (prefix_tokens=%s max_pos=%s)",
            STT_MAX_NEW_TOKENS,
            effective,
            prefix_tokens,
            max_pos,
        )
    return max(32, effective)


def _transcribe_chunk(
    chunk: np.ndarray,
    sample_rate: int,
    whisper_lang: str | None,
    prev_text: str | None,
) -> str:
    input_features = processor(
        chunk.astype(np.float32),
        sampling_rate=sample_rate,
        return_tensors="pt",
    )
    features = input_features["input_features"].to(device=device, dtype=dtype)

    prompt_ids = _prompt_ids_from_text(prev_text)
    gen_kw: dict = {
        "input_features": features,
        "num_beams": _effective_num_beams(),
        "do_sample": False,
        "max_new_tokens": _effective_max_new_tokens(prompt_ids),
    }
    if prompt_ids is not None:
        gen_kw["prompt_ids"] = prompt_ids

    if whisper_lang:
        try:
            gen_kw["forced_decoder_ids"] = processor.get_decoder_prompt_ids(
                language=whisper_lang,
                task="transcribe",
            )
        except Exception:
            _log.warning("forced_decoder_ids_failed lang=%s; falling back to language kwarg", whisper_lang)
            gen_kw["language"] = whisper_lang
            gen_kw["task"] = "transcribe"
    else:
        gen_kw["task"] = "transcribe"

    with torch.no_grad():
        generated_ids = speech_to_text_model.generate(**gen_kw)

    return processor.batch_decode(generated_ids, skip_special_tokens=True)[0].strip()


def _transcribe_sync(temp_file_path: str, requested_lang: str | None) -> dict[str, str | bool | None]:
    t0 = time.perf_counter()
    _cm = _infer_lock if _VOICE_TO_TEXT_USE_INFER_LOCK else contextlib.nullcontext()
    with _cm:
        if speech_to_text_model is None or processor is None:
            raise RuntimeError("Model is not loaded.")

        t_load = time.perf_counter()
        audio_input, sample_rate = _load_audio_16k_mono(temp_file_path)
        audio_input = _preprocess_audio(audio_input, sample_rate)
        load_ms = (time.perf_counter() - t_load) * 1000

        if audio_input.size == 0:
            return {"text": "", "language": requested_lang, "language_auto_detected": False}

        if VOICE_TO_TEXT_MAX_AUDIO_SEC > 0:
            max_samples = int(VOICE_TO_TEXT_MAX_AUDIO_SEC * sample_rate)
            if len(audio_input) > max_samples:
                audio_input = audio_input[:max_samples]
                _log.info("audio_trimmed_to_sec=%s", VOICE_TO_TEXT_MAX_AUDIO_SEC)

        whisper_lang = resolve_whisper_language(requested_lang)
        language_auto_detected = False
        if whisper_lang is None or not STT_FORCE_LANGUAGE:
            first_end = min(len(audio_input), int(min(STT_CHUNK_SEC, 30.0) * sample_rate))
            probe = audio_input[:first_end]
            probe_features = processor(
                probe.astype(np.float32),
                sampling_rate=sample_rate,
                return_tensors="pt",
            )["input_features"].to(device=device, dtype=dtype)
            detected = _detect_whisper_language(probe_features)
            if detected:
                whisper_lang = detected
                language_auto_detected = True
            elif whisper_lang is None:
                whisper_lang = "turkish"

        chunk_samples = int(STT_CHUNK_SEC * sample_rate)
        hop_samples = int(max(1.0, (STT_CHUNK_SEC - STT_CHUNK_OVERLAP_SEC) * sample_rate))
        starts = _chunk_starts(len(audio_input), chunk_samples, hop_samples)
        min_chunk_samples = int(STT_MIN_CHUNK_SEC * sample_rate)

        chunk_texts: list[str] = []
        prev_text: str | None = None
        t_gen = time.perf_counter()
        for start_idx in starts:
            end_idx = min(start_idx + chunk_samples, len(audio_input))
            chunk = audio_input[start_idx:end_idx]
            if chunk.size < min_chunk_samples:
                continue

            text = _transcribe_chunk(chunk, sample_rate, whisper_lang, prev_text)
            if text:
                chunk_texts.append(text)
                prev_text = _merge_chunk_texts(chunk_texts)

        gen_ms = (time.perf_counter() - t_gen) * 1000
        total_ms = (time.perf_counter() - t0) * 1000
        _log.info(
            "transcribe_done lang=%s auto=%s load_ms=%.0f generate_ms=%.0f total_ms=%.0f "
            "samples=%d chunks=%d beams=%d",
            whisper_lang,
            language_auto_detected,
            load_ms,
            gen_ms,
            total_ms,
            len(audio_input),
            len(starts),
            _effective_num_beams(),
        )

    return {
        "text": _merge_chunk_texts(chunk_texts),
        "language": whisper_lang,
        "language_auto_detected": language_auto_detected,
    }


@app.get("/")
async def root():
    return {
        "message": "Voice-to-Text API. POST audio to /transcribe.",
        "transcribe": (
            "multipart: file + optional Form field 'language' "
            "(turkish|english|arabic or tr|en|ar|auto). Default turkish."
        ),
        "defaults": {
            "model": os.environ.get("VOICE_TO_TEXT_MODEL", "openai/whisper-large-v3-turbo"),
            "chunk_sec": STT_CHUNK_SEC,
            "chunk_overlap_sec": STT_CHUNK_OVERLAP_SEC,
            "num_beams": _effective_num_beams(),
            "num_beams_configured": STT_NUM_BEAMS,
            "cpu_greedy": STT_CPU_GREEDY and device == "cpu",
        },
    }


@app.post("/transcribe")
async def transcribe_audio(
    file: UploadFile = File(...),
    language: str = Form("turkish"),
):
    if speech_to_text_model is None or processor is None:
        raise HTTPException(status_code=500, detail="Model could not be loaded. Check server logs.")

    whisper_lang = resolve_whisper_language(language)
    _log.info("transcribe_begin file=%s language=%s", file.filename, whisper_lang or "auto")

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

        return await run_in_threadpool(_transcribe_sync, temp_file_path, language)
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
