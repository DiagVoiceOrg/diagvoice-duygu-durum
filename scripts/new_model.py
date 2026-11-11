"""
Yeni model iskeleti üretir (PROD_PLAN F2 — "yeni model ekleme: yarım gün").

  python scripts/new_model.py --id voice_fatigue --title "Ses yorgunluğu" --group gpu --input audio

Üretilenler:
  diagvoice-backend/services/<id>/__init__.py
  diagvoice-backend/services/<id>/app.py         load() + POST /analyze iskeleti
  diagvoice-backend/registry.yaml                 taslak kayıt (sha256 boş, v1 açık)

Sonraki adımlar docs/ADDING_A_MODEL.md'de.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "diagvoice-backend"

AUDIO_TEMPLATE = '''"""{title} — DiagVoice model servisi ({id}).

Worker (dv_worker) bu modülü import eder, `load()`'u bir kez çağırır ve `app`'i /{id} altına bağlar.
Model yolu registry.yaml'daki artefakttan env ile gelir: {env}.
"""
from __future__ import annotations

import os
import tempfile
import threading

import torch
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool

app = FastAPI(title="{title}")
device = "cuda" if torch.cuda.is_available() else "cpu"
model = None                     # registry `require: [model]` — None kalırsa /ready hata verir
_infer_lock = threading.Lock()   # GPU'da aynı anda tek çıkarım


def load() -> None:
    global model
    path = os.environ["{env}"]
    # TODO: modeli yükle, ör.:
    # model = MyNet(); model.load_state_dict(torch.load(path, map_location="cpu")); model.to(device).eval()
    model = {{"path": path}}


def _predict_sync(audio_path: str) -> dict:
    from audio_io import load_mono_float32  # 16 kHz mono float32

    y, sr = load_mono_float32(audio_path, sr=16000, mono=True)
    with _infer_lock, torch.inference_mode():
        # TODO: gerçek çıkarım
        score = float(len(y)) / sr
    return {{"score": score, "duration_sec": len(y) / sr}}


@app.post("/analyze")
async def analyze(file: UploadFile = File(...)):
    if model is None:
        raise HTTPException(503, "Model yüklenmedi")
    with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file.filename or ".wav")[1]) as tmp:
        tmp.write(await file.read())
        path = tmp.name
    try:
        return await run_in_threadpool(_predict_sync, path)
    finally:
        os.unlink(path)
'''

TEXT_TEMPLATE = '''"""{title} — DiagVoice model servisi ({id}). Metin girdili."""
from __future__ import annotations

import os
import threading

from fastapi import FastAPI, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

app = FastAPI(title="{title}")
model = None
_infer_lock = threading.Lock()


class TextIn(BaseModel):
    text: str


def load() -> None:
    global model
    path = os.environ["{env}"]
    model = {{"path": path}}  # TODO


def _predict_sync(text: str) -> dict:
    with _infer_lock:
        return {{"length": len(text)}}  # TODO


@app.post("/analyze")
async def analyze(body: TextIn):
    if model is None:
        raise HTTPException(503, "Model yüklenmedi")
    return await run_in_threadpool(_predict_sync, body.text)
'''

ENTRY = """
  {id}:
    title: {title}
    version: v1
    group: {group}
    module: services/{id}/app.py
    startup: [load]
    require: [model]
    artifacts:
      weights:
        path: {id}/v1/{weights}
        sha256: ""          # python scripts/hash_models.py --write
        env: {env}
    v1:
      endpoint: /analyze
      input: {input}
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", required=True, help="küçük harf, rakam, _ (ör. voice_fatigue)")
    ap.add_argument("--title", required=True)
    ap.add_argument("--group", choices=["gpu", "cpu"], default="gpu")
    ap.add_argument("--input", choices=["audio", "text"], default="audio")
    ap.add_argument("--weights", default="model.pt", help="ağırlık dosyasının adı")
    a = ap.parse_args()
    if not re.fullmatch(r"[a-z][a-z0-9_]{2,40}", a.id):
        print("--id: küçük harf ile başlamalı; yalnızca a-z, 0-9, _", file=sys.stderr)
        return 2
    reg = BACKEND / "registry.yaml"
    text = reg.read_text(encoding="utf-8")
    if re.search(rf"^  {a.id}:\s*$", text, re.M):
        print(f"registry'de zaten var: {a.id}", file=sys.stderr)
        return 2
    svc = BACKEND / "services" / a.id
    if svc.exists():
        print(f"klasör zaten var: {svc}", file=sys.stderr)
        return 2
    env = f"{a.id.upper()}_MODEL_PATH"
    svc.mkdir(parents=True)
    (BACKEND / "services" / "__init__.py").touch()
    (svc / "__init__.py").write_text("", encoding="utf-8")
    tpl = AUDIO_TEMPLATE if a.input == "audio" else TEXT_TEMPLATE
    (svc / "app.py").write_text(tpl.format(id=a.id, title=a.title, env=env), encoding="utf-8")

    entry = ENTRY.format(id=a.id, title=a.title, group=a.group, env=env, input=a.input, weights=a.weights)
    marker = "\n# Gateway profilleri"
    i = text.find(marker)
    text = text[:i].rstrip("\n") + "\n" + entry + text[i:] if i >= 0 else text + entry
    reg.write_text(text, encoding="utf-8")

    print(f"""Oluşturuldu:
  {svc / 'app.py'}
  registry.yaml → models.{a.id}

Sonraki adımlar (docs/ADDING_A_MODEL.md):
  1. Ağırlığı sunucuda MODEL_ROOT/{a.id}/v1/{a.weights} yoluna koy
  2. python scripts/hash_models.py --write       (sha256'yı registry'ye yazar)
  3. services/{a.id}/app.py içindeki TODO'ları doldur (load + _predict_sync)
  4. pytest tests/test_worker.py
  5. Sunucuda: docker compose restart backend  →  /v1/analyze/{a.id} ve model:{a.id} scope'u açılır""")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
