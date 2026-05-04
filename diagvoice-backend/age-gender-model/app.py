import contextlib
import io
import json
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
import torchaudio
import torch.nn as nn
import uvicorn
from fastapi import File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from starlette.concurrency import run_in_threadpool
from transformers import AutoFeatureExtractor, AutoModel, AutoModelForAudioClassification

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

MODEL_DIR = os.environ.get(
    "AGE_GENDER_MODEL_DIR",
    "/Users/beyazskorsky/Documents/diag-duygu-durum/diagvoice-backend/models",
)

SR = 16000
MAX_LEN = SR * 4
BASE_MODEL = "microsoft/wavlm-base"
GENDER_MODEL_ID = os.environ.get(
    "GENDER_MODEL_ID",
    "alefiury/wav2vec2-large-xlsr-53-gender-recognition-librispeech",
)

_USE_READY_GENDER_MODEL = os.environ.get("AGE_GENDER_USE_READY_GENDER_MODEL", "1").strip().lower() not in (
    "0",
    "false",
    "no",
)

_log = logging.getLogger("diagvoice.age_gender")
_log.setLevel(getattr(logging, os.environ.get("DIAGVOICE_LOG_LEVEL", "INFO").upper(), logging.INFO))
if not _log.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [diagvoice.age_gender] %(message)s"))
    _log.addHandler(_h)
    _log.propagate = False

_infer_lock = threading.Lock()
_AGE_GENDER_USE_INFER_LOCK = os.environ.get("AGE_GENDER_USE_INFER_LOCK", "1").strip().lower() not in (
    "0",
    "false",
    "no",
)

gender_labels = []
agebin_labels = []
gender2id = {}
agebin2id = {}
model = None
device = None
gender_model = None
gender_feature_extractor = None
gender_model_sr = 16000


class MultiTask(nn.Module):
    def __init__(self, num_gender, num_agebin):
        super().__init__()
        self.encoder = AutoModel.from_pretrained(BASE_MODEL)
        h = self.encoder.config.hidden_size
        self.drop = nn.Dropout(0.1)
        self.g_head = nn.Linear(h, num_gender)
        self.a_head = nn.Linear(h, num_agebin)

    def forward(self, input_values):
        x = self.encoder(input_values=input_values).last_hidden_state.mean(dim=1)
        x = self.drop(x)
        return self.g_head(x), self.a_head(x)


def _load_model():
    global gender_labels, agebin_labels, gender2id, agebin2id, model, device, gender_model, gender_feature_extractor, gender_model_sr

    print("Loading age-gender model...")
    try:
        labels_path = os.path.join(MODEL_DIR, "labels.json")
        with open(labels_path, "r", encoding="utf-8") as f:
            maps = json.load(f)
        gender_labels = maps["gender"]
        agebin_labels = maps["agebin"]
        gender2id = {k: i for i, k in enumerate(gender_labels)}
        agebin2id = {k: i for i, k in enumerate(agebin_labels)}
        print(f"Labels loaded: gender={gender_labels}, agebin={agebin_labels}")

        model_path = os.path.join(MODEL_DIR, "model.pt")
        model = MultiTask(len(gender_labels), len(agebin_labels))
        state = torch.load(model_path, map_location="cpu")
        model.load_state_dict(state, strict=True)

        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        model.to(device)
        model.eval()
        print(f"Model loaded from {model_path} on {device}")

        try:
            print(f"Loading ready gender model: {GENDER_MODEL_ID}")
            gender_feature_extractor = AutoFeatureExtractor.from_pretrained(GENDER_MODEL_ID)
            gender_model = AutoModelForAudioClassification.from_pretrained(GENDER_MODEL_ID).to(device)
            gender_model.eval()
            gender_model_sr = int(getattr(gender_feature_extractor, "sampling_rate", SR) or SR)
            print(f"Ready gender model loaded (sr={gender_model_sr})")
        except Exception as ge:
            print(f"Ready gender model could not be loaded, fallback will be used: {ge}")
            print(traceback.format_exc())
            gender_model = None
            gender_feature_extractor = None
    except Exception as e:
        print(f"!!! FATAL: Failed to load age-gender model: {e} !!!")
        print(traceback.format_exc())
        model = None
        gender_model = None
        gender_feature_extractor = None


_load_model()


def _wav_tensor_from_path(tmp_path: str) -> torch.Tensor:
    """Önce librosa; olmazsa pydub (m4a/mp3 vb.). Çıktı: [MAX_LEN] float32."""
    wav: torch.Tensor | None = None
    try:
        y, s = librosa.load(tmp_path, sr=SR, mono=True)
        if y is not None and len(y) > 0:
            wav = torch.from_numpy(np.asarray(y, dtype=np.float32))
            wav = torch.nan_to_num(wav)
    except Exception:
        wav = None

    if wav is None or wav.numel() == 0:
        from pydub import AudioSegment

        audio = AudioSegment.from_file(tmp_path)
        audio = audio.set_frame_rate(SR).set_channels(1)
        arr = np.array(audio.get_array_of_samples(), dtype=np.float32) / 32768.0
        wav = torch.tensor(arr, dtype=torch.float32)
        wav = torch.nan_to_num(wav)

    wav = wav[:MAX_LEN] if wav.numel() > MAX_LEN else nn.functional.pad(wav, (0, MAX_LEN - wav.numel()))
    return wav


