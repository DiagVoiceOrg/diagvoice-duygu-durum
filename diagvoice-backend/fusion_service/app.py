import asyncio
import io
import logging
import math
import os
import re
import sys
import tempfile
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, Optional

_BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

import fastapi
import httpx
import uvicorn
from fastapi import File, Form, HTTPException, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError, ResponseValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.responses import Response

from fusion_service.emotion_fusion import (
    DEFAULT_AUDIO_VALENCE_WEIGHTS,
    build_emotion_fusion_payload,
    load_fusion_config_from_env,
)
from fusion_service.openapi_tags import OPENAPI_TAGS, PROXY_JSON_RESPONSES
from fusion_service.schemas import (
    AnalyzeFusedResponse,
    EmotionFusionRequest,
    EmotionFusionResponse,
    ServiceInfoResponse,
    TextSentimentRequest,
    ToggAnalyzeResponse,
    TranscriptMeaningRequest,
    TurkishPsychSignalsRequest,
)


def _ipv4_loopback_url(url: str) -> str:
    """
    Tek Docker konteyner içinde supervisord ile yan yana servisler IPv4'te dinler.
    `localhost` bazen önce IPv6 (::1) olarak çözülür; httpx bağlantı düşer.
    İç servis URL'lerinde 127.0.0.1 kullanımını zorunlu kılar.
    """
    if not url or not isinstance(url, str):
        return url
    return re.sub(r"(?i)//localhost(?=:|/)", "//127.0.0.1", url.strip())


from code.stt.language import normalize_speech_language_code, speech_language_to_form_value


def _normalize_speech_language_for_stt(raw: Optional[str]) -> str:
    """UI kodu (tr|en|ar|auto) → standart speech_language kodu."""
    return normalize_speech_language_code(raw)


def _stt_language_form_value(raw: Optional[str]) -> str:
    """Fusion → voice_to_text `language` form alanı (Whisper adları veya auto)."""
    return speech_language_to_form_value(raw)


_CMS_ENABLED = os.environ.get("CMS_ENABLED", "1").strip().lower() not in ("0", "false", "no")

# Küçük multipart proxy istekleri: diske yazmadan bellekten upstream’e (0 = her zaman disk).
FUSION_PROXY_MAX_MEMORY_BYTES = int(os.environ.get("FUSION_PROXY_MAX_MEMORY_BYTES", str(8 * 1024 * 1024)))
FUSION_PROXY_MAX_MEMORY_BYTES = max(0, FUSION_PROXY_MAX_MEMORY_BYTES)

_upstream_httpx: Optional[httpx.AsyncClient] = None


@asynccontextmanager
async def _app_lifespan(_app: fastapi.FastAPI):
    global _upstream_httpx
    _upstream_httpx = httpx.AsyncClient(
        timeout=httpx.Timeout(
            float(os.environ.get("FUSION_HTTP_TIMEOUT_SEC", "900")),
            connect=float(os.environ.get("FUSION_HTTP_CONNECT_TIMEOUT_SEC", "30")),
            read=float(os.environ.get("FUSION_HTTP_READ_TIMEOUT_SEC", "900")),
        ),
        limits=httpx.Limits(max_keepalive_connections=32, max_connections=64),
    )
    try:
        if _CMS_ENABLED:
            import logging

            _log = logging.getLogger(__name__)
            try:
                from cms.database import ensure_indexes
                from cms.audio_recordings import ensure_storage_dir

                await ensure_indexes()
                ensure_storage_dir()
                _log.info("CMS Mongo indeksleri hazır.")
            except Exception:
                _log.exception("CMS ensure_indexes başarısız (izin / ağ / URI kontrol et).")

            try:
                from cms.seed import seed_admin_if_empty, seed_default_demo_if_missing

                await seed_admin_if_empty()
                await seed_default_demo_if_missing()
            except Exception:
                _log.exception(
                    "CMS seed başarısız — admin girişi için `users` koleksiyonu ve MONGO_URI / "
                    "CMS_ADMIN_EMAIL / CMS_ADMIN_PASSWORD ortam değişkenlerini kontrol et."
                )
        yield
    finally:
        if _upstream_httpx is not None:
            await _upstream_httpx.aclose()
            _upstream_httpx = None


app = fastapi.FastAPI(
    title="DiagVoice Fusion API",
    description=(
        "Ses tabanlı çoklu model analizi için tek giriş noktası: STT, duygu, hastalık, mental fitness, "
        "depresyon, yaş-cinsiyet ve isteğe bağlı benchmark. İç servislere proxy ve CMS (MongoDB) API'si.\n\n"
        "**OpenAPI:** Bu sayfa (`/docs`), ReDoc (`/redoc`) ve ham şema (`/openapi.json`) FastAPI tarafından "
        "otomatik üretilir. Ayrıntılı iş kuralları için depodaki `FUSION_API_REFERENCE.md` dosyasına bakın."
    ),
    version="1.0.0",
    lifespan=_app_lifespan,
    openapi_tags=OPENAPI_TAGS,
)

_cors_origins_raw = os.environ.get(
    "CORS_ALLOW_ORIGINS",
    "https://diagvoice.huseyinalav.me,https://diagvoice.com,https://www.diagvoice.com,"
    "http://localhost:5173,http://127.0.0.1:5173,"
    "https://landing.diagvoice.com,"
    "https://duygudurum.diagvoice.com,https://emosyon.diagvoice.com,https://algoritmalar.diagvoice.com,https://yolarkadasim.diagvoice.com",
)
_cors_allow_origins = [o.strip() for o in _cors_origins_raw.split(",") if o.strip()]

@app.exception_handler(RequestValidationError)
async def _request_validation_exception_handler(request: Request, exc: RequestValidationError):
    from cms.usage_audit import error_details_from_validation, set_request_error_audit

    errs = exc.errors()
    set_request_error_audit(request, error_details_from_validation(errs))
    if request.url.path.startswith("/wellness/"):
        msg = errs[0].get("msg", "Geçersiz istek.") if errs else "Geçersiz istek."
        return JSONResponse(status_code=400, content={"error": str(msg)})
    return JSONResponse(status_code=422, content={"detail": errs})


@app.exception_handler(HTTPException)
async def _http_exception_handler(request: Request, exc: HTTPException):
    from cms.usage_audit import error_details_from_http_exception, set_request_error_audit

    set_request_error_audit(request, error_details_from_http_exception(exc.status_code, exc.detail))
    if isinstance(exc.detail, (dict, list)):
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.exception_handler(ResponseValidationError)
async def _response_validation_exception_handler(request: Request, exc: ResponseValidationError):
    from cms.usage_audit import set_request_error_audit, summarize_validation_errors

    errs = exc.errors()
    set_request_error_audit(
        request,
        {
            "error_type": "response_validation",
            "error_source": "fusion_handler",
            "error_summary": summarize_validation_errors(errs),
            "validation_errors": errs[:20],
        },
    )
    return JSONResponse(status_code=500, content={"detail": "Response validation error", "errors": errs})


