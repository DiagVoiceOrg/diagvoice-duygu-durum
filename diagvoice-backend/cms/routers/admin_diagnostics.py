"""
Admin-only: dahili çıkarım mikro servislerinin yüklendiğini / yanıt verdiğini özet kontrolü.
Tarayıcıdan doğrudan 805x portlarına erişim olmadığı için istekler sunucu içinde yapılır.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from datetime import datetime, timezone
from typing import Annotated, Any
from urllib.parse import urlparse, urlunparse

import httpx
from fastapi import APIRouter, Depends

from cms.deps import require_admin

log = logging.getLogger("cms.diagnostics")

router = APIRouter(prefix="/admin/diagnostics", tags=["admin-diagnostics"])


def _ipv4_loopback_url(url: str) -> str:
    """fusion_service ile aynı kural."""
    if not url or not isinstance(url, str):
        return url
    return re.sub(r"(?i)//localhost(?=:|/)", "//127.0.0.1", url.strip())


def _service_root(full_action_url: str) -> str:
    """http://127.0.0.1:8051/transcribe -> http://127.0.0.1:8051/"""
    u = urlparse(full_action_url.strip())
    root = urlunparse((u.scheme, u.netloc, "/", "", "", ""))
    return root


def _env_upstream_urls() -> dict[str, tuple[str, str]]:
    """
    key -> (servis_etiketi, kök_health_url_veya_health_path)
    URL'ler fusion_service ile uyumlu env varsayılanları kullanır.
    """
    vtt = _ipv4_loopback_url(os.environ.get("VOICE_TO_TEXT_URL", "http://127.0.0.1:8051/transcribe"))
    tts = _ipv4_loopback_url(os.environ.get("TEXT_TO_SENTIMENT_URL", "http://127.0.0.1:8050/analyze"))
    vsa = _ipv4_loopback_url(os.environ.get("VOICE_TO_SENTIMENT_URL", "http://127.0.0.1:8052/analyze-audio"))
    dis = _ipv4_loopback_url(os.environ.get("DISEASE_SERVICE_URL", "http://127.0.0.1:8054/analyze-disease"))
    mf = _ipv4_loopback_url(os.environ.get("MENTAL_FITNESS_URL", "http://127.0.0.1:8055/analyze-mental"))
    ag = _ipv4_loopback_url(os.environ.get("AGE_GENDER_URL", "http://127.0.0.1:8056/analyze-age-gender"))
    dep = _ipv4_loopback_url(os.environ.get("DEPRESSION_SERVICE_URL", "http://127.0.0.1:8057/analyze-depression"))

    inference_raw = os.environ.get("INFERENCE_API_URL")
    inference = ""
    if inference_raw is not None and str(inference_raw).strip():
        inference = _ipv4_loopback_url(str(inference_raw).strip().rstrip("/"))

    # HF Türkçe psik metin servisi (mental_fitness ses servisinden ayrı). Boş TURKISH_PSYCH_HEALTH_URL = tarama dışı.
    _tp_h_raw = os.environ.get("TURKISH_PSYCH_HEALTH_URL")
    if _tp_h_raw is not None and not str(_tp_h_raw).strip():
        turkish_psych_health = ""
    elif _tp_h_raw and str(_tp_h_raw).strip():
        turkish_psych_health = _ipv4_loopback_url(str(_tp_h_raw).strip())
    else:
        _tp_port = int(os.environ.get("TURKISH_PSYCH_CLASSIFIER_PORT", "8058"))
        turkish_psych_health = _ipv4_loopback_url(f"http://127.0.0.1:{_tp_port}/health")

    _ev2_h_raw = os.environ.get("EMOTION_V2_HEALTH_URL")
    if _ev2_h_raw is not None and not str(_ev2_h_raw).strip():
        emotion_v2_health = ""
    elif _ev2_h_raw and str(_ev2_h_raw).strip():
        emotion_v2_health = _ipv4_loopback_url(str(_ev2_h_raw).strip())
    else:
        _ev2_port = int(os.environ.get("EMOTION_V2_PORT", "8059"))
        emotion_v2_health = _ipv4_loopback_url(f"http://127.0.0.1:{_ev2_port}/health")

    return {
        "text_sentiment": ("Metin duygu analizi", _service_root(tts)),
        "voice_to_text": ("Ses → metin (STT)", _service_root(vtt)),
        "voice_sentiment": ("Ses duygu (emosyon)", _service_root(vsa)),
        "disease": ("Hastalık (sağlıklı/hasta)", _service_root(dis)),
        "mental_fitness": ("Mental fitness", _service_root(mf)),
        "age_gender": ("Yaş & cinsiyet", _service_root(ag)),
        "depression": ("Depresyon skoru", _service_root(dep)),
        "turkish_psych": ("Türkçe psik sinyal (HF metin)", turkish_psych_health),
        "emotion_v2": ("Emosyon v2 (multimodal stacking)", emotion_v2_health),
        "benchmark": ("İş sağlığı (benchmark)", f"{inference}/health" if inference else ""),
    }


def _connect_read_timeouts():
    ct = float(os.environ.get("DIAGNOSTICS_HEALTH_CONNECT_SEC", "4"))
    rt = float(os.environ.get("DIAGNOSTICS_HEALTH_READ_SEC", "12"))
    return httpx.Timeout(rt, connect=ct)


