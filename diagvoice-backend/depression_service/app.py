import contextlib
import io
import logging
import os
import tempfile
import threading
import time
import traceback
from typing import Any

import fastapi
import librosa
import numpy as np
import torch
import torch.nn as nn
import uvicorn
from fastapi import File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydub import AudioSegment
from starlette.concurrency import run_in_threadpool
from transformers import AutoFeatureExtractor, AutoModel


TARGET_SR = int(os.environ.get("DEPRESSION_TARGET_SR", "16000"))
SEGMENT_SEC = float(os.environ.get("DEPRESSION_SEGMENT_SEC", "8"))
HOP_SEC = float(os.environ.get("DEPRESSION_HOP_SEC", "4"))
TOP_DB = float(os.environ.get("DEPRESSION_TOP_DB", "25"))
MIN_KEEP_SEC = float(os.environ.get("DEPRESSION_MIN_KEEP_SEC", "2.0"))
MAX_SEGMENTS = int(os.environ.get("DEPRESSION_MAX_SEGMENTS", "20"))
INFER_BATCH_SIZE = int(os.environ.get("DEPRESSION_INFER_BATCH_SIZE", "4"))
THRESHOLD = float(os.environ.get("DEPRESSION_THRESHOLD", "0.5"))

SEGMENT_LEN = int(TARGET_SR * SEGMENT_SEC)
HOP_LEN = int(TARGET_SR * HOP_SEC)

MODEL_PATH = os.environ.get("DEPRESSION_MODEL_PATH", "/app/models/depresyon.pt")
BACKBONE_NAME = os.environ.get("DEPRESSION_BACKBONE", "facebook/wav2vec2-base")
CACHE_DIR = os.environ.get("DEPRESSION_BACKBONE_CACHE_DIR")

_log = logging.getLogger("diagvoice.depression")
_log.setLevel(getattr(logging, os.environ.get("DIAGVOICE_LOG_LEVEL", "INFO").upper(), logging.INFO))
if not _log.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [diagvoice.depression] %(message)s"))
    _log.addHandler(_h)
    _log.propagate = False
_infer_lock = threading.Lock()
_DEPRESSION_USE_INFER_LOCK = os.environ.get("DEPRESSION_USE_INFER_LOCK", "1").strip().lower() not in (
    "0",
    "false",
    "no",
)


class Wav2VecBinaryClassifier(nn.Module):
    def __init__(self, model_name: str, dropout: float = 0.3, cache_dir: str | None = None):
        super().__init__()
        self.backbone = AutoModel.from_pretrained(model_name, cache_dir=cache_dir)
        hidden_size = self.backbone.config.hidden_size

        self.dropout = nn.Dropout(dropout)
        self.classifier = nn.Sequential(
            nn.Linear(hidden_size, 256),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(256, 2),
        )

    def masked_mean_pooling(self, hidden_states: torch.Tensor, attention_mask: torch.Tensor | None):
        if attention_mask is None:
            return hidden_states.mean(dim=1)

        mask_f = attention_mask.float()
        th = hidden_states.size(1)
        tm = mask_f.size(1)
        if tm == th:
            m = mask_f
        else:
            # nearest: indeks örneklemesi — interpolate yerine hızlı hizalama
            if th <= 1:
                m = mask_f[:, :1]
            else:
                pos = torch.linspace(0, tm - 1, th, device=mask_f.device, dtype=torch.float32)
                idx = pos.round().long().clamp(0, tm - 1)
                m = mask_f.gather(1, idx.unsqueeze(0).expand(mask_f.size(0), -1))

        m = m.unsqueeze(-1)
        summed = torch.sum(hidden_states * m, dim=1)
        denom = torch.clamp(m.sum(dim=1), min=1e-6)
        return summed / denom

    def forward(self, input_values: torch.Tensor, attention_mask: torch.Tensor | None = None):
        outputs = self.backbone(input_values=input_values, attention_mask=attention_mask)
        hidden_states = outputs.last_hidden_state
        pooled = self.masked_mean_pooling(hidden_states, attention_mask)
        logits = self.classifier(self.dropout(pooled))
        return logits