@app.exception_handler(Exception)
async def _unhandled_exception_handler(request: Request, exc: Exception):
    from cms.usage_audit import error_details_from_unhandled, set_request_error_audit

    if isinstance(exc, HTTPException):
        raise exc
    _log.exception("unhandled_exception path=%s", request.url.path)
    set_request_error_audit(request, error_details_from_unhandled(exc))
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def fusion_usage_audit_middleware(request: Request, call_next):
    """MongoDB fusion_api_logs: yol, metod, HTTP durumu, süre, istemci IP; handler `request.state.audit_details` ile zenginleştirir."""
    from cms.usage_audit import (
        AUDIT_LOG_ENABLED,
        _skip_path,
        client_ip_from_request,
        error_details_from_response_body,
        schedule_fusion_audit,
        set_request_error_audit,
    )

    path = request.url.path
    if not _CMS_ENABLED or not AUDIT_LOG_ENABLED or _skip_path(path):
        return await call_next(request)
    t0 = time.perf_counter()
    response = await call_next(request)
    duration_ms = (time.perf_counter() - t0) * 1000.0
    details = getattr(request.state, "audit_details", None)
    if details is None and response.status_code >= 400:
        body = b""
        async for chunk in response.body_iterator:
            body += chunk
        set_request_error_audit(request, error_details_from_response_body(response.status_code, body))
        details = getattr(request.state, "audit_details", None)
        response = Response(
            content=body,
            status_code=response.status_code,
            headers=dict(response.headers),
            media_type=response.media_type,
        )
    if details is not None and not isinstance(details, dict):
        details = {"value": str(details)[:2000]}
    audio_recording = getattr(request.state, "audio_recording", None)
    if audio_recording is not None and not isinstance(audio_recording, dict):
        audio_recording = None
    schedule_fusion_audit(
        path=path,
        method=request.method,
        http_status=response.status_code,
        duration_ms=duration_ms,
        client_ip=client_ip_from_request(request.scope.get("headers") or []),
        details=details,
        audio_recording=audio_recording,
    )
    return response


from fusion_service.wellness.router import router as wellness_router

app.include_router(wellness_router)

if _CMS_ENABLED:
    from cms.routers import admin_diagnostics as cms_admin_diagnostics
    from cms.routers import admin_pages as cms_admin_pages
    from cms.routers import admin_profiles as cms_admin_profiles
    from cms.routers import admin_usage as cms_admin_usage
    from cms.routers import auth as cms_auth
    from cms.routers import public as cms_public

    app.include_router(cms_auth.router)
    app.include_router(cms_public.router)
    app.include_router(cms_admin_pages.router)
    app.include_router(cms_admin_profiles.router)
    app.include_router(cms_admin_diagnostics.router)
    app.include_router(cms_admin_usage.router)

VOICE_TO_TEXT_URL = _ipv4_loopback_url(
    os.environ.get("VOICE_TO_TEXT_URL", "http://127.0.0.1:8051/transcribe")
)
TEXT_TO_SENTIMENT_URL = _ipv4_loopback_url(
    os.environ.get("TEXT_TO_SENTIMENT_URL", "http://127.0.0.1:8050/analyze")
)
VOICE_TO_SENTIMENT_URL = _ipv4_loopback_url(
    os.environ.get("VOICE_TO_SENTIMENT_URL", "http://127.0.0.1:8052/analyze-audio")
)
DISEASE_SERVICE_URL = _ipv4_loopback_url(
    os.environ.get("DISEASE_SERVICE_URL", "http://127.0.0.1:8054/analyze-disease")
)
MENTAL_FITNESS_URL = _ipv4_loopback_url(
    os.environ.get("MENTAL_FITNESS_URL", "http://127.0.0.1:8055/analyze-mental")
)
_mf_validate_env = os.environ.get("MENTAL_FITNESS_VALIDATE_URL", "").strip()
if _mf_validate_env:
    MENTAL_FITNESS_VALIDATE_URL = _ipv4_loopback_url(_mf_validate_env)
else:
    _mf_u = MENTAL_FITNESS_URL.rstrip("/")
    _mf_sfx = "/analyze-mental"
    if _mf_u.lower().endswith(_mf_sfx):
        MENTAL_FITNESS_VALIDATE_URL = _mf_u[: -len(_mf_sfx)] + "/validate-transcript-meaning"
    else:
        MENTAL_FITNESS_VALIDATE_URL = _mf_u + "/validate-transcript-meaning"
AGE_GENDER_URL = _ipv4_loopback_url(
    os.environ.get("AGE_GENDER_URL", "http://127.0.0.1:8056/analyze-age-gender")
)
DEPRESSION_SERVICE_URL = _ipv4_loopback_url(
    os.environ.get("DEPRESSION_SERVICE_URL", "http://127.0.0.1:8057/analyze-depression")
)

# Türkçe psik HF: /analyze-fused içinde çağrılmaz. Yalnız POST /analyze-turkish-psych-signals proxy hedefi.
# Boş string = bu proxy kapalı (iç :8058 doğrudan publish ediliyorsa). Dışarıda yalnız :8085 ise URL dolu olmalı.
_turkish_psych_raw = os.environ.get("TURKISH_PSYCH_CLASSIFIER_URL")
if _turkish_psych_raw is None:
    TURKISH_PSYCH_CLASSIFIER_URL = _ipv4_loopback_url("http://127.0.0.1:8058/analyze")
elif not str(_turkish_psych_raw).strip():
    TURKISH_PSYCH_CLASSIFIER_URL = ""
else:
    TURKISH_PSYCH_CLASSIFIER_URL = _ipv4_loopback_url(str(_turkish_psych_raw).strip())

# Emosyon v2 (multimodal stacking): /analyze-fused içinde çağrılmaz. Yalnız POST /analyze-emotion-v2 proxy hedefi.
_emotion_v2_raw = os.environ.get("EMOTION_V2_URL")
if _emotion_v2_raw is None:
    EMOTION_V2_URL = _ipv4_loopback_url("http://127.0.0.1:8059/analyze-audio")
elif not str(_emotion_v2_raw).strip():
    EMOTION_V2_URL = ""
else:
    EMOTION_V2_URL = _ipv4_loopback_url(str(_emotion_v2_raw).strip())

# benchmark_v2 (inference_api Flask, iç ağ) — boş string ile kapatılabilir
_inference_url_raw = os.environ.get("INFERENCE_API_URL")
if _inference_url_raw is None:
    INFERENCE_API_URL = "http://127.0.0.1:8053"
elif not str(_inference_url_raw).strip():
    INFERENCE_API_URL = ""
else:
    INFERENCE_API_URL = _ipv4_loopback_url(str(_inference_url_raw).strip().rstrip("/"))

# benchmark_v2 açıkken analyze-fused ile aynı CPU’da sklearn/feature yükü rekabet eder; gerekmiyorsa INFERENCE_API_URL boş bırakın.

HTTPX_TOTAL_TIMEOUT_SEC = float(os.environ.get("FUSION_HTTP_TIMEOUT_SEC", "900"))
HTTPX_CONNECT_TIMEOUT_SEC = float(os.environ.get("FUSION_HTTP_CONNECT_TIMEOUT_SEC", "30"))
HTTPX_READ_TIMEOUT_SEC = float(os.environ.get("FUSION_HTTP_READ_TIMEOUT_SEC", "900"))

# STT vb. cold start: ConnectError'da tekrar dene. Eski varsayılan 60×2s ≈ dakikalarca bekletiyordu.
FUSION_UPSTREAM_CONNECT_RETRIES = max(1, int(os.environ.get("FUSION_UPSTREAM_CONNECT_RETRIES", "10")))
FUSION_UPSTREAM_RETRY_DELAY_SEC = float(os.environ.get("FUSION_UPSTREAM_RETRY_DELAY_SEC", "1.0"))

