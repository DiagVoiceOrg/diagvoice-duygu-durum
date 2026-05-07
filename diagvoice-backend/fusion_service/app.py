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
from fastapi import Body, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse


def _ipv4_loopback_url(url: str) -> str:
    """
    Tek Docker konteyner içinde supervisord ile yan yana servisler IPv4'te dinler.
    `localhost` bazen önce IPv6 (::1) olarak çözülür; httpx bağlantı düşer.
    İç servis URL'lerinde 127.0.0.1 kullanımını zorunlu kılar.
    """
    if not url or not isinstance(url, str):
        return url
    return re.sub(r"(?i)//localhost(?=:|/)", "//127.0.0.1", url.strip())


def _normalize_speech_language_for_stt(raw: Optional[str]) -> str:
    """UI kodu (tr|en|ar) → voice_to_text Form `language`; STT tarafında Whisper diline çevrilir."""
    s = (raw or "tr").strip().lower()
    return s if s in {"tr", "en", "ar"} else "tr"


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

                await ensure_indexes()
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


app = fastapi.FastAPI(lifespan=_app_lifespan)

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

if _CMS_ENABLED:
    from cms.routers import admin_diagnostics as cms_admin_diagnostics
    from cms.routers import admin_pages as cms_admin_pages
    from cms.routers import admin_profiles as cms_admin_profiles
    from cms.routers import auth as cms_auth
    from cms.routers import public as cms_public

    app.include_router(cms_auth.router)
    app.include_router(cms_public.router)
    app.include_router(cms_admin_pages.router)
    app.include_router(cms_admin_profiles.router)
    app.include_router(cms_admin_diagnostics.router)

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

# Türkçe psikolojik sinyal (HF metin sınıflandırma) — boş string ile kapatılabilir
_turkish_psych_raw = os.environ.get("TURKISH_PSYCH_CLASSIFIER_URL")
if _turkish_psych_raw is None:
    TURKISH_PSYCH_CLASSIFIER_URL = _ipv4_loopback_url("http://127.0.0.1:8058/analyze")
elif not str(_turkish_psych_raw).strip():
    TURKISH_PSYCH_CLASSIFIER_URL = ""
else:
    TURKISH_PSYCH_CLASSIFIER_URL = _ipv4_loopback_url(str(_turkish_psych_raw).strip())

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

FUSION_W_TEXT = float(os.environ.get("FUSION_W_TEXT", "0.5"))
FUSION_W_TEXT = max(0.0, min(1.0, FUSION_W_TEXT))

DYNAMIC_FUSION = os.environ.get("DYNAMIC_FUSION", "1").strip() not in {"0", "false", "False"}

# Clamp range for dynamic w_text
W_TEXT_MIN = float(os.environ.get("W_TEXT_MIN", "0.2"))
W_TEXT_MAX = float(os.environ.get("W_TEXT_MAX", "0.8"))
W_TEXT_MIN = max(0.0, min(1.0, W_TEXT_MIN))
W_TEXT_MAX = max(0.0, min(1.0, W_TEXT_MAX))
if W_TEXT_MIN > W_TEXT_MAX:
    W_TEXT_MIN, W_TEXT_MAX = W_TEXT_MAX, W_TEXT_MIN

# Audio emotion class order based on your training script:
# 0 sadness, 1 fear, 2 happiness, 3 anger
#
# Convert to valence (0..1) using a weighted sum of probabilities:
#   v_raw = sum(p_i * w_i) where w_i in [-1..1]
#   valence = (v_raw + 1) / 2
# and then modulate by intensity (0..1) to reduce impact when the model is unsure:
#   valence = 0.5 + intensity * (v_raw / 2)
DEFAULT_AUDIO_VALENCE_WEIGHTS = [-1.0, -0.6, 1.0, -0.8]


