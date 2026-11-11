"""
/v1 — anahtarlı, sürümlü resmi API (PROD_PLAN F1).

Kimlik doğrulama, scope ve limitler middleware'de (fusion_service.apikeys.auth) uygulanır; bu modül
yalnızca uçları tanımlar ve mevcut handler'lara yönlendirir. Handler'lar app.py'den `build_router`
ile verilir (app.py betik olarak çalıştığı için buradan import edilmez).

Eski uçlardan farkı:
  - Hata gövdesi her zaman {"error": {"code", "message", "request_id"}}
  - Birden çok model çalıştıran uçlarda (togg, fused) yanıtta "partial": true|false
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Optional

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse

from fusion_service.apikeys import scopes as S
from fusion_service.apikeys.limiter import limiter
from fusion_service.schemas import TextSentimentRequest, TurkishPsychSignalsRequest

V1_TAG = "v1"


def _with_partial(result: Any, error_keys: Optional[list[str]] = None) -> Any:
    """Dict yanıta 'partial' ekler: herhangi bir *_error alanı doluysa True."""
    if isinstance(result, JSONResponse) or not isinstance(result, dict):
        return result
    keys = error_keys or [k for k in result if k.endswith("_error")]
    result["partial"] = any(result.get(k) for k in keys)
    return result


def build_router(h: SimpleNamespace) -> APIRouter:
    r = APIRouter(prefix="/v1", tags=[V1_TAG])
    audio = File(..., description="Ses dosyası (WAV, M4A/AAC, MP3, FLAC, OGG, WEBM)")
    lang = Form("tr", description="Konuşma dili: tr | en | ar | auto")

    @r.post("/analyze/togg", summary="TOGG: ses emosyonu + WURSS")
    async def v1_togg(request: Request, file: UploadFile = audio):
        return _with_partial(await h.togg_analyze(request, file), ["audio_error", "disease_error"])

    @r.post("/analyze/fused", summary="Tam analiz: STT + tüm modeller")
    async def v1_fused(request: Request, file: UploadFile = audio, speech_language: str = lang):
        return _with_partial(await h.analyze_fused(request, file, speech_language))

    @r.post("/analyze/stt", summary="Konuşma tanıma")
    async def v1_stt(request: Request, file: UploadFile = audio, speech_language: str = lang):
        return await h.proxy_analyze_voice_to_text(request, file, speech_language)

    @r.post("/analyze/emotion_audio", summary="Ses emosyonu")
    async def v1_emotion_audio(request: Request, file: UploadFile = audio):
        return await h.proxy_analyze_voice_sentiment(request, file)

    @r.post("/analyze/disease_wurss", summary="WURSS sağlık sinyali")
    async def v1_disease(request: Request, file: UploadFile = audio):
        return await h.proxy_analyze_disease(request, file)

    @r.post("/analyze/depression", summary="Depresyon")
    async def v1_depression(request: Request, file: UploadFile = audio):
        return await h.proxy_analyze_depression(request, file)

    @r.post("/analyze/age_gender", summary="Yaş ve cinsiyet")
    async def v1_age_gender(request: Request, file: UploadFile = audio):
        return await h.proxy_analyze_age_gender(request, file)

    @r.post("/analyze/mental_fitness", summary="Mental fitness")
    async def v1_mental(request: Request, file: UploadFile = audio):
        return await h.proxy_analyze_mental_fitness(request, file)

    @r.post("/analyze/emotion_v2", summary="Çok kipli emosyon v2")
    async def v1_emotion_v2(
        request: Request,
        file: UploadFile = audio,
        speech_language: str = lang,
        transcript: Optional[str] = Form(None, description="Verilirse STT atlanır"),
    ):
        return await h.proxy_analyze_emotion_v2(request, file, speech_language, None, transcript)

    @r.post("/analyze/occupational_health", summary="İş sağlığı (benchmark v2)")
    async def v1_occupational(request: Request, file: UploadFile = audio,
                              transcript: str = Form("", description="İsteğe bağlı metin")):
        return await h.proxy_analyze_benchmark_v2(request, file, transcript)

    @r.post("/analyze/text_sentiment", summary="Metin duygu analizi")
    async def v1_text_sentiment(request: Request, body: TextSentimentRequest):
        return await h.proxy_analyze_text_sentiment(request, body)

    @r.post("/analyze/turkish_psych", summary="Türkçe psikolojik sinyaller")
    async def v1_turkish_psych(request: Request, body: TurkishPsychSignalsRequest):
        return await h.proxy_analyze_turkish_psych_signals(request, body)

    @r.get("/models", summary="Bu anahtarın erişebildiği analizler")
    async def v1_models(request: Request):
        key = request.state.api_key
        return {"models": S.visible_models(key.scopes)}

    @r.get("/me", summary="Anahtar bilgisi ve limitler")
    async def v1_me(request: Request):
        key = request.state.api_key
        return {
            "key_id": key.key_id,
            "type": key.type,
            "name": key.name,
            "client": key.client_name,
            "scopes": key.scopes,
            "limits": key.limits,
            "expires_at": key.expires_at,
            "active_requests": limiter.active(key.key_id),
        }

    return r
