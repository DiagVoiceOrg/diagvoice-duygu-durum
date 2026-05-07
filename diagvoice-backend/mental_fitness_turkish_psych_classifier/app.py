"""
Türkçe psikolojik sinyal metin sınıflandırma (Hugging Face Transformers).
mental_fitness servisinden bağımsız; ayrı HTTP portunda çalışır.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

import torch
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool
from transformers import pipeline

_ROOT = Path(__file__).resolve().parent
_DEFAULT_MODEL_DIR = str(_ROOT)

MODEL_DIR = os.environ.get("TURKISH_PSYCH_MODEL_DIR", _DEFAULT_MODEL_DIR).strip() or _DEFAULT_MODEL_DIR
LABEL_MAPS_PATH = Path(os.environ.get("TURKISH_PSYCH_LABEL_MAPS", str(Path(MODEL_DIR) / "label_maps.json")))
CATEGORY_NAMES_PATH = Path(
    os.environ.get("TURKISH_PSYCH_CATEGORY_NAMES_TR", str(_ROOT / "psych_category_names_tr.json"))
)

_log = logging.getLogger("diagvoice.turkish_psych_classifier")
_log.setLevel(getattr(logging, os.environ.get("DIAGVOICE_LOG_LEVEL", "INFO").upper(), logging.INFO))
if not _log.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [turkish_psych] %(message)s"))
    _log.addHandler(_h)
    _log.propagate = False

_infer_lock = threading.Lock()
_USE_INFER_LOCK = os.environ.get("TURKISH_PSYCH_USE_INFER_LOCK", "1").strip().lower() not in ("0", "false", "no")

_id2label_by_class_index: Dict[str, str] = {}
_category_names_tr: Dict[str, str] = {}
_classifier = None


def _load_label_maps() -> Dict[str, str]:
    if not LABEL_MAPS_PATH.is_file():
        _log.warning("label_maps.json bulunamadı: %s", LABEL_MAPS_PATH)
        return {}
    with open(LABEL_MAPS_PATH, encoding="utf-8") as f:
        data = json.load(f)
    raw = data.get("id2label") or {}
    return {str(k): str(v) for k, v in raw.items()}


def _load_category_names_tr() -> Dict[str, str]:
    if not CATEGORY_NAMES_PATH.is_file():
        return {}
    with open(CATEGORY_NAMES_PATH, encoding="utf-8") as f:
        data = json.load(f)
    out: Dict[str, str] = {}
    for k, v in data.items():
        if v is None:
            continue
        s = str(v).strip()
        if s:
            out[str(k)] = s
    return out


def _normalize_raw_label_to_label_id(raw: str, id2label: Dict[str, str]) -> str:
    """HF çıktısı (ör. LABEL_2 veya '10') -> config id2label değeri ('0'..'15' stringleri)."""
    s = str(raw).strip()
    m = re.match(r"(?i)^LABEL_(\d+)$", s)
    if m:
        idx = m.group(1)
        return id2label.get(idx, idx)
    return s


def _build_classifier():
    global _classifier
    device = 0 if torch.cuda.is_available() else -1
    _log.info("Model yükleniyor: %s device=%s", MODEL_DIR, device)
    # return_all_scores=True: tüm sınıfların skorları (tek etiketli modelde bile)
    _classifier = pipeline(
        "text-classification",
        model=MODEL_DIR,
        tokenizer=MODEL_DIR,
        return_all_scores=True,
        device=device,
    )
    _log.info("Pipeline hazır.")


app = FastAPI(title="Turkish psych signal text classifier")

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


@app.on_event("startup")
def _startup() -> None:
    global _id2label_by_class_index, _category_names_tr
    _id2label_by_class_index = _load_label_maps()
    _category_names_tr = _load_category_names_tr()
    try:
        _build_classifier()
    except Exception:
        _log.exception("Model yüklenemedi; /analyze 503 dönecek.")


class AnalyzeRequest(BaseModel):
    text: str = Field(..., min_length=1, description="Türkçe (veya desteklenen dilde) metin")


def _map_scores(raw_scores: Any) -> List[Dict[str, Any]]:
    """Pipeline çıktısını label_id + isteğe bağlı Türkçe isim ile zenginleştir."""
    if isinstance(raw_scores, dict):
        items: List[Dict[str, Any]] = [raw_scores]
    elif isinstance(raw_scores, list):
        items = [x for x in raw_scores if isinstance(x, dict)]
    else:
        items = []

    out: List[Dict[str, Any]] = []
    for it in items:
        raw_label = it.get("label", "")
        score = float(it.get("score", 0.0))
        label_id = _normalize_raw_label_to_label_id(str(raw_label), _id2label_by_class_index)
        name_tr = _category_names_tr.get(label_id)
        row: Dict[str, Any] = {
            "label_raw": str(raw_label),
            "label_id": label_id,
            "score": score,
        }
        if name_tr:
            row["category_name_tr"] = name_tr
        out.append(row)
    out.sort(key=lambda x: x["score"], reverse=True)
    return out


def _analyze_sync(text: str) -> Dict[str, Any]:
    if _classifier is None:
        raise RuntimeError("Model yüklü değil.")
    t = text.strip()
    if not t:
        raise ValueError("Boş metin.")

    def _run():
        return _classifier(t)

    if _USE_INFER_LOCK:
        with _infer_lock:
            raw = _run()
    else:
        raw = _run()

    # return_all_scores=True bazen [[{...},...]] (batch) döndürür
    if isinstance(raw, list) and raw and isinstance(raw[0], list):
        raw = raw[0]

    mapped = _map_scores(raw)
    top = mapped[0] if mapped else None
    return {
        "text": t,
        "predictions": mapped,
        "top_prediction": top,
    }


@app.get("/")
async def root():
    return {
        "message": "Türkçe psikolojik sinyal metin sınıflandırma (HF). POST /analyze JSON {text}.",
        "model_dir": MODEL_DIR,
        "category_names_file": str(CATEGORY_NAMES_PATH) if CATEGORY_NAMES_PATH.is_file() else None,
    }


@app.get("/health")
async def health():
    ok = _classifier is not None
    return {"ok": ok, "model_dir": MODEL_DIR}


@app.post("/analyze")
async def analyze(req: AnalyzeRequest):
    try:
        return await run_in_threadpool(_analyze_sync, req.text)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


if __name__ == "__main__":
    _port = int(os.environ.get("TURKISH_PSYCH_CLASSIFIER_PORT", "8058"))
    uvicorn.run(app, host="0.0.0.0", port=_port)
