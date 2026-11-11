"""Testler için sahte model servisi (registry/worker testleri)."""
import os

from fastapi import FastAPI, File, UploadFile

app = FastAPI()
model = None
LOADED_FROM = None


def load():
    global model, LOADED_FROM
    LOADED_FROM = os.environ.get("DUMMY_MODEL_PATH")
    if os.environ.get("DUMMY_FAIL_SILENTLY") == "1":
        model = None  # gerçek servislerdeki "try/except → None" davranışı
        return
    model = {"weights": open(LOADED_FROM, "rb").read()}


@app.post("/analyze")
async def analyze(file: UploadFile = File(...)):
    data = await file.read()
    return {"bytes": len(data), "loaded_from": LOADED_FROM}