def _load_audio_valence_weights() -> list[float]:
    raw = os.environ.get("AUDIO_VALENCE_WEIGHTS", "")
    if not raw.strip():
        return DEFAULT_AUDIO_VALENCE_WEIGHTS
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if len(parts) != 4:
        return DEFAULT_AUDIO_VALENCE_WEIGHTS
    try:
        ws = [float(p) for p in parts]
        if any(w < -1.0 or w > 1.0 for w in ws):
            return DEFAULT_AUDIO_VALENCE_WEIGHTS
        return ws
    except Exception:
        return DEFAULT_AUDIO_VALENCE_WEIGHTS


AUDIO_VALENCE_WEIGHTS = _load_audio_valence_weights()


def text_sentiment_to_valence(sentiment_label: str, score: float) -> float:
    lab = (sentiment_label or "").upper()
    s = float(score)
    if lab == "POSITIVE":
        v = s
    elif lab == "NEGATIVE":
        v = 1.0 - s
    else:
        # Unknown label; fall back to neutral-ish
        v = 0.5
    return max(0.0, min(1.0, v))


def text_valence_confidence(valence: Optional[float]) -> Optional[float]:
    if valence is None:
        return None
    # distance to 0.5 mapped to [0..1]
    v = float(valence)
    conf = min(1.0, max(0.0, abs(v - 0.5) * 2.0))
    return conf


def audio_entropy_confidence(probs: Any) -> Optional[float]:
    if not isinstance(probs, list) or len(probs) < 4:
        return None
    try:
        p = [max(1e-12, float(x)) for x in probs[:4]]
        s = sum(p)
        p = [x / s for x in p]
        ent = -sum(x * math.log(x) for x in p)
        ent_max = math.log(4.0)
        ent_norm = ent / ent_max
        # confidence is inverse entropy
        conf = 1.0 - ent_norm
        return max(0.0, min(1.0, conf))
    except Exception:
        return None


def audio_overall_confidence(intensity: Optional[float], probs: Any) -> Optional[float]:
    ent_conf = audio_entropy_confidence(probs)
    if intensity is None and ent_conf is None:
        return None
    inten = None
    if intensity is not None:
        inten = max(0.0, min(1.0, float(intensity)))

    if inten is None:
        return ent_conf
    if ent_conf is None:
        return inten

    # intensity says how strong emotion is; entropy says how peaked distribution is
    return max(0.0, min(1.0, 0.5 * inten + 0.5 * ent_conf))


def audio_probs_to_valence(probs: Any, intensity: Optional[float] = None) -> Optional[float]:
    if not isinstance(probs, list) or len(probs) < 4:
        return None

    try:
        p = [float(x) for x in probs[:4]]
        v_raw = sum(pi * wi for pi, wi in zip(p, AUDIO_VALENCE_WEIGHTS))
        v_raw = max(-1.0, min(1.0, v_raw))

        if intensity is None:
            v = (v_raw + 1.0) / 2.0
        else:
            inten = float(intensity)
            inten = max(0.0, min(1.0, inten))
            v = 0.5 + inten * (v_raw / 2.0)

        return max(0.0, min(1.0, float(v)))
    except Exception:
        return None


def fuse(valence_text: Optional[float], valence_audio: Optional[float], w_text: float) -> Dict[str, Any]:
    if valence_text is None and valence_audio is None:
        return {"valence": None, "label": None, "w_text": w_text}

    if valence_text is None:
        v = valence_audio
        w = 0.0
    elif valence_audio is None:
        v = valence_text
        w = 1.0
    else:
        w = w_text
        v = w * valence_text + (1.0 - w) * valence_audio

    label = "POSITIVE" if v is not None and v >= 0.5 else "NEGATIVE"
    return {"valence": v, "label": label, "w_text": w}


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


async def _proxy_file_upload(
    upstream_url: str,
    file: UploadFile,
    *,
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
                return JSONResponse(status_code=502, content={"detail": f"Proxy error: {e}"})

        if r is None:
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
        return JSONResponse(status_code=r.status_code, content=body)
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass


async def _proxy_json(
    upstream_url: str,
    payload: Dict[str, Any],
    *,
    proxy_name: str = "proxy_json",
) -> JSONResponse:
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
            return JSONResponse(status_code=502, content={"detail": f"Proxy error: {e}"})

    if r is None:
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
    return JSONResponse(status_code=r.status_code, content=body)


@app.get("/")
async def root():
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
            "benchmark_inference": INFERENCE_API_URL or None,
        },
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
        },
        "fusion": {
            "w_text": FUSION_W_TEXT,
            "dynamic_fusion": DYNAMIC_FUSION,
            "w_text_min": W_TEXT_MIN,
            "w_text_max": W_TEXT_MAX,
            "audio_valence_weights": AUDIO_VALENCE_WEIGHTS,
        },
    }