async def _probe_get(client: httpx.AsyncClient, service_id: str, label: str, url: str) -> dict[str, Any]:
    t0 = time.perf_counter()
    out: dict[str, Any] = {
        "id": service_id,
        "label": label,
        "probe_url": url,
        "skipped": False,
        "status": "fail",
        "http_status": None,
        "latency_ms": None,
        "detail": None,
        "preview": None,
    }
    if not url:
        out["skipped"] = True
        out["status"] = "skipped"
        out["detail"] = "Bu servis yapılandırmada kapalı."
        return out
    try:
        r = await client.get(url, follow_redirects=True)
        ms = round((time.perf_counter() - t0) * 1000, 2)
        out["http_status"] = r.status_code
        out["latency_ms"] = ms
        preview: Any = None
        ctype = r.headers.get("content-type") or ""
        if "application/json" in ctype:
            try:
                preview = r.json()
                if isinstance(preview, dict):
                    preview = {k: preview[k] for k in list(preview.keys())[:12]}
            except Exception:
                preview = r.text[:300]
        elif r.text:
            preview = r.text[:300]
        out["preview"] = preview

        ok = r.status_code < 400
        if service_id == "benchmark":
            # Flask /health: ok alanı mümkün
            ok = ok and isinstance(preview, dict) and preview.get("ok") is True
            if ok:
                out["status"] = "ok"
            else:
                err = preview.get("error") if isinstance(preview, dict) else None
                out["detail"] = err if err else (
                    "Model /health yanıtı başarısız (model dosyası veya bağımlılık kontrolü)."
                )
                out["status"] = "fail"
        elif service_id == "turkish_psych":
            # FastAPI GET /health: { ok, model_dir, weights_path }
            ok = ok and isinstance(preview, dict) and preview.get("ok") is True
            if ok:
                out["status"] = "ok"
            else:
                out["detail"] = (
                    "HF model / ağırlık yüklenemedi (weights_path veya bağımlılık). "
                    "TURKISH_PSYCH_WEIGHTS_PATH ve servis loglarını kontrol edin."
                )
                out["status"] = "fail"
        elif service_id == "emotion_v2":
            ok = ok and isinstance(preview, dict) and preview.get("ok") is True
            if ok:
                out["status"] = "ok"
            else:
                err = preview.get("error") if isinstance(preview, dict) else None
                out["detail"] = err if err else (
                    "Emosyon v2 model yüklenemedi. EMOTION_V2_MODEL_PATH ve servis loglarını kontrol edin."
                )
                out["status"] = "fail"
        else:
            if ok:
                out["status"] = "ok"
            else:
                out["detail"] = f"HTTP {r.status_code}"
                out["status"] = "fail" if r.status_code >= 500 else "warn"

        # benchmark / turkish_psych disinda body'de bilinen hata
        if preview and isinstance(preview, dict) and preview.get("error"):
            msg = str(preview.get("error"))[:480]
            if service_id not in ("benchmark", "turkish_psych", "emotion_v2") or preview.get("ok") is False:
                out["detail"] = msg
                if preview.get("ok") is False or r.status_code >= 400:
                    out["status"] = "fail"

        return out
    except httpx.TimeoutException as e:
        out["latency_ms"] = round((time.perf_counter() - t0) * 1000, 2)
        out["detail"] = f"Timeout: {e}"
        log.warning("diagnostics_fail id=%s url=%s err=timeout", service_id, url)
        return out
    except httpx.ConnectError as e:
        out["latency_ms"] = round((time.perf_counter() - t0) * 1000, 2)
        out["detail"] = f"Bağlanılamadı: {e}"
        log.warning("diagnostics_fail id=%s url=%s err=connect", service_id, url)
        return out
    except Exception as e:
        out["latency_ms"] = round((time.perf_counter() - t0) * 1000, 2)
        out["detail"] = str(e)[:500]
        log.warning("diagnostics_fail id=%s url=%s err=%s", service_id, url, e)
        return out


@router.get("/models-health")
async def models_health(_: Annotated[dict, Depends(require_admin)]) -> dict[str, Any]:
    """Dahili mikro servislerin GET kök veya /health ile canlılık kontrolü."""
    urls = _env_upstream_urls()
    timeout = _connect_read_timeouts()
    order = [
        "text_sentiment",
        "voice_to_text",
        "voice_sentiment",
        "disease",
        "mental_fitness",
        "age_gender",
        "depression",
        "turkish_psych",
        "emotion_v2",
        "benchmark",
    ]
    async with httpx.AsyncClient(timeout=timeout) as client:
        tasks = [
            _probe_get(client, sid, urls[sid][0], urls[sid][1])
            for sid in order
            if sid in urls
        ]
        services = await asyncio.gather(*tasks)

    summary = {"ok": 0, "warn": 0, "fail": 0, "skipped": 0}
    for s in services:
        st = s.get("status")
        if st == "ok":
            summary["ok"] += 1
        elif st == "warn":
            summary["warn"] += 1
        elif st == "skipped":
            summary["skipped"] += 1
        else:
            summary["fail"] += 1

    return {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "services": list(services),
        "summary": summary,
        "hint": (
            "Bu kontrol yalnızca servislerin HTTP yanıt verdiğini, benchmark için joblib yükünü ve "
            "Türkçe psik HF servisi için /health içindeki model yükünü doğrular; "
            "tam çıkarım doğruluğu için ses ile /analyze-fused denemesi gerekir."
        ),
    }
