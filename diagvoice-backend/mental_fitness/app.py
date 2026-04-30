import os
import tempfile
import traceback

import fastapi
import numpy as np
import uvicorn
from fastapi import File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sklearn.base import BaseEstimator
import joblib

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


def _bytes_to_temp_file(audio_bytes: bytes, filename: str) -> str:
    """
    Gelen ses bytes'ını geçici bir dosyaya yazar ve yolunu döner.
    mental_fitness_classifier_v1.extract_features fonksiyonuyla
    aynı veri akışını kullanmak için sadece dosya yolu veriyoruz.
    """
    with tempfile.NamedTemporaryFile(delete=False, suffix=f"_{filename}") as tmp:
        tmp.write(audio_bytes)
        return tmp.name


@app.get("/")
async def root():
    return {
        "message": "Mental fitness (canlıda olan) servisi. Ses dosyanızı /analyze-mental endpoint'ine gönderin.",
        "model_path": MODEL_PATH,
        "transcript_validation": (
            "POST /validate-transcript-meaning (DeepSeek; DEEPSEEK_API_KEY veya REQUIRE_* ile zorunlu)"
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

    if _REQUIRE_DEEPSEEK and not DEEPSEEK_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="Transcript validation required but DEEPSEEK_API_KEY is not set.",
        )

    try:
        meaningful, reason = validate_transcript_meaningfulness(
            raw,
            body.language,
            api_key=DEEPSEEK_API_KEY or None,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e

    skipped = not DEEPSEEK_API_KEY and not _REQUIRE_DEEPSEEK
    return {"meaningful": meaningful, "reason": reason, "validation_skipped": skipped}


@app.post("/analyze-mental")
async def analyze_mental(file: UploadFile = File(...)):
    if _model is None:
        raise HTTPException(status_code=500, detail="Mental fitness model could not be loaded. Check server logs.")

    tmp_path = None
    try:
        audio_bytes = await file.read()
        if not audio_bytes:
            raise HTTPException(status_code=400, detail="Empty audio file.")

        # Bytes'ı geçici dosyaya yaz ve eğitimde kullanılan feature extractor ile özellik çıkar
        tmp_path = _bytes_to_temp_file(audio_bytes, file.filename or "audio")
        feats = extract_features(tmp_path, feature_set="rich")

        if feats is None:
            raise HTTPException(status_code=400, detail="Feature extraction returned no features.")

        # Eğitim scriptindeki gibi: (n_features,) -> (1, n_features)
        feats_reshaped = np.asarray(feats, dtype=np.float32).reshape(1, -1)

        # Tahmin ve olasılıklar
        raw_pred = _model.predict(feats_reshaped)[0]
        probs = None
        mental_fitness_score = None
        if hasattr(_model, "predict_proba"):
            probs_arr = _model.predict_proba(feats_reshaped)[0]
            probs = [float(x) for x in probs_arr.tolist()]

            # mental_fitness_classifier_v1'deki ile aynı skor hesabı
            classes = getattr(_model, "classes_", None)
            if classes is not None:
                classes_list = list(classes)
                if "healthy" in classes_list:
                    healthy_idx = classes_list.index("healthy")
                    mental_fitness_score = float(probs_arr[healthy_idx] * 100.0)
                elif "depression" in classes_list:
                    depression_idx = classes_list.index("depression")
                    mental_fitness_score = float((1.0 - probs_arr[depression_idx]) * 100.0)

        label = None
        pred_id = None
        classes = getattr(_model, "classes_", None)
        if classes is not None:
            classes_list = list(classes)
            # raw_pred string label olabilir (örn. "healthy"/"depression")
            if raw_pred in classes_list:
                pred_id = int(classes_list.index(raw_pred))
                label = str(raw_pred)
            else:
                # Numeric gelirse, yine index olarak ele al
                try:
                    idx = int(raw_pred)
                    if 0 <= idx < len(classes_list):
                        pred_id = idx
                        label = str(classes_list[idx])
                except (TypeError, ValueError):
                    label = str(raw_pred)

        return {
            "pred_id": pred_id,
            "pred_label": label,
            "probs": probs,
            "mental_fitness_score": None if mental_fitness_score is None else float(f"{mental_fitness_score:.2f}"),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Mental fitness analysis failed: {e}")
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8005)