@app.post("/analyze-depression")
async def proxy_analyze_depression(file: UploadFile = File(...)):
    """
    Aracı endpoint: gelen ses dosyasını doğrudan depresyon servisine iletir.
    Yanıt gövdesi ve HTTP durumu depresyon servisiyle aynıdır (JSON).
    """
    return await _proxy_file_upload(DEPRESSION_SERVICE_URL, file, file_field_name="file", proxy_name="analyze-depression")


@app.post("/analyze-voice-to-text")
async def proxy_analyze_voice_to_text(
    file: UploadFile = File(...),
    speech_language: str = Form("tr"),
):
    lg = _normalize_speech_language_for_stt(speech_language)
    return await _proxy_file_upload(
        VOICE_TO_TEXT_URL,
        file,
        file_field_name="file",
        extra_form_data={"language": lg},
        proxy_name="analyze-voice-to-text",
    )


@app.post("/analyze-text-sentiment")
async def proxy_analyze_text_sentiment(payload: Dict[str, Any] = Body(...)):
    text = str(payload.get("text", "")).strip()
    if not text:
        raise HTTPException(status_code=400, detail="Body alanı 'text' zorunludur.")
    return await _proxy_json(TEXT_TO_SENTIMENT_URL, {"text": text}, proxy_name="analyze-text-sentiment")


@app.post("/analyze-voice-sentiment")
async def proxy_analyze_voice_sentiment(file: UploadFile = File(...)):
    return await _proxy_file_upload(VOICE_TO_SENTIMENT_URL, file, file_field_name="file", proxy_name="analyze-voice-sentiment")


@app.post("/analyze-disease")
async def proxy_analyze_disease(file: UploadFile = File(...)):
    return await _proxy_file_upload(DISEASE_SERVICE_URL, file, file_field_name="file", proxy_name="analyze-disease")


@app.post("/analyze-mental-fitness")
async def proxy_analyze_mental_fitness(file: UploadFile = File(...)):
    return await _proxy_file_upload(MENTAL_FITNESS_URL, file, file_field_name="file", proxy_name="analyze-mental-fitness")


@app.post("/analyze-mental-fitness/validate-transcript-meaning")
async def proxy_validate_transcript_meaning(payload: Dict[str, Any] = Body(...)):
    """Mental fitness servisindeki POST /validate-transcript-meaning ile aynı gövde: {text, language}."""
    return await _proxy_json(
        MENTAL_FITNESS_VALIDATE_URL,
        {"text": str(payload.get("text", "")), "language": str(payload.get("language", ""))},
        proxy_name="validate-transcript-meaning",
    )


@app.post("/analyze-age-gender")
async def proxy_analyze_age_gender(file: UploadFile = File(...)):
    return await _proxy_file_upload(AGE_GENDER_URL, file, file_field_name="file", proxy_name="analyze-age-gender")


@app.post("/analyze-text-audio-fusion")
async def proxy_analyze_text_audio_fusion(
    text: str = Form(...),
    audio: UploadFile = File(...),
    fusion_mode: str = Form("dynamic"),
):
    return await _proxy_file_upload(
        f"{TEXT_TO_SENTIMENT_URL.rsplit('/', 1)[0]}/analyze_fusion",
        audio,
        file_field_name="audio",
        extra_form_data={"text": text, "fusion_mode": fusion_mode},
        proxy_name="analyze-text-audio-fusion",
    )