_log = logging.getLogger("diagvoice.fusion")
_log.setLevel(getattr(logging, os.environ.get("DIAGVOICE_LOG_LEVEL", "INFO").upper(), logging.INFO))
if not _log.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [diagvoice.fusion] %(message)s"))
    _log.addHandler(_h)
    _log.propagate = False

_FUSION_CFG = load_fusion_config_from_env()
FUSION_W_TEXT = _FUSION_CFG.w_text
DYNAMIC_FUSION = _FUSION_CFG.dynamic_fusion
W_TEXT_MIN = _FUSION_CFG.w_text_min
W_TEXT_MAX = _FUSION_CFG.w_text_max
AUDIO_VALENCE_WEIGHTS = list(_FUSION_CFG.audio_valence_weights)


def _build_timeout() -> httpx.Timeout:
    return httpx.Timeout(
        HTTPX_TOTAL_TIMEOUT_SEC,
        connect=HTTPX_CONNECT_TIMEOUT_SEC,
        read=HTTPX_READ_TIMEOUT_SEC,
    )


def _upstream_client() -> httpx.AsyncClient:
    if _upstream_httpx is None:
        raise RuntimeError("Fusion upstream HTTP client not initialized (lifespan).")
    return _upstream_httpx


def _is_upstream_connection_error(exc: BaseException) -> bool:
    if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout)):
        return True
    if isinstance(exc, httpx.HTTPError) and exc.__cause__ is not None:
        return _is_upstream_connection_error(exc.__cause__)
    return False


async def _fusion_post_multipart_file(
    client: httpx.AsyncClient,
    url: str,
    tmp_path: str,
    *,
    file_field: str,
    upload_name: str,
    content_type: str,
    extra_form: Optional[Dict[str, str]] = None,
    step: str = "upstream",
) -> tuple[Optional[Dict[str, Any]], Optional[str]]:
    t0 = time.perf_counter()
    last_conn: Optional[BaseException] = None
    for attempt in range(FUSION_UPSTREAM_CONNECT_RETRIES):
        try:
            if attempt > 0:
                _log.warning(
                    "retry step=%s attempt=%s/%s url=%s sleep_s=%s",
                    step,
                    attempt + 1,
                    FUSION_UPSTREAM_CONNECT_RETRIES,
                    url,
                    FUSION_UPSTREAM_RETRY_DELAY_SEC,
                )
                await asyncio.sleep(FUSION_UPSTREAM_RETRY_DELAY_SEC)
            with open(tmp_path, "rb") as fh:
                files = {file_field: (upload_name, fh, content_type or "application/octet-stream")}
                r = await client.post(url, files=files, data=extra_form or None)
            r.raise_for_status()
            body = r.json()
            if not isinstance(body, dict):
                return None, f"non-dict JSON from {url}"
            _log.info(
                "upstream_ok step=%s url=%s http=%s total_ms=%.0f",
                step,
                url,
                r.status_code,
                (time.perf_counter() - t0) * 1000,
            )
            return body, None
        except (httpx.ConnectError, httpx.ConnectTimeout) as e:
            last_conn = e
            if attempt + 1 >= FUSION_UPSTREAM_CONNECT_RETRIES:
                _log.error(
                    "upstream_fail step=%s url=%s attempts=%s total_ms=%.0f err=%s",
                    step,
                    url,
                    FUSION_UPSTREAM_CONNECT_RETRIES,
                    (time.perf_counter() - t0) * 1000,
                    e,
                )
                return None, (
                    f"request failed (url={url}): upstream unreachable after "
                    f"{FUSION_UPSTREAM_CONNECT_RETRIES} attempts ({e})"
                )
            _log.warning("upstream_connect_error step=%s attempt=%s url=%s err=%s", step, attempt + 1, url, e)
            continue
        except Exception as e:
            if _is_upstream_connection_error(e) and attempt + 1 < FUSION_UPSTREAM_CONNECT_RETRIES:
                last_conn = e
                _log.warning("upstream_wrapped_connect_error step=%s attempt=%s err=%s", step, attempt + 1, e)
                continue
            _log.error("upstream_error step=%s url=%s total_ms=%.0f err=%s", step, url, (time.perf_counter() - t0) * 1000, e)
            return None, f"request failed (url={url}): {e}"
    return None, f"request failed (url={url}): {last_conn}"


async def _fusion_post_json(
    client: httpx.AsyncClient,
    url: str,
    payload: Dict[str, Any],
    *,
    step: str = "json_upstream",
) -> tuple[Optional[Dict[str, Any]], Optional[str]]:
    t0 = time.perf_counter()
    last_conn: Optional[BaseException] = None
    for attempt in range(FUSION_UPSTREAM_CONNECT_RETRIES):
        try:
            if attempt > 0:
                _log.warning(
                    "retry step=%s attempt=%s/%s url=%s",
                    step,
                    attempt + 1,
                    FUSION_UPSTREAM_CONNECT_RETRIES,
                    url,
                )
                await asyncio.sleep(FUSION_UPSTREAM_RETRY_DELAY_SEC)
            r = await client.post(url, json=payload)
            r.raise_for_status()
            body = r.json()
            if not isinstance(body, dict):
                return None, f"non-dict JSON from {url}"
            _log.info(
                "upstream_ok step=%s url=%s http=%s total_ms=%.0f",
                step,
                url,
                r.status_code,
                (time.perf_counter() - t0) * 1000,
            )
            return body, None
        except (httpx.ConnectError, httpx.ConnectTimeout) as e:
            last_conn = e
            if attempt + 1 >= FUSION_UPSTREAM_CONNECT_RETRIES:
                _log.error(
                    "upstream_fail step=%s url=%s attempts=%s total_ms=%.0f err=%s",
                    step,
                    url,
                    FUSION_UPSTREAM_CONNECT_RETRIES,
                    (time.perf_counter() - t0) * 1000,
                    e,
                )
                return None, (
                    f"request failed (url={url}): upstream unreachable after "
                    f"{FUSION_UPSTREAM_CONNECT_RETRIES} attempts ({e})"
                )
            _log.warning("upstream_connect_error step=%s attempt=%s url=%s err=%s", step, attempt + 1, url, e)
            continue
        except Exception as e:
            if _is_upstream_connection_error(e) and attempt + 1 < FUSION_UPSTREAM_CONNECT_RETRIES:
                last_conn = e
                continue
            _log.error("upstream_error step=%s url=%s err=%s", step, url, e)
            return None, f"request failed (url={url}): {e}"
    return None, f"request failed (url={url}): {last_conn}"


def _set_audit_details(request: Optional[Request], details: Dict[str, Any]) -> None:
    if request is not None:
        request.state.audit_details = details


def _upstream_error_fields(*pairs: tuple[str, Optional[str]]) -> dict[str, str]:
    """Başarısız upstream adımlarını audit için özetler."""
    failed = {name: err for name, err in pairs if err}
    return {"upstream_errors": failed} if failed else {}


def _proxy_upstream_error_detail(body: Any, http_status: int) -> dict[str, Any]:
    if http_status < 400:
        return {}
    from cms.usage_audit import normalize_error_detail

    if isinstance(body, dict):
        if body.get("detail") is not None:
            return {"upstream_error": normalize_error_detail(body["detail"])}
        if body.get("error") is not None:
            return {"upstream_error": normalize_error_detail(body["error"])}
        return {"upstream_error_body": normalize_error_detail(body)}
    if body is not None:
        return {"upstream_error": normalize_error_detail(body)}
    return {"upstream_error": f"HTTP {http_status}"}