def _decode_to_float32_16k(path: str) -> np.ndarray:
    """
    Önce librosa (daha az kopya); olmazsa pydub+ffmpeg yolu.
    """
    y: np.ndarray | None = None
    sr = TARGET_SR
    try:
        y_load, sr_load = librosa.load(path, sr=TARGET_SR, mono=True)
        y = np.asarray(y_load, dtype=np.float32)
        sr = int(sr_load)
    except Exception:
        y = None

    if y is None or y.size == 0:
        audio_segment = AudioSegment.from_file(path)
        audio_segment = audio_segment.set_frame_rate(TARGET_SR).set_channels(1).set_sample_width(2)
        wav_buffer = io.BytesIO()
        audio_segment.export(wav_buffer, format="wav")
        wav_buffer.seek(0)
        y, sr = librosa.load(wav_buffer, sr=None, mono=True)
        y = np.asarray(y, dtype=np.float32)

    y = np.nan_to_num(y)
    if sr != TARGET_SR:
        y = librosa.resample(y, orig_sr=sr, target_sr=TARGET_SR)

    y = y - float(np.mean(y))
    y_trimmed, _ = librosa.effects.trim(y, top_db=TOP_DB)

    if len(y_trimmed) < int(MIN_KEEP_SEC * TARGET_SR):
        y_trimmed = y

    peak = float(np.max(np.abs(y_trimmed)) + 1e-8)
    y_trimmed = y_trimmed / peak
    return y_trimmed.astype(np.float32)


def _make_segments(y: np.ndarray) -> list[np.ndarray]:
    if len(y) <= SEGMENT_LEN:
        pad = SEGMENT_LEN - len(y)
        return [np.pad(y, (0, pad), mode="constant").astype(np.float32)]

    starts = list(range(0, len(y) - SEGMENT_LEN + 1, HOP_LEN))
    last_start = len(y) - SEGMENT_LEN
    if len(starts) == 0 or starts[-1] != last_start:
        starts.append(last_start)

    if MAX_SEGMENTS > 0 and len(starts) > MAX_SEGMENTS:
        idxs = np.linspace(0, len(starts) - 1, MAX_SEGMENTS, dtype=int)
        starts = [starts[i] for i in idxs]

    return [y[s : s + SEGMENT_LEN].astype(np.float32) for s in starts]


def _analyze_depression_sync(tmp_path: str) -> dict[str, Any]:
    """CPU/torch işi — tek seferde bir istek (model paylaşımlı)."""
    t0 = time.perf_counter()
    _lock_cm = _infer_lock if _DEPRESSION_USE_INFER_LOCK else contextlib.nullcontext()
    with _lock_cm:
        t_dec = time.perf_counter()
        y = _decode_to_float32_16k(tmp_path)
        segments = _make_segments(y)
        decode_ms = (time.perf_counter() - t_dec) * 1000

        if model is None or feature_extractor is None:
            raise RuntimeError("Model not loaded")

        probs_list: list[np.ndarray] = []
        step = max(1, INFER_BATCH_SIZE)
        t_inf = time.perf_counter()
        with torch.no_grad():
            for i in range(0, len(segments), step):
                batch = segments[i : i + step]
                inputs = feature_extractor(
                    batch,
                    sampling_rate=TARGET_SR,
                    return_tensors="pt",
                    padding=True,
                )
                input_values = inputs["input_values"].to(device)
                attention_mask = inputs.get("attention_mask")
                if attention_mask is not None:
                    attention_mask = attention_mask.to(device)

                logits = model(input_values=input_values, attention_mask=attention_mask)
                probs_batch = torch.softmax(logits, dim=1)[:, 1].detach().cpu().numpy()
                probs_list.append(probs_batch)
        infer_ms = (time.perf_counter() - t_inf) * 1000

        probs_depression = np.concatenate(probs_list, axis=0)

        mean_prob = float(np.mean(probs_depression))
        median_prob = float(np.median(probs_depression))
        std_prob = float(np.std(probs_depression))
        min_prob = float(np.min(probs_depression))
        max_prob = float(np.max(probs_depression))

        if len(probs_depression) >= 5:
            low = np.percentile(probs_depression, 10)
            high = np.percentile(probs_depression, 90)
            trimmed = probs_depression[
                (probs_depression >= low) & (probs_depression <= high)
            ]
            trimmed_mean_prob = float(np.mean(trimmed)) if len(trimmed) > 0 else mean_prob
        else:
            trimmed_mean_prob = mean_prob

        final_prob = float(0.5 * median_prob + 0.5 * trimmed_mean_prob)

        pred_id = 1 if final_prob >= THRESHOLD else 0
        pred_label = "depresyon" if pred_id == 1 else "saglikli"

        if std_prob >= 0.25:
            reliability = "dusuk"
        elif 0.35 <= final_prob <= 0.65:
            reliability = "orta"
        else:
            reliability = "yuksek"

        if final_prob < 0.2:
            risk_level = "dusuk"
        elif final_prob < 0.5:
            risk_level = "orta"
        else:
            risk_level = "yuksek"

        seg_n = len(segments)
        out = {
            "pred_id": pred_id,
            "pred_label": pred_label,
            "risk_level": risk_level,
            "final_prob_depression": final_prob,
            "mean_prob_depression": mean_prob,
            "median_prob_depression": median_prob,
            "trimmed_mean_prob_depression": trimmed_mean_prob,
            "std_prob_depression": std_prob,
            "min_prob_depression": min_prob,
            "max_prob_depression": max_prob,
            "reliability": reliability,
            "is_unstable": bool(std_prob >= 0.25),
            "segment_count": int(seg_n),
            "threshold": THRESHOLD,
            "segment_probs": [float(x) for x in probs_depression.tolist()],
            "labels": {"0": "saglikli", "1": "depresyon"},
        }

    total_ms = (time.perf_counter() - t0) * 1000
    _log.info(
        "analyze_depression_done segments=%d decode_ms=%.0f infer_ms=%.0f total_ms=%.0f",
        seg_n,
        decode_ms,
        infer_ms,
        total_ms,
    )
    return out


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