def _normalize_gender_label(raw: str) -> str:
    s = str(raw or "").strip().lower()
    if "fem" in s or "woman" in s or "female" in s or s in {"f", "kadin", "kadın"}:
        return "female"
    if "male" in s or "man" in s or s in {"m", "erkek"}:
        return "male"
    return "female" if s.endswith("0") else "male"


def _predict_gender_ready_model(wav_mono_16k: torch.Tensor):
    if gender_model is None or gender_feature_extractor is None:
        return None

    wav = wav_mono_16k.detach().cpu()
    if wav.dim() != 1:
        wav = wav.squeeze()
    if gender_model_sr != SR:
        wav = torchaudio.functional.resample(wav, orig_freq=SR, new_freq=gender_model_sr)

    x = wav.numpy().astype(np.float32)
    inputs = gender_feature_extractor(
        x,
        sampling_rate=gender_model_sr,
        return_tensors="pt",
        padding=True,
    )
    inputs = {k: v.to(device) for k, v in inputs.items()}

    with torch.no_grad():
        out = gender_model(**inputs)
        probs = torch.softmax(out.logits, dim=-1).cpu().numpy()[0]

    id2label = getattr(gender_model.config, "id2label", None) or {}
    mapped = []
    for i, p in enumerate(probs.tolist()):
        raw_label = id2label.get(i, str(i))
        mapped.append((_normalize_gender_label(raw_label), float(p)))

    female_prob = 0.0
    male_prob = 0.0
    for lab, p in mapped:
        if lab == "female":
            female_prob += p
        elif lab == "male":
            male_prob += p

    total = female_prob + male_prob
    if total <= 0:
        female_prob, male_prob = 0.5, 0.5
    else:
        female_prob, male_prob = female_prob / total, male_prob / total

    probs_out = [female_prob, male_prob]
    pred_id = int(np.argmax(np.asarray(probs_out)))
    pred_label = ["female", "male"][pred_id]
    return {"pred_id": pred_id, "pred_label": pred_label, "probs": probs_out}


def _analyze_age_gender_sync(tmp_path: str) -> dict[str, Any]:
    t0 = time.perf_counter()
    _cm = _infer_lock if _AGE_GENDER_USE_INFER_LOCK else contextlib.nullcontext()
    with _cm:
        t_dec = time.perf_counter()
        wav = _wav_tensor_from_path(tmp_path)
        decode_ms = (time.perf_counter() - t_dec) * 1000

        wav_b = wav.unsqueeze(0).to(device)

        t_inf = time.perf_counter()
        with torch.no_grad():
            lg, la = model(wav_b)
            g_probs_mt = torch.softmax(lg, dim=-1).cpu().numpy()[0]
            a_probs = torch.softmax(la, dim=-1).cpu().numpy()[0]
            g_pred_mt = int(lg.argmax(-1).cpu().item())
            a_pred = int(la.argmax(-1).cpu().item())

        gender_ready = None
        if _USE_READY_GENDER_MODEL:
            gender_ready = _predict_gender_ready_model(wav.detach().cpu())

        if gender_ready is None:
            g_probs = [float(x) for x in g_probs_mt.tolist()]
            g_pred = g_pred_mt
            g_label = gender_labels[g_pred]
            gender_source = "multitask_fallback"
        else:
            g_probs = [float(x) for x in gender_ready["probs"]]
            g_pred = int(gender_ready["pred_id"])
            g_label = str(gender_ready["pred_label"])
            gender_source = "ready_model"
        infer_ms = (time.perf_counter() - t_inf) * 1000

    total_ms = (time.perf_counter() - t0) * 1000
    _log.info(
        "analyze_age_gender_done decode_ms=%.0f infer_ms=%.0f total_ms=%.0f source=%s",
        decode_ms,
        infer_ms,
        total_ms,
        gender_source,
    )

    return {
        "gender": {
            "pred_id": g_pred,
            "pred_label": g_label,
            "probs": g_probs,
            "source": gender_source,
        },
        "agebin": {
            "pred_id": a_pred,
            "pred_label": agebin_labels[a_pred],
            "probs": [float(x) for x in a_probs.tolist()],
        },
    }


@app.get("/")
async def root():
    return {
        "message": "Age-Gender servisi. Ses dosyanızı /analyze-age-gender endpoint'ine gönderin.",
        "model_dir": MODEL_DIR,
        "gender_labels": gender_labels,
        "agebin_labels": agebin_labels,
    }


@app.post("/analyze-age-gender")
async def analyze_age_gender(file: UploadFile = File(...)):
    if model is None:
        raise HTTPException(status_code=500, detail="Age-gender model could not be loaded. Check server logs.")

    tmp_path = None
    try:
        suffix = ""
        if file.filename:
            safe = str(file.filename).replace("/", "_").replace("\\", "_")
            suffix = f"_{safe}"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp_path = tmp.name
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                tmp.write(chunk)

        if not tmp_path or os.path.getsize(tmp_path) == 0:
            raise HTTPException(status_code=400, detail="Empty audio file.")

        _log.info("analyze_age_gender_begin file=%s bytes=%d", file.filename or "", os.path.getsize(tmp_path))
        return await run_in_threadpool(_analyze_age_gender_sync, tmp_path)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Age-gender analysis failed: {e}") from e
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass


if __name__ == "__main__":
    _port = int(os.environ.get("AGE_GENDER_PORT", "8056"))
    uvicorn.run(app, host="0.0.0.0", port=_port)
