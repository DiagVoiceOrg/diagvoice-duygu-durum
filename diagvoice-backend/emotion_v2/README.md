# Emosyon v2 — Multimodal Stacking

DiagVoice backend içinde çalışan Emosyon v2 mikroservisi.

## Model

- Artifact: `/app/models/final_multimodal_stacking_model.joblib`
- İlk açılışta HF modelleri indirilir (Whisper Large V3 Turbo, multilingual-E5-large-instruct, WavLM Base+)

## Endpoint

- `POST /analyze-audio` — multipart: `file`, opsiyonel `language`, `transcript`
- `GET /health`, `GET /model-info`

Fusion proxy: `POST /analyze-emotion-v2` (port 8085)

## Ortam

| Değişken | Varsayılan |
|----------|------------|
| `EMOTION_V2_PORT` | `8059` |
| `EMOTION_V2_MODEL_PATH` | `/app/models/final_multimodal_stacking_model.joblib` |
| `EMOTION_V2_DEVICE` | otomatik (cuda varsa) |
| `EMOTION_V2_USE_INFER_LOCK` | `1` |

GPU önerilir; CPU-only ortamda ilk istek yavaş olabilir.
