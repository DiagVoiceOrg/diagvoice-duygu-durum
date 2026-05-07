FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    OMP_NUM_THREADS=1 \
    MKL_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1 \
    NUMEXPR_MAX_THREADS=1 \
    HF_HOME=/app/.cache/huggingface \
    DIAGVOICE_BENCHMARK_CONFIG=/app/inference_api/config.docker.yaml \
    DIAGVOICE_MODEL=/app/models/is-sagligi.joblib \
    TEXT_TO_SENTIMENT_PORT=8050 \
    VOICE_TO_TEXT_PORT=8051 \
    VOICE_TO_SENTIMENT_PORT=8052 \
    INFERENCE_API_PORT=8053 \
    DISEASE_SERVICE_PORT=8054 \
    MENTAL_FITNESS_PORT=8055 \
    AGE_GENDER_PORT=8056 \
    DEPRESSION_SERVICE_PORT=8057 \
    TURKISH_PSYCH_CLASSIFIER_PORT=8058 \
    TURKISH_PSYCH_WEIGHTS_PATH=/app/models/mental-fitness-forgpt.safetensors \
    FUSION_PORT=8085 \
    TEXT_TO_SENTIMENT_URL=http://127.0.0.1:8050/analyze \
    VOICE_TO_TEXT_URL=http://127.0.0.1:8051/transcribe \
    VOICE_TO_SENTIMENT_URL=http://127.0.0.1:8052/analyze-audio \
    DISEASE_SERVICE_URL=http://127.0.0.1:8054/analyze-disease \
    MENTAL_FITNESS_URL=http://127.0.0.1:8055/analyze-mental \
    AGE_GENDER_URL=http://127.0.0.1:8056/analyze-age-gender \
    DEPRESSION_SERVICE_URL=http://127.0.0.1:8057/analyze-depression \
    TURKISH_PSYCH_CLASSIFIER_URL=http://127.0.0.1:8058/analyze \
    INFERENCE_API_URL=http://127.0.0.1:8053

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ffmpeg \
        supervisor \
        libsndfile1 \
        build-essential \
        cmake \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf

COPY fusion_service /app/fusion_service
COPY cms /app/cms
COPY inference_api /app/inference_api
COPY code /app/code
COPY text_to_sentiment /app/text_to_sentiment
COPY voice_to_text /app/voice_to_text
COPY voice_to_sentiment /app/voice_to_sentiment
COPY disease_service /app/disease_service
COPY mental_fitness /app/mental_fitness
COPY age-gender-model /app/age-gender-model
COPY depression_service /app/depression_service
COPY mental_fitness_turkish_psych_classifier /app/mental_fitness_turkish_psych_classifier
COPY models /app/models
COPY test-data /app/test-data
COPY .env /app/.env

# Ana API (fusion + CMS); mikro servisler konteyner içi 8050–8058.
EXPOSE 8085

CMD ["supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf"]