async def _persist_upload_audio(
    request: Optional[Request],
    *,
    tmp_path: Optional[str] = None,
    mem_body: Optional[bytes] = None,
    original_filename: str = "audio",
    content_type: str = "application/octet-stream",
) -> None:
    if request is None:
        return
    from cms.audio_recordings import persist_request_audio

    await persist_request_audio(
        request,
        tmp_path=tmp_path,
        body=mem_body,
        original_filename=original_filename,
        content_type=content_type,
    )


async def _proxy_file_upload(
    upstream_url: str,
    file: UploadFile,
    *,
    request: Optional[Request] = None,
    file_field_name: str = "file",
    extra_form_data: Optional[Dict[str, str]] = None,
    proxy_name: str = "proxy_multipart",
) -> JSONResponse:
    tmp_path: Optional[str] = None
    mem_body: Optional[bytes] = None
    t_req = time.perf_counter()
    try:
        suffix = ""
        if file.filename:
            safe = file.filename.replace("/", "_").replace("\\", "_")
            suffix = f"_{safe}"
        ctype = file.content_type or "application/octet-stream"
        fname = file.filename or "audio"

        buf = bytearray()
        th = FUSION_PROXY_MAX_MEMORY_BYTES
        if th <= 0:
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                tmp_path = tmp.name
                while True:
                    chunk = await file.read(1024 * 1024)
                    if not chunk:
                        break
                    tmp.write(chunk)
        else:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                if tmp_path is None and len(buf) + len(chunk) <= th:
                    buf.extend(chunk)
                    continue
                if tmp_path is None:
                    t = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
                    tmp_path = t.name
                    t.write(buf)
                    t.write(chunk)
                    t.close()
                    buf.clear()
                else:
                    with open(tmp_path, "ab") as wf:
                        wf.write(chunk)

        if tmp_path is None:
            mem_body = bytes(buf)
            nbytes = len(mem_body)
            storage = "memory"
        else:
            nbytes = os.path.getsize(tmp_path)
            storage = "disk"

        _log.info(
            "proxy_begin name=%s upstream=%s file=%s bytes=%d storage=%s upload_ms=%.0f",
            proxy_name,
            upstream_url,
            fname,
            nbytes,
            storage,
            (time.perf_counter() - t_req) * 1000,
        )

        await _persist_upload_audio(
            request,
            tmp_path=tmp_path,
            mem_body=mem_body,
            original_filename=fname,
            content_type=ctype,
        )

        client = _upstream_client()
        r: Optional[httpx.Response] = None
        t_upstream = time.perf_counter()
        for attempt in range(FUSION_UPSTREAM_CONNECT_RETRIES):
            try:
                if attempt > 0:
                    _log.warning(
                        "proxy_retry name=%s attempt=%s/%s upstream=%s",
                        proxy_name,
                        attempt + 1,
                        FUSION_UPSTREAM_CONNECT_RETRIES,
                        upstream_url,
                    )
                    await asyncio.sleep(FUSION_UPSTREAM_RETRY_DELAY_SEC)
                if mem_body is not None:
                    files = {
                        file_field_name: (
                            fname,
                            io.BytesIO(mem_body),
                            ctype,
                        )
                    }
                    r = await client.post(upstream_url, files=files, data=extra_form_data)
                else:
                    with open(tmp_path, "rb") as f:
                        files = {
                            file_field_name: (
                                fname,
                                f,
                                ctype,
                            )
                        }
                        r = await client.post(upstream_url, files=files, data=extra_form_data)
                break
            except (httpx.ConnectError, httpx.ConnectTimeout) as e:
                if attempt + 1 >= FUSION_UPSTREAM_CONNECT_RETRIES:
                    _log.error(
                        "proxy_fail name=%s upstream=%s attempts=%s total_ms=%.0f err=%s",
                        proxy_name,
                        upstream_url,
                        FUSION_UPSTREAM_CONNECT_RETRIES,
                        (time.perf_counter() - t_upstream) * 1000,
                        e,
                    )
                    _set_audit_details(
                        request,
                        {
                            "proxy": proxy_name,
                            "filename": fname,
                            "bytes": nbytes,
                            "error": "upstream_unreachable",
                        },
                    )
                    return JSONResponse(
                        status_code=503,
                        content={
                            "detail": (
                                f"Upstream not reachable after {FUSION_UPSTREAM_CONNECT_RETRIES} attempts: {e}"
                            )
                        },
                    )
            except Exception as e:
                if _is_upstream_connection_error(e) and attempt + 1 < FUSION_UPSTREAM_CONNECT_RETRIES:
                    continue
                _log.error("proxy_error name=%s upstream=%s err=%s", proxy_name, upstream_url, e)
                _set_audit_details(
                    request,
                    {"proxy": proxy_name, "filename": fname, "bytes": nbytes, "error": "proxy_exception", "message": str(e)[:800]},
                )
                return JSONResponse(status_code=502, content={"detail": f"Proxy error: {e}"})

        if r is None:
            _set_audit_details(
                request,
                {"proxy": proxy_name, "filename": fname, "bytes": nbytes, "error": "no_upstream_response"},
            )
            return JSONResponse(
                status_code=503,
                content={"detail": "Upstream not reachable (no response)."},
            )
        try:
            body = r.json()
        except Exception:
            body = {"detail": r.text or "Upstream returned non-JSON"}
        _log.info(
            "proxy_end name=%s upstream=%s http=%s upstream_ms=%.0f total_ms=%.0f",
            proxy_name,
            upstream_url,
            r.status_code,
            (time.perf_counter() - t_upstream) * 1000,
            (time.perf_counter() - t_req) * 1000,
        )
        from cms.usage_audit import truncate_proxy_json

        audit_payload: Dict[str, Any] = {
            "proxy": proxy_name,
            "filename": fname,
            "bytes": nbytes,
            "upstream_http": r.status_code,
            "storage": storage,
        }
        if r.status_code >= 400:
            audit_payload.update(_proxy_upstream_error_detail(body, r.status_code))
        else:
            truncated = truncate_proxy_json(body, proxy_name)
            if isinstance(truncated, dict):
                audit_payload["response"] = truncated.get("body", truncated)
        _set_audit_details(request, audit_payload)
        return JSONResponse(status_code=r.status_code, content=body)
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass


async def _proxy_json(
    request: Request,
    upstream_url: str,
    payload: Dict[str, Any],
    *,
    proxy_name: str = "proxy_json",
) -> JSONResponse:
    from cms.usage_audit import truncate_proxy_json

    t0 = time.perf_counter()
    _log.info("proxy_json_begin name=%s upstream=%s", proxy_name, upstream_url)
    r: Optional[httpx.Response] = None
    for attempt in range(FUSION_UPSTREAM_CONNECT_RETRIES):
        try:
            if attempt > 0:
                _log.warning("proxy_json_retry name=%s attempt=%s", proxy_name, attempt + 1)
                await asyncio.sleep(FUSION_UPSTREAM_RETRY_DELAY_SEC)
            r = await _upstream_client().post(upstream_url, json=payload)
            break
        except (httpx.ConnectError, httpx.ConnectTimeout) as e:
            if attempt + 1 >= FUSION_UPSTREAM_CONNECT_RETRIES:
                _log.error("proxy_json_fail name=%s upstream=%s err=%s", proxy_name, upstream_url, e)
                _set_audit_details(request, {"proxy": proxy_name, "error": "upstream_unreachable"})
                return JSONResponse(
                    status_code=503,
                    content={
                        "detail": (
                            f"Upstream not reachable after {FUSION_UPSTREAM_CONNECT_RETRIES} attempts: {e}"
                        )
                    },
                )
        except Exception as e:
            if _is_upstream_connection_error(e) and attempt + 1 < FUSION_UPSTREAM_CONNECT_RETRIES:
                continue
            _log.error("proxy_json_error name=%s err=%s", proxy_name, e)
            _set_audit_details(request, {"proxy": proxy_name, "error": "proxy_exception", "message": str(e)[:800]})
            return JSONResponse(status_code=502, content={"detail": f"Proxy error: {e}"})

    if r is None:
        _set_audit_details(request, {"proxy": proxy_name, "error": "no_upstream_response"})
        return JSONResponse(status_code=503, content={"detail": "Upstream not reachable (no response)."})
    try:
        body = r.json()
    except Exception:
        body = {"detail": r.text or "Upstream returned non-JSON"}
    _log.info(
        "proxy_json_end name=%s http=%s total_ms=%.0f",
        proxy_name,
        r.status_code,
        (time.perf_counter() - t0) * 1000,
    )
    request.state.audit_details = {
        **truncate_proxy_json(body, proxy_name),
        "upstream_http": r.status_code,
        **_proxy_upstream_error_detail(body if isinstance(body, dict) else {"detail": body}, r.status_code),
    }
    return JSONResponse(status_code=r.status_code, content=body)


@app.get("/", response_model=ServiceInfoResponse, tags=["meta"])
async def root():
    """Servis özeti, iç bağımlılık URL'leri ve OpenAPI dokümantasyon bağlantıları."""
    return {
        "message": (
            "Fusion service. POST audio to /analyze-fused — runs STT, text+audio sentiment fusion "
            "signals, disease / mental-fitness / age-gender / depression, and optional benchmark_v2."
        ),
        "deps": {
            "voice_to_text": VOICE_TO_TEXT_URL,
            "text_to_sentiment": TEXT_TO_SENTIMENT_URL,
            "voice_to_sentiment": VOICE_TO_SENTIMENT_URL,
            "disease_service": DISEASE_SERVICE_URL,
            "mental_fitness": MENTAL_FITNESS_URL,
            "mental_fitness_validate_transcript": MENTAL_FITNESS_VALIDATE_URL,
            "age_gender": AGE_GENDER_URL,
            "depression_service": DEPRESSION_SERVICE_URL,
            "turkish_psych_classifier": TURKISH_PSYCH_CLASSIFIER_URL or None,
            "emotion_v2": EMOTION_V2_URL or None,
            "benchmark_inference": INFERENCE_API_URL or None,
        },
        "togg_analyze": (
            "POST /togg-analyze (multipart file) -> voice_to_sentiment (emosyon) + disease_service (WURSS), paralel"
        ),
        "proxy": {
            "depression": "POST /analyze-depression (multipart file) -> forwards to depression_service",
            "voice_to_text": "POST /analyze-voice-to-text (multipart file) -> forwards to voice_to_text",
            "text_to_sentiment": "POST /analyze-text-sentiment (json: {text}) -> forwards to text_to_sentiment",
            "voice_to_sentiment": "POST /analyze-voice-sentiment (multipart file) -> forwards to voice_to_sentiment",
            "disease_service": "POST /analyze-disease (multipart file) -> forwards to disease_service",
            "mental_fitness": "POST /analyze-mental-fitness (multipart file) -> forwards to mental_fitness",
            "mental_fitness_transcript": (
                "POST /analyze-mental-fitness/validate-transcript-meaning (json: {text, language}) "
                "-> forwards to mental_fitness /validate-transcript-meaning"
            ),
            "age_gender": "POST /analyze-age-gender (multipart file) -> forwards to age_gender",
            "text_audio_fusion": "POST /analyze-text-audio-fusion (multipart file+text) -> forwards to text_to_sentiment /analyze_fusion",
            "benchmark_v2_proxy": "POST /analyze-benchmark-v2 (multipart file, optional transcript) -> forwards to benchmark /predict",
            "benchmark_v2": (
                f"POST {INFERENCE_API_URL}/predict (internal) — field 'audio', form 'transcript'"
                if INFERENCE_API_URL
                else "disabled (INFERENCE_API_URL empty)"
            ),
            "turkish_psych_signals": (
                "POST /analyze-turkish-psych-signals (json: {text}) -> HF Türkçe psikolojik sinyal servisi"
                if TURKISH_PSYCH_CLASSIFIER_URL
                else "disabled (TURKISH_PSYCH_CLASSIFIER_URL empty)"
            ),
            "emotion_v2": (
                "POST /analyze-emotion-v2 (multipart file, optional speech_language/transcript) -> multimodal stacking emosyon v2"
                if EMOTION_V2_URL
                else "disabled (EMOTION_V2_URL empty)"
            ),
            "emotion_fusion": (
                "POST /analyze-emotion-fusion (json: text_sentiment + audio) -> 4-class unified_emotion"
            ),
            "wellness_companion_chat": (
                "POST /wellness/companion/chat — json (metin) veya multipart (ses+messages); "
                "OpenAI orchestration + iç STT/mental-fitness; yanıt {message} veya {message, transcript}"
            ),
        },
        "fusion": {
            "w_text": FUSION_W_TEXT,
            "dynamic_fusion": DYNAMIC_FUSION,
            "w_text_min": W_TEXT_MIN,
            "w_text_max": W_TEXT_MAX,
            "audio_valence_weights": AUDIO_VALENCE_WEIGHTS,
        },
        "openapi": {
            "swagger_ui": "/docs",
            "redoc": "/redoc",
            "openapi_json": "/openapi.json",
        },
    }


@app.post(
    "/analyze-depression",
    tags=["proxy"],
    responses=PROXY_JSON_RESPONSES,
    summary="Depresyon analizi (proxy)",
)
async def proxy_analyze_depression(request: Request, file: UploadFile = File(..., description="Ses dosyası")):
    """
    Aracı endpoint: gelen ses dosyasını doğrudan depresyon servisine iletir.
    Yanıt gövdesi ve HTTP durumu depresyon servisiyle aynıdır (JSON).
    """
    return await _proxy_file_upload(
        DEPRESSION_SERVICE_URL, file, request=request, file_field_name="file", proxy_name="analyze-depression"
    )


@app.post(
    "/analyze-voice-to-text",
    tags=["proxy"],
    responses=PROXY_JSON_RESPONSES,
    summary="Konuşmayı metne çevir (proxy)",
)
async def proxy_analyze_voice_to_text(
    request: Request,
    file: UploadFile = File(..., description="Ses dosyası"),
    speech_language: str = Form("tr", description="Whisper dili: tr | en | ar | auto"),
):
    lg = _stt_language_form_value(speech_language)
    return await _proxy_file_upload(
        VOICE_TO_TEXT_URL,
        file,
        request=request,
        file_field_name="file",
        extra_form_data={"language": lg},
        proxy_name="analyze-voice-to-text",
    )


@app.post(
    "/analyze-text-sentiment",
    tags=["proxy"],
    responses=PROXY_JSON_RESPONSES,
    summary="Metin duygu analizi (proxy)",
)
async def proxy_analyze_text_sentiment(request: Request, body: TextSentimentRequest):
    return await _proxy_json(request, TEXT_TO_SENTIMENT_URL, {"text": body.text.strip()}, proxy_name="analyze-text-sentiment")