@app.post("/analyze-benchmark-v2")
async def proxy_analyze_benchmark_v2(file: UploadFile = File(...), transcript: str = Form("")):
    if not INFERENCE_API_URL:
        raise HTTPException(status_code=503, detail="benchmark_v2 disabled (INFERENCE_API_URL empty)")
    predict_url = f"{INFERENCE_API_URL}/predict"
    return await _proxy_file_upload(
        predict_url,
        file,
        file_field_name="audio",
        extra_form_data={"transcript": transcript or ""},
        proxy_name="analyze-benchmark-v2",
    )


@app.post("/analyze-turkish-psych-signals")
async def proxy_analyze_turkish_psych_signals(payload: Dict[str, Any] = Body(...)):
    """
    Türkçe psikolojik sinyal HF modeli (mental_fitness ses/metin servisinden bağımsız).
    Gövde: {\"text\": \"...\"}
    """
    if not TURKISH_PSYCH_CLASSIFIER_URL:
        raise HTTPException(
            status_code=503,
            detail="Turkish psych classifier disabled (TURKISH_PSYCH_CLASSIFIER_URL empty)",
        )
    text = str(payload.get("text", "")).strip()
    if not text:
        raise HTTPException(status_code=400, detail="Body alanı 'text' zorunludur.")
    return await _proxy_json(
        TURKISH_PSYCH_CLASSIFIER_URL,
        {"text": text},
        proxy_name="analyze-turkish-psych-signals",
    )


@app.post("/analyze-fused")
async def analyze_fused(
    file: UploadFile = File(...),
    speech_language: str = Form("tr"),
):
    tmp_path: Optional[str] = None
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
                extra_form={"language": stt_lang},
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

    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass

    # Normalize to valence [0,1]
    # text_result: "sentiment" veya "label" (model formatına göre)
    valence_text = None
    if text_result and "score" in text_result:
        sentiment_label = text_result.get("sentiment") or text_result.get("label")
        if sentiment_label is not None:
            valence_text = text_sentiment_to_valence(sentiment_label, text_result.get("score"))

    # FE uyumu: text_sentiment'ta "sentiment" anahtarı olsun (bazı modeller "label" döner)
    text_sentiment_for_response = None
    if text_result:
        text_sentiment_for_response = dict(text_result)
        if "sentiment" not in text_sentiment_for_response and "label" in text_sentiment_for_response:
            text_sentiment_for_response["sentiment"] = text_sentiment_for_response["label"]

    valence_audio = None
    if audio_result and "probs" in audio_result:
        valence_audio = audio_probs_to_valence(audio_result.get("probs"), audio_result.get("intensity"))

    # Dynamic weighting
    text_conf = text_valence_confidence(valence_text)
    audio_conf = audio_overall_confidence(
        audio_result.get("intensity") if isinstance(audio_result, dict) else None,
        audio_result.get("probs") if isinstance(audio_result, dict) else None,
    )

    w_text_used = FUSION_W_TEXT
    if DYNAMIC_FUSION and valence_text is not None and valence_audio is not None and text_conf is not None and audio_conf is not None:
        # Higher confidence -> higher weight.
        # Map relative confidence to [W_TEXT_MIN..W_TEXT_MAX]
        ratio = text_conf / (text_conf + audio_conf + 1e-9)
        w_text_used = W_TEXT_MIN + (W_TEXT_MAX - W_TEXT_MIN) * ratio

    disagreement = None
    if valence_text is not None and valence_audio is not None:
        disagreement = abs(float(valence_text) - float(valence_audio))

    fused = fuse(valence_text, valence_audio, w_text_used)
    _log.info(
        "analyze_fused response_ready stt_ok=%s transcript_len=%d",
        stt_err is None,
        len((stt_text or "").strip()),
    )

    return {
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
        "confidence": {
            "text": text_conf,
            "audio": audio_conf,
            "disagreement": disagreement,
            "dynamic_fusion": DYNAMIC_FUSION,
        },
        "fused": fused,
    }


if __name__ == "__main__":
    _fusion_port = int(os.environ.get("FUSION_PORT", "8085"))
    uvicorn.run(app, host="0.0.0.0", port=_fusion_port)