print("Starting depression-service and loading model...")
try:
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Using device: {device}")

    feature_extractor = AutoFeatureExtractor.from_pretrained(BACKBONE_NAME, cache_dir=CACHE_DIR)
    model = Wav2VecBinaryClassifier(BACKBONE_NAME, dropout=0.3, cache_dir=CACHE_DIR)

    state_obj: Any = torch.load(MODEL_PATH, map_location="cpu")
    if isinstance(state_obj, dict) and "state_dict" in state_obj and isinstance(state_obj["state_dict"], dict):
        state_dict = state_obj["state_dict"]
    elif isinstance(state_obj, dict):
        state_dict = state_obj
    else:
        raise RuntimeError("Invalid depression checkpoint format")

    model.load_state_dict(state_dict, strict=True)
    model.to(device)
    model.eval()

    print(f"Depression model loaded from {MODEL_PATH}")
except Exception:
    print("!!! FATAL: Failed to load depression model !!!")
    print(traceback.format_exc())
    feature_extractor = None
    model = None
    device = "cpu"


@app.get("/")
async def root():
    return {
        "message": "Depression service. Send audio to /analyze-depression.",
        "model_path": MODEL_PATH,
        "backbone": BACKBONE_NAME,
        "target_sr": TARGET_SR,
        "segment_sec": SEGMENT_SEC,
        "hop_sec": HOP_SEC,
        "threshold": THRESHOLD,
    }


@app.post("/analyze-depression")
async def analyze_depression(file: UploadFile = File(...)):
    if model is None or feature_extractor is None:
        raise HTTPException(status_code=500, detail="Depression model could not be loaded. Check server logs.")

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
        _log.info("analyze_depression_begin file=%s bytes=%d recv_ms=%.0f", file.filename or "", nbytes, recv_ms)

        try:
            return await run_in_threadpool(_analyze_depression_sync, tmp_path)
        except Exception as e:
            print("Depression endpoint failed:")
            print(traceback.format_exc())
            raise HTTPException(status_code=500, detail=f"Depression analysis failed: {e}") from e
    finally:
        try:
            if tmp_path and os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass


if __name__ == "__main__":
    _port = int(os.environ.get("DEPRESSION_SERVICE_PORT", "8057"))
    uvicorn.run(app, host="0.0.0.0", port=_port)