@app.post(
    "/analyze-emotion-fusion",
    response_model=EmotionFusionResponse,
    tags=["analysis"],
    summary="Metin + ses emosyon birleşimi (4 sınıf)",
)
async def analyze_emotion_fusion(request: Request, body: EmotionFusionRequest):
    """
    Metin duygu ve ses emosyonu sonuçlarını ortak 4-sınıf uzayında birleştirir.
    Kısmi profiller veya harici istemciler için; tam analiz `/analyze-fused` içinde de üretilir.
    """
    text_payload = body.text_sentiment.model_dump() if body.text_sentiment else None
    audio_payload = body.audio.model_dump() if body.audio else None
    fusion = build_emotion_fusion_payload(text_payload, audio_payload, _FUSION_CFG)
    request.state.audit_details = {
        "route": "analyze-emotion-fusion",
        "has_text": text_payload is not None,
        "has_audio": audio_payload is not None,
        "unified_pred": (fusion.get("unified_emotion") or {}).get("pred_label"),
    }
    return fusion


@app.post(
    "/analyze-voice-sentiment",
    tags=["proxy"],
    responses=PROXY_JSON_RESPONSES,
    summary="Ses emosyonu (proxy)",
)
async def proxy_analyze_voice_sentiment(request: Request, file: UploadFile = File(..., description="Ses dosyası")):
    return await _proxy_file_upload(
        VOICE_TO_SENTIMENT_URL, file, request=request, file_field_name="file", proxy_name="analyze-voice-sentiment"
    )


@app.post(
    "/analyze-emotion-v2",
    tags=["proxy"],
    responses=PROXY_JSON_RESPONSES,
    summary="Emosyon v2 — multimodal stacking (proxy)",
)
async def proxy_analyze_emotion_v2(
    request: Request,
    file: UploadFile = File(..., description="Ses dosyası"),
    speech_language: str = Form("tr", description="STT dili: tr | en | ar | auto"),
    language: Optional[str] = Form(None, description="(Geriye dönük) turkish | english | arabic | auto"),
    transcript: Optional[str] = Form(None, description="Verilirse STT atlanır"),
    include_branches: bool = Query(False, description="Model dallarının olasılıklarını yanıta ekler"),
):
    """
    Multimodal stacking emosyon v2 (merkezi STT + E5 + WavLM + akustik).
    `/analyze-fused` zincirine dahil değildir. Mevcut v1 ses emosyonundan (`/analyze-voice-sentiment`) bağımsızdır.
    """
    if not EMOTION_V2_URL:
        raise HTTPException(status_code=503, detail="Emotion v2 disabled (EMOTION_V2_URL empty)")

    upstream_url = EMOTION_V2_URL
    if include_branches:
        upstream_url = f"{upstream_url}?include_branches=true"

    extra: Dict[str, str] = {"speech_language": _normalize_speech_language_for_stt(speech_language)}
    if language is not None and str(language).strip():
        extra["language"] = str(language).strip()
    if transcript is not None and str(transcript).strip():
        extra["transcript"] = str(transcript).strip()

    return await _proxy_file_upload(
        upstream_url,
        file,
        request=request,
        file_field_name="file",
        extra_form_data=extra or None,
        proxy_name="analyze-emotion-v2",
    )


@app.post(
    "/analyze-disease",
    tags=["proxy"],
    responses=PROXY_JSON_RESPONSES,
    summary="WURSS / hastalık (proxy)",
)
async def proxy_analyze_disease(request: Request, file: UploadFile = File(..., description="Ses dosyası")):
    return await _proxy_file_upload(
        DISEASE_SERVICE_URL, file, request=request, file_field_name="file", proxy_name="analyze-disease"
    )


@app.post(
    "/analyze-mental-fitness",
    tags=["proxy"],
    responses=PROXY_JSON_RESPONSES,
    summary="Mental fitness — ses (proxy)",
)
async def proxy_analyze_mental_fitness(request: Request, file: UploadFile = File(..., description="Ses dosyası")):
    return await _proxy_file_upload(
        MENTAL_FITNESS_URL, file, request=request, file_field_name="file", proxy_name="analyze-mental-fitness"
    )


@app.post(
    "/analyze-mental-fitness/validate-transcript-meaning",
    tags=["proxy"],
    responses=PROXY_JSON_RESPONSES,
    summary="Transcript anlamlılık doğrulama (proxy)",
)
async def proxy_validate_transcript_meaning(request: Request, body: TranscriptMeaningRequest):
    """Mental fitness servisindeki POST /validate-transcript-meaning ile aynı gövde."""
    return await _proxy_json(
        request,
        MENTAL_FITNESS_VALIDATE_URL,
        {"text": body.text, "language": body.language},
        proxy_name="validate-transcript-meaning",
    )


@app.post(
    "/analyze-age-gender",
    tags=["proxy"],
    responses=PROXY_JSON_RESPONSES,
    summary="Yaş ve cinsiyet (proxy)",
)
async def proxy_analyze_age_gender(request: Request, file: UploadFile = File(..., description="Ses dosyası")):
    return await _proxy_file_upload(
        AGE_GENDER_URL, file, request=request, file_field_name="file", proxy_name="analyze-age-gender"
    )


@app.post(
    "/analyze-text-audio-fusion",
    tags=["proxy"],
    responses=PROXY_JSON_RESPONSES,
    summary="Metin + ses valence birleşimi (proxy)",
)
async def proxy_analyze_text_audio_fusion(
    request: Request,
    text: str = Form(..., description="Metin (STT veya kullanıcı girdisi)"),
    audio: UploadFile = File(..., description="Ses dosyası — alan adı `audio`"),
    fusion_mode: str = Form("dynamic", description="text_to_sentiment /analyze_fusion fusion_mode"),
):
    return await _proxy_file_upload(
        f"{TEXT_TO_SENTIMENT_URL.rsplit('/', 1)[0]}/analyze_fusion",
        audio,
        request=request,
        file_field_name="audio",
        extra_form_data={"text": text, "fusion_mode": fusion_mode},
        proxy_name="analyze-text-audio-fusion",
    )


@app.post(
    "/analyze-benchmark-v2",
    tags=["proxy"],
    responses=PROXY_JSON_RESPONSES,
    summary="İş sağlığı benchmark v2 (proxy)",
)
async def proxy_analyze_benchmark_v2(
    request: Request,
    file: UploadFile = File(..., description="Ses dosyası — alan adı `audio` upstream'de"),
    transcript: str = Form("", description="İsteğe bağlı STT metni"),
):
    if not INFERENCE_API_URL:
        raise HTTPException(status_code=503, detail="benchmark_v2 disabled (INFERENCE_API_URL empty)")
    predict_url = f"{INFERENCE_API_URL}/predict"
    return await _proxy_file_upload(
        predict_url,
        file,
        request=request,
        file_field_name="audio",
        extra_form_data={"transcript": transcript or ""},
        proxy_name="analyze-benchmark-v2",
    )


