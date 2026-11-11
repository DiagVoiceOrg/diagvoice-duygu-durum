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

from fastapi import APIRouter, File, Form, Query, Request, UploadFile
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

    # registry.yaml'dan otomatik açılan modeller (yeni model eklemek için kod yazmak gerekmez).
    # Sabit uçlardan SONRA tanımlanır; böylece yukarıdaki yollar önceliklidir.
    @r.post("/analyze/{model_id}", summary="Registry'deki diğer modeller (registry.yaml → v1)")
    async def v1_registry_model(model_id: str, request: Request):
        import os

        import httpx

        spec = S.REGISTRY_V1.get(model_id)
        if spec is None:
            from fastapi import HTTPException

            raise HTTPException(404, f"Model bulunamadı: {model_id}")
        base = os.environ.get("WORKER_CPU_URL" if spec["group"] == "cpu" else "WORKER_GPU_URL") or (
            "http://127.0.0.1:8061" if spec["group"] == "cpu" else "http://127.0.0.1:8060"
        )
        url = f"{base.rstrip('/')}/{model_id}{spec['endpoint']}"
        client = h.upstream_client()
        try:
            if spec["input"] == "text":
                resp = await client.post(url, json=await request.json())
            else:
                form = await request.form()
                up = form.get("file")
                if up is None or not hasattr(up, "read"):
                    from fusion_service.apikeys.errors import error_response

                    return error_response(request, 422, "invalid_request", "multipart 'file' alanı gerekli")
                data = {k: v for k, v in form.items() if k != "file" and isinstance(v, str)}
                resp = await client.post(url, files={"file": (up.filename or "audio", await up.read(),
                                                              up.content_type or "application/octet-stream")}, data=data)
        except httpx.HTTPError as e:
            from fusion_service.apikeys.errors import error_response

            return error_response(request, 502, "upstream_error", f"Model servisine ulaşılamadı: {type(e).__name__}")
        try:
            body = resp.json()
        except ValueError:
            body = {"raw": resp.text[:2000]}
        if resp.status_code >= 400:
            from fusion_service.apikeys.errors import error_response

            msg = body.get("detail") if isinstance(body, dict) and isinstance(body.get("detail"), str) else "Model servisi hata döndü."
            return error_response(request, 502 if resp.status_code >= 500 else resp.status_code,
                                  "upstream_error" if resp.status_code >= 500 else "invalid_request", msg)
        return body

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
            "active_requests": await limiter.active(key.key_id),
        }

    # ------------------------------------------------------------------ asenkron işler (F4)
    def _jobs_or_error(request: Request):
        from fusion_service.apikeys.errors import error_response
        from fusion_service.jobs import store

        if not store.enabled():
            return error_response(request, 503, "jobs_disabled", "İş kuyruğu bu sunucuda etkin değil (REDIS_URL).")
        return None

    @r.post("/jobs", status_code=202, summary="Asenkron iş gönder (togg, fused veya tek model)")
    async def v1_jobs_submit(
        request: Request,
        file: UploadFile = audio,
        kind: str = Form(..., description="togg | fused | stt | emotion_audio | disease_wurss | depression | age_gender | "
                                          "mental_fitness | emotion_v2 | occupational_health"),
        speech_language: Optional[str] = Form(None, description="fused / stt / emotion_v2 için"),
        transcript: Optional[str] = Form(None, description="emotion_v2 / occupational_health için"),
        webhook_url: Optional[str] = Form(None, description="İş bitince POST edilir (https, herkese açık adres)"),
        wait: float = Query(0, ge=0, le=30, description="Sonucu en fazla bu kadar saniye bekle; bitmezse 202"),
    ):
        from fusion_service.apikeys.errors import ApiError, error_response
        from fusion_service.jobs import queue as JQ

        if (err := _jobs_or_error(request)) is not None:
            return err
        key = request.state.api_key
        try:
            if kind not in JQ.KINDS:
                raise ApiError(422, "invalid_request", f"Bilinmeyen iş türü: {kind}")
            scope = JQ.KINDS[kind][0]
            if not S.allowed(key.scopes, scope):
                raise ApiError(403, "scope_denied", f"Bu anahtarın '{scope}' erişimi yok.")
            if webhook_url:
                JQ.validate_webhook_url(webhook_url)
            params = {k: v for k, v in (("speech_language", speech_language), ("transcript", transcript)) if v}
            job = await JQ.submit(key=key, kind=kind, filename=file.filename or "audio", content=await file.read(),
                                  content_type=file.content_type or "", params=params, webhook_url=webhook_url)
        except ApiError as e:
            return error_response(request, e.status, e.code, e.message, headers=e.headers)
        if wait > 0:
            job = await JQ.wait_for(job["job_id"], key.key_id, wait)
        done = job["status"] in ("succeeded", "failed", "cancelled")
        return JSONResponse(job, status_code=200 if done else 202,
                            headers=None if done else {"Location": f"/v1/jobs/{job['job_id']}"})

    @r.get("/jobs/{job_id}", summary="İş durumu ve sonucu")
    async def v1_jobs_get(request: Request, job_id: str,
                          wait: float = Query(0, ge=0, le=30, description="Bitene kadar en fazla bu kadar bekle")):
        from fusion_service.apikeys.errors import error_response
        from fusion_service.jobs import queue as JQ

        if (err := _jobs_or_error(request)) is not None:
            return err
        key = request.state.api_key
        job = await (JQ.wait_for(job_id, key.key_id, wait) if wait > 0 else JQ.get(job_id, key.key_id))
        if job is None:
            return error_response(request, 404, "not_found", "İş bulunamadı (süresi dolmuş veya başka anahtara ait).")
        return job

    @r.delete("/jobs/{job_id}", summary="Bekleyen işi iptal et")
    async def v1_jobs_cancel(request: Request, job_id: str):
        from fusion_service.apikeys.errors import error_response
        from fusion_service.jobs import queue as JQ

        if (err := _jobs_or_error(request)) is not None:
            return err
        job = await JQ.cancel(job_id, request.state.api_key.key_id)
        if job is None:
            return error_response(request, 404, "not_found", "İş bulunamadı.")
        return job

    return r