@app.post(
    "/analyze-turkish-psych-signals",
    tags=["proxy"],
    responses=PROXY_JSON_RESPONSES,
    summary="Türkçe psikolojik sinyaller — metin HF (proxy)",
)
async def proxy_analyze_turkish_psych_signals(request: Request, body: TurkishPsychSignalsRequest):
    """
    Türkçe psikolojik sinyal HF modeli (mental_fitness ses servisinden bağımsız).
    `/analyze-fused` zincirine dahil değildir.
    """
    if not TURKISH_PSYCH_CLASSIFIER_URL:
        raise HTTPException(
            status_code=503,
            detail="Turkish psych classifier disabled (TURKISH_PSYCH_CLASSIFIER_URL empty)",
        )
    return await _proxy_json(
        request,
        TURKISH_PSYCH_CLASSIFIER_URL,
        {"text": body.text.strip()},
        proxy_name="analyze-turkish-psych-signals",
    )


@app.post(
    "/togg-analyze",
    response_model=ToggAnalyzeResponse,
    tags=["analysis"],
    summary="TOGG: ses emosyonu + WURSS (paralel)",
)
async def togg_analyze(request: Request, file: UploadFile = File(..., description="Ses dosyası")):
    """
    TOGG: tek ses dosyası → emosyon (voice_to_sentiment) ve WURSS (disease_service), paralel.
    Yanıt alanları analyze-fused ile uyumlu: audio / disease ve *_error.
    """
    tmp_path: Optional[str] = None
    upload_name = "audio.wav"
    file_bytes: Optional[int] = None
    try:
        suffix = ""
        if file.filename:
            safe = file.filename.replace("/", "_").replace("\\", "_")
            suffix = f"_{safe}"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp_path = tmp.name
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                tmp.write(chunk)

        assert tmp_path is not None
        disk = tmp_path

        audio_result: Optional[Dict[str, Any]] = None
        audio_err: Optional[str] = None
        disease_result: Optional[Dict[str, Any]] = None
        disease_err: Optional[str] = None

        upload_name = (file.filename or "audio.wav").replace("/", "_").replace("\\", "_")
        file_bytes = os.path.getsize(disk)
        ct = file.content_type or "application/octet-stream"
        await _persist_upload_audio(
            request,
            tmp_path=disk,
            original_filename=upload_name,
            content_type=ct,
        )
        _log.info(
            "togg_analyze begin upload_name=%s bytes=%d",
            upload_name,
            file_bytes,
        )

        async def _run_voice_sentiment(c: httpx.AsyncClient) -> None:
            nonlocal audio_result, audio_err
            audio_result, audio_err = await _fusion_post_multipart_file(
                c,
                VOICE_TO_SENTIMENT_URL,
                disk,
                file_field="file",
                upload_name=upload_name,
                content_type=ct,
                step="togg_voice_sentiment",
            )

        async def _run_disease(c: httpx.AsyncClient) -> None:
            nonlocal disease_result, disease_err
            disease_result, disease_err = await _fusion_post_multipart_file(
                c,
                DISEASE_SERVICE_URL,
                disk,
                file_field="file",
                upload_name=upload_name,
                content_type=ct,
                step="togg_disease",
            )

        async def _timed(name: str, coro):
            t0 = time.perf_counter()
            await coro
            _log.info("togg_analyze parallel_branch_done branch=%s ms=%.0f", name, (time.perf_counter() - t0) * 1000)

        client = _upstream_client()
        t_par = time.perf_counter()
        await asyncio.gather(
            _timed("voice_sentiment", _run_voice_sentiment(client)),
            _timed("disease", _run_disease(client)),
        )
        _log.info("togg_analyze parallel_gather_done total_ms=%.0f", (time.perf_counter() - t_par) * 1000)

        from cms.usage_audit import client_ip_from_request, redact_fused_details
        from fusion_service.togg_diversify import maybe_diversify_togg_response

        out: Dict[str, Any] = {
            "audio": audio_result,
            "audio_error": audio_err,
            "disease": disease_result,
            "disease_error": disease_err,
        }
        client_ip = client_ip_from_request(request.scope.get("headers") or [])
        out, diversify_meta = maybe_diversify_togg_response(out, scope_key=client_ip)
        audit_payload: Dict[str, Any] = {
            "route": "togg-analyze",
            "upload_name": upload_name,
            "file_bytes": file_bytes,
            "response": redact_fused_details(out),
            **_upstream_error_fields(("voice_sentiment", audio_err), ("disease", disease_err)),
        }
        if diversify_meta:
            audit_payload["diversify"] = diversify_meta
        request.state.audit_details = audit_payload
        return out
    except Exception as e:
        _set_audit_details(
            request,
            {
                "route": "togg-analyze",
                "upload_name": upload_name,
                "file_bytes": file_bytes,
                "error_type": type(e).__name__,
                "error_source": "togg-analyze_handler",
                "error_summary": str(e)[:800],
            },
        )
        raise
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass


@app.post(
    "/analyze-fused",
    response_model=AnalyzeFusedResponse,
    tags=["analysis"],
    summary="Birleşik ses analizi (tüm modeller + valence fusion)",
)
async def analyze_fused(
    request: Request,
    file: UploadFile = File(..., description="Ses dosyası"),
    speech_language: str = Form("tr", description="STT dili: tr | en | ar | auto"),
):
    """
    Tek ses dosyasında STT, metin/ses duygusu, hastalık, mental fitness, yaş-cinsiyet, depresyon
    ve isteğe bağlı benchmark_v2 çalıştırır; metin+ses valence birleşimi `fused` alanında döner.
    """
    tmp_path: Optional[str] = None
    upload_name = "audio.wav"
    stt_lang = "tr"
    _disk_bytes: Optional[int] = None
    try:
        # Stream upload to disk to avoid holding large files in memory.
        suffix = ""
        if file.filename:
            safe = file.filename.replace("/", "_").replace("\\", "_")
            suffix = f"_{safe}"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp_path = tmp.name
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                tmp.write(chunk)

        assert tmp_path is not None
        disk = tmp_path

        benchmark_v2_result: Optional[Dict[str, Any]] = None
        benchmark_v2_err: Optional[str] = None
        stt_text: Optional[str] = None
        stt_err: Optional[str] = None
        audio_result: Optional[Dict[str, Any]] = None
        audio_err: Optional[str] = None
        text_result: Optional[Dict[str, Any]] = None
        text_err: Optional[str] = None
        disease_result: Optional[Dict[str, Any]] = None
        disease_err: Optional[str] = None
        mental_fitness_result: Optional[Dict[str, Any]] = None
        mental_fitness_err: Optional[str] = None
        age_gender_result: Optional[Dict[str, Any]] = None
        age_gender_err: Optional[str] = None
        depression_result: Optional[Dict[str, Any]] = None
        depression_err: Optional[str] = None

        upload_name = (file.filename or "audio.wav").replace("/", "_").replace("\\", "_")
        ct = file.content_type or "application/octet-stream"
        _disk_bytes = os.path.getsize(disk)
        stt_lang = _normalize_speech_language_for_stt(speech_language)
        stt_form_lang = _stt_language_form_value(speech_language)
        await _persist_upload_audio(
            request,
            tmp_path=disk,
            original_filename=upload_name,
            content_type=ct,
        )
        _log.info(
            "analyze_fused begin upload_name=%s bytes=%d speech_language=%s",
            upload_name,
            _disk_bytes,
            stt_lang,
        )

        async def _run_stt(c: httpx.AsyncClient) -> None:
            nonlocal stt_text, stt_err
            body, err = await _fusion_post_multipart_file(
                c,
                VOICE_TO_TEXT_URL,
                disk,
                file_field="file",
                upload_name=upload_name,
                content_type=ct,
                extra_form={"language": stt_form_lang},
                step="fused_stt",
            )
            if err:
                stt_err = err
                return
            t = body.get("text") if body else None
            if t is None:
                stt_err = "voice_to_text: missing 'text' in response"
                return
            stt_text = str(t)

        async def _run_voice_sentiment(c: httpx.AsyncClient) -> None:
            nonlocal audio_result, audio_err
            audio_result, audio_err = await _fusion_post_multipart_file(
                c,
                VOICE_TO_SENTIMENT_URL,
                disk,
                file_field="file",
                upload_name=upload_name,
                content_type=ct,
                step="fused_voice_sentiment",
            )

        async def _run_disease(c: httpx.AsyncClient) -> None:
            nonlocal disease_result, disease_err
            disease_result, disease_err = await _fusion_post_multipart_file(
                c,
                DISEASE_SERVICE_URL,
                disk,
                file_field="file",
                upload_name=upload_name,
                content_type=ct,
                step="fused_disease",
            )

        async def _run_mental(c: httpx.AsyncClient) -> None:
            nonlocal mental_fitness_result, mental_fitness_err
            mental_fitness_result, mental_fitness_err = await _fusion_post_multipart_file(
                c,
                MENTAL_FITNESS_URL,
                disk,
                file_field="file",
                upload_name=upload_name,
                content_type=ct,
                step="fused_mental_fitness",
            )

        async def _run_age_gender(c: httpx.AsyncClient) -> None:
            nonlocal age_gender_result, age_gender_err
            age_gender_result, age_gender_err = await _fusion_post_multipart_file(
                c,
                AGE_GENDER_URL,
                disk,
                file_field="file",
                upload_name=upload_name,
                content_type=ct,
                step="fused_age_gender",
            )

        async def _run_depression(c: httpx.AsyncClient) -> None:
            nonlocal depression_result, depression_err
            depression_result, depression_err = await _fusion_post_multipart_file(
                c,
                DEPRESSION_SERVICE_URL,
                disk,
                file_field="file",
                upload_name=upload_name,
                content_type=ct,
                step="fused_depression",
            )

        predict_url = f"{INFERENCE_API_URL}/predict" if INFERENCE_API_URL else ""

        async def _run_benchmark(c: httpx.AsyncClient, transcript: str) -> None:
            nonlocal benchmark_v2_result, benchmark_v2_err
            benchmark_v2_result, benchmark_v2_err = await _fusion_post_multipart_file(
                c,
                predict_url,
                disk,
                file_field="audio",
                upload_name=upload_name,
                content_type=ct,
                extra_form={"transcript": transcript or ""},
                step="fused_benchmark_v2",
            )

        async def _timed(name: str, coro):
            t0 = time.perf_counter()
            await coro
            _log.info("analyze_fused parallel_branch_done branch=%s ms=%.0f", name, (time.perf_counter() - t0) * 1000)

        client = _upstream_client()
        t_par = time.perf_counter()
        await asyncio.gather(
            _timed("stt", _run_stt(client)),
            _timed("voice_sentiment", _run_voice_sentiment(client)),
            _timed("disease", _run_disease(client)),
            _timed("mental_fitness", _run_mental(client)),
            _timed("age_gender", _run_age_gender(client)),
            _timed("depression", _run_depression(client)),
        )
        _log.info(
            "analyze_fused parallel_gather_done total_ms=%.0f (en yavaş dal yukarıdaki max)",
            (time.perf_counter() - t_par) * 1000,
        )

        transcript = (stt_text or "").strip()
        if transcript:
            t_txt = time.perf_counter()
            text_result, text_err = await _fusion_post_json(
                client,
                TEXT_TO_SENTIMENT_URL,
                {"text": transcript},
                step="fused_text_sentiment",
            )
            _log.info(
                "analyze_fused text_sentiment_done ms=%.0f err=%s",
                (time.perf_counter() - t_txt) * 1000,
                text_err is not None,
            )
        elif stt_err:
            text_err = f"text_sentiment skipped: STT failed ({stt_err})"
        elif stt_text is not None:
            text_err = "skipped: empty transcript after STT"
        else:
            text_err = "text_sentiment skipped: no transcript"

        if INFERENCE_API_URL:
            t_bm = time.perf_counter()
            await _run_benchmark(client, transcript)
            _log.info(
                "analyze_fused benchmark_v2_done ms=%.0f err=%s",
                (time.perf_counter() - t_bm) * 1000,
                benchmark_v2_err is not None,
            )
        else:
            _log.info("analyze_fused benchmark_v2 skipped (INFERENCE_API_URL empty)")

        # Normalize to valence [0,1] and 4-class unified emotion
        text_sentiment_for_response = None
        if text_result:
            text_sentiment_for_response = dict(text_result)
            if "sentiment" not in text_sentiment_for_response and "label" in text_sentiment_for_response:
                text_sentiment_for_response["sentiment"] = text_sentiment_for_response["label"]

        fusion_payload = build_emotion_fusion_payload(text_result, audio_result, _FUSION_CFG)
        valence_text = fusion_payload.get("valence_text")
        valence_audio = fusion_payload.get("valence_audio")
        fused = fusion_payload.get("fused")
        confidence = fusion_payload.get("confidence")
        unified_emotion = fusion_payload.get("unified_emotion")
        _log.info(
            "analyze_fused response_ready stt_ok=%s transcript_len=%d unified=%s",
            stt_err is None,
            len((stt_text or "").strip()),
            (unified_emotion or {}).get("pred_label") if isinstance(unified_emotion, dict) else None,
        )

        from cms.usage_audit import redact_fused_details

        out: Dict[str, Any] = {
            "text": stt_text,
            "text_error": stt_err,
            "audio": audio_result,
            "audio_error": audio_err,
            "disease": disease_result,
            "disease_error": disease_err,
            "mental_fitness": mental_fitness_result,
            "mental_fitness_error": mental_fitness_err,
            "age_gender": age_gender_result,
            "age_gender_error": age_gender_err,
            "depression": depression_result,
            "depression_error": depression_err,
            "benchmark_v2": benchmark_v2_result,
            "benchmark_v2_error": benchmark_v2_err,
            "text_sentiment": text_sentiment_for_response,
            "text_sentiment_error": text_err,
            "valence_text": valence_text,
            "valence_audio": valence_audio,
            "confidence": confidence,
            "fused": fused,
            "unified_emotion": unified_emotion,
        }
        request.state.audit_details = {
            "route": "analyze-fused",
            "upload_name": upload_name,
            "speech_language": stt_lang,
            "file_bytes": _disk_bytes,
            "response": redact_fused_details(out),
            **_upstream_error_fields(
                ("stt", stt_err),
                ("voice_sentiment", audio_err),
                ("disease", disease_err),
                ("mental_fitness", mental_fitness_err),
                ("age_gender", age_gender_err),
                ("depression", depression_err),
                ("text_sentiment", text_err),
                ("benchmark_v2", benchmark_v2_err),
            ),
        }
        return out
    except Exception as e:
        _set_audit_details(
            request,
            {
                "route": "analyze-fused",
                "upload_name": upload_name,
                "speech_language": stt_lang,
                "file_bytes": _disk_bytes,
                "error_type": type(e).__name__,
                "error_source": "analyze-fused_handler",
                "error_summary": str(e)[:800],
            },
        )
        raise
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass


if __name__ == "__main__":
    _fusion_port = int(os.environ.get("FUSION_PORT", "8085"))
    uvicorn.run(app, host="0.0.0.0", port=_fusion_port)
