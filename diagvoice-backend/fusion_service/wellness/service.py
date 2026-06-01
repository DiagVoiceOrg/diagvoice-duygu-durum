"""Wellness Companion — LLM orchestration + Türkçe psik sinyal tool."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from typing import Any

import httpx

from fusion_service.wellness.prompt import WELLNESS_SYSTEM_PROMPT, WELLNESS_VOICE_CONTEXT_TEMPLATE
from fusion_service.wellness.rate_limit import check_rate_limit

_log = logging.getLogger("diagvoice.wellness")

MAX_MESSAGES = int(os.environ.get("WELLNESS_MAX_MESSAGES", "40"))
MAX_CONTENT_LEN = int(os.environ.get("WELLNESS_MAX_CONTENT_LEN", "4000"))
MAX_TOOL_ROUNDS = max(1, int(os.environ.get("WELLNESS_MAX_TOOL_ROUNDS", "3")))
LLM_TIMEOUT_SEC = float(os.environ.get("WELLNESS_LLM_TIMEOUT_SEC", "180"))
ANALYZE_TIMEOUT_SEC = float(os.environ.get("WELLNESS_ANALYZE_TIMEOUT_SEC", "120"))
VOICE_TIMEOUT_SEC = float(os.environ.get("WELLNESS_VOICE_TIMEOUT_SEC", "120"))
MAX_AUDIO_BYTES = int(os.environ.get("WELLNESS_MAX_AUDIO_BYTES", str(15 * 1024 * 1024)))

ANALYZE_TOOL = {
    "type": "function",
    "function": {
        "name": "analyzeTurkishPsychSignals",
        "description": (
            "Kullanıcının Türkçe mesajındaki duygusal içeriği analiz eder. "
            "Anlamlı duygusal paylaşım olduğunda çağır."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "Analiz edilecek kullanıcı mesajı",
                }
            },
            "required": ["text"],
        },
    },
}


class WellnessChatError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def _wellness_enabled() -> bool:
    return os.environ.get("WELLNESS_ENABLED", "1").strip().lower() not in ("0", "false", "no")


def _openai_config() -> tuple[str, str, str]:
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        raise WellnessChatError(
            "Wellness Companion şu an kullanılamıyor. Lütfen daha sonra tekrar deneyin.",
            status_code=503,
        )
    base = os.environ.get("OPENAI_API_BASE", "https://api.openai.com/v1").rstrip("/")
    model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini"
    return key, base, model


def _fusion_base_url() -> str:
    port = os.environ.get("FUSION_PORT", "8085")
    return f"http://127.0.0.1:{port}"


def _resolve_analyze_url() -> str:
    for env_name in ("WELLNESS_ANALYZE_URL", "DIAGVOICE_ANALYZE_URL"):
        raw = os.environ.get(env_name, "").strip()
        if raw:
            return raw
    psych = os.environ.get("TURKISH_PSYCH_CLASSIFIER_URL", "").strip()
    if psych:
        return psych
    return f"{_fusion_base_url()}/analyze-turkish-psych-signals"


def _resolve_mental_fitness_url() -> str:
    raw = os.environ.get("WELLNESS_MENTAL_FITNESS_URL", "").strip()
    if raw:
        return _ipv4_loopback_url(raw)
    return f"{_fusion_base_url()}/analyze-mental-fitness"


def _resolve_validate_transcript_url() -> str:
    raw = os.environ.get("WELLNESS_VALIDATE_TRANSCRIPT_URL", "").strip()
    if raw:
        return _ipv4_loopback_url(raw)
    return f"{_fusion_base_url()}/analyze-mental-fitness/validate-transcript-meaning"


def _resolve_stt_url() -> str:
    raw = os.environ.get("WELLNESS_STT_URL", "").strip()
    if raw:
        return _ipv4_loopback_url(raw)
    return _ipv4_loopback_url(
        os.environ.get("VOICE_TO_TEXT_URL", "http://127.0.0.1:8051/transcribe").strip()
    )


def _locale_to_stt_language(locale: str | None) -> str:
    if (locale or "").strip().lower() == "en":
        return "english"
    return "turkish"


def _locale_to_validation_language(locale: str | None) -> str:
    if (locale or "").strip().lower() == "en":
        return "english"
    return "turkish"


def _summarize_mental_fitness(mf: dict[str, Any]) -> str:
    parts: list[str] = []
    label = mf.get("pred_label")
    if label:
        parts.append(f"Olası sınıf sinyali: {label}")
    score = mf.get("mental_fitness_score")
    if score is not None:
        parts.append(f"Yorumlanabilir skor: {score}")
    probs = mf.get("probs")
    if isinstance(probs, list) and probs:
        parts.append(f"Olasılık dağılımı (iç): {probs}")
    return "; ".join(parts) if parts else "Ses tabanlı mental fitness analizi tamamlandı."


def _extract_transcript(stt_body: dict[str, Any]) -> str:
    for key in ("text", "transcript", "stt"):
        val = stt_body.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""


def _ipv4_loopback_url(url: str) -> str:
    if not url:
        return url
    return re.sub(r"(?i)//localhost(?=:|/)", "//127.0.0.1", url.strip())


def validate_messages(
    messages: list[dict[str, str]],
    *,
    require_user: bool = True,
) -> list[dict[str, str]]:
    if not messages:
        raise WellnessChatError("messages dizisi zorunludur.")
    if len(messages) > MAX_MESSAGES:
        raise WellnessChatError(f"En fazla {MAX_MESSAGES} mesaj gönderilebilir.")
    has_user = False
    out: list[dict[str, str]] = []
    for i, m in enumerate(messages):
        if not isinstance(m, dict):
            raise WellnessChatError(f"messages[{i}] geçersiz.")
        role = str(m.get("role", "")).strip().lower()
        if role not in ("user", "assistant"):
            raise WellnessChatError(f"messages[{i}].role yalnızca user veya assistant olabilir.")
        content = str(m.get("content", ""))
        if len(content) > MAX_CONTENT_LEN:
            raise WellnessChatError(f"Mesaj içeriği en fazla {MAX_CONTENT_LEN} karakter olabilir.")
        if role == "user" and content.strip():
            has_user = True
        out.append({"role": role, "content": content})
    if require_user and not has_user:
        raise WellnessChatError("En az bir anlamlı user mesajı gerekir.")
    return out


def parse_messages_json(raw: str) -> list[dict[str, str]]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise WellnessChatError("messages alanı geçerli JSON olmalıdır.") from e
    if not isinstance(data, list):
        raise WellnessChatError("messages bir dizi olmalıdır.")
    return [dict(m) for m in data]


async def _call_analyze(
    client: httpx.AsyncClient,
    url: str,
    text: str,
    api_key: str | None,
) -> dict[str, Any]:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    r = await client.post(
        url,
        json={"text": text},
        headers=headers,
        timeout=ANALYZE_TIMEOUT_SEC,
    )
    if r.status_code >= 500:
        raise WellnessChatError(
            "Duygu analizi servisi şu an yanıt vermiyor. Lütfen biraz sonra tekrar deneyin.",
            status_code=502,
        )
    if r.status_code >= 400:
        _log.warning("wellness analyze http=%s body=%s", r.status_code, r.text[:300])
        raise WellnessChatError(
            "Mesajınız şu an analiz edilemedi. Sohbete devam edebilirsiniz.",
            status_code=502,
        )
    try:
        body = r.json()
    except Exception as e:
        raise WellnessChatError(
            "Analiz servisinden geçersiz yanıt alındı.",
            status_code=502,
        ) from e
    if not isinstance(body, dict):
        raise WellnessChatError("Analiz servisinden geçersiz yanıt alındı.", status_code=502)
    return body


async def _openai_chat(
    client: httpx.AsyncClient,
    *,
    api_key: str,
    base_url: str,
    model: str,
    messages: list[dict[str, Any]],
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "tools": [ANALYZE_TOOL],
        "tool_choice": "auto",
        "temperature": 0.7,
    }
    r = await client.post(
        f"{base_url}/chat/completions",
        json=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        timeout=LLM_TIMEOUT_SEC,
    )
    if r.status_code == 429:
        raise WellnessChatError(
            "Çok fazla istek gönderildi. Lütfen bir dakika bekleyip tekrar deneyin.",
            status_code=429,
        )
    if r.status_code >= 500 or r.status_code in (401, 403):
        _log.error("wellness openai http=%s body=%s", r.status_code, r.text[:500])
        raise WellnessChatError(
            "Yapay zeka servisi şu an kullanılamıyor. Lütfen daha sonra tekrar deneyin.",
            status_code=503,
        )
    if r.status_code == 402:
        _log.warning("wellness openai http=402 body=%s", r.text[:500])
        raise WellnessChatError(
            "Yapay zeka servisi şu an kullanılamıyor (hesap bakiyesi). Lütfen daha sonra tekrar deneyin.",
            status_code=503,
        )
    if r.status_code >= 400:
        _log.warning("wellness openai http=%s body=%s", r.status_code, r.text[:500])
        raise WellnessChatError(
            "İsteğiniz işlenemedi. Lütfen mesajınızı kısaltıp tekrar deneyin.",
            status_code=400,
        )
    try:
        data = r.json()
        return data["choices"][0]["message"]
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as e:
        raise WellnessChatError(
            "Yapay zeka yanıtı beklenen formatta değil.",
            status_code=503,
        ) from e


async def _call_stt(
    client: httpx.AsyncClient,
    url: str,
    *,
    audio_bytes: bytes,
    filename: str,
    content_type: str,
    locale: str | None,
) -> dict[str, Any]:
    r = await client.post(
        url,
        files={"file": (filename, audio_bytes, content_type or "application/octet-stream")},
        data={"language": _locale_to_stt_language(locale)},
        timeout=VOICE_TIMEOUT_SEC,
    )
    if r.status_code >= 500:
        raise WellnessChatError(
            "Ses metne çevrilemedi. Lütfen biraz sonra tekrar deneyin.",
            status_code=502,
        )
    if r.status_code >= 400:
        _log.warning("wellness stt http=%s body=%s", r.status_code, r.text[:300])
        raise WellnessChatError(
            "Ses kaydı işlenemedi. Lütfen tekrar kayıt deneyin.",
            status_code=400,
        )
    try:
        body = r.json()
    except Exception as e:
        raise WellnessChatError("STT servisinden geçersiz yanıt alındı.", status_code=502) from e
    if not isinstance(body, dict):
        raise WellnessChatError("STT servisinden geçersiz yanıt alındı.", status_code=502)
    return body


async def _call_mental_fitness(
    client: httpx.AsyncClient,
    url: str,
    *,
    audio_bytes: bytes,
    filename: str,
    content_type: str,
    api_key: str | None,
) -> dict[str, Any]:
    headers: dict[str, str] = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    r = await client.post(
        url,
        files={"file": (filename, audio_bytes, content_type or "application/octet-stream")},
        headers=headers,
        timeout=ANALYZE_TIMEOUT_SEC,
    )
    if r.status_code >= 500:
        raise WellnessChatError(
            "Ses analizi servisi şu an yanıt vermiyor. Lütfen biraz sonra tekrar deneyin.",
            status_code=502,
        )
    if r.status_code >= 400:
        _log.warning("wellness mental_fitness http=%s body=%s", r.status_code, r.text[:300])
        raise WellnessChatError(
            "Ses kaydı analiz edilemedi. Lütfen tekrar deneyin.",
            status_code=502,
        )
    try:
        body = r.json()
    except Exception as e:
        raise WellnessChatError("Analiz servisinden geçersiz yanıt alındı.", status_code=502) from e
    if not isinstance(body, dict):
        raise WellnessChatError("Analiz servisinden geçersiz yanıt alındı.", status_code=502)
    return body


async def _call_validate_transcript(
    client: httpx.AsyncClient,
    url: str,
    *,
    text: str,
    locale: str | None,
    api_key: str | None,
) -> dict[str, Any]:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    r = await client.post(
        url,
        json={"text": text, "language": _locale_to_validation_language(locale)},
        headers=headers,
        timeout=ANALYZE_TIMEOUT_SEC,
    )
    if r.status_code >= 500:
        raise WellnessChatError(
            "Transkript doğrulaması şu an yapılamıyor. Lütfen biraz sonra tekrar deneyin.",
            status_code=502,
        )
    if r.status_code >= 400:
        _log.warning("wellness validate_transcript http=%s body=%s", r.status_code, r.text[:300])
        raise WellnessChatError(
            "Kayıt doğrulanamadı. Lütfen tekrar deneyin.",
            status_code=400,
        )
    try:
        body = r.json()
    except Exception as e:
        raise WellnessChatError("Doğrulama servisinden geçersiz yanıt alındı.", status_code=502) from e
    if not isinstance(body, dict):
        raise WellnessChatError("Doğrulama servisinden geçersiz yanıt alındı.", status_code=502)
    return body


async def _run_wellness_llm(
    client: httpx.AsyncClient,
    *,
    validated: list[dict[str, str]],
    api_key: str,
    openai_base: str,
    model: str,
    analyze_url: str,
    diagvoice_api_key: str | None,
    voice_context: str | None = None,
    route_mode: str = "text",
) -> tuple[str, dict[str, Any]]:
    system_content = WELLNESS_SYSTEM_PROMPT
    if voice_context:
        system_content = f"{WELLNESS_SYSTEM_PROMPT}\n\n{voice_context}"

    openai_messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_content},
        *validated,
    ]

    tool_called = False
    for _round in range(MAX_TOOL_ROUNDS + 1):
        msg = await _openai_chat(
            client,
            api_key=api_key,
            base_url=openai_base,
            model=model,
            messages=openai_messages,
        )

        tool_calls = msg.get("tool_calls") or []
        if not tool_calls:
            content = (msg.get("content") or "").strip()
            if not content:
                raise WellnessChatError(
                    "Şu an yanıt oluşturamıyorum. Lütfen tekrar deneyin.",
                    status_code=503,
                )
            audit = {
                "route": "wellness-companion-chat",
                "mode": route_mode,
                "message_count": len(validated),
                "tool_called": tool_called,
                "tool_rounds": _round,
                "response_len": len(content),
            }
            return content, audit

        openai_messages.append(msg)

        for tc in tool_calls:
            fn = (tc.get("function") or {})
            name = fn.get("name", "")
            if name != "analyzeTurkishPsychSignals":
                openai_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.get("id", ""),
                        "content": json.dumps({"error": f"Unknown tool: {name}"}, ensure_ascii=False),
                    }
                )
                continue
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            text = str(args.get("text", "")).strip()
            if not text:
                last_user = next(
                    (m["content"] for m in reversed(validated) if m["role"] == "user"),
                    "",
                )
                text = last_user.strip()
            if not text:
                tool_result = {"error": "Analiz için metin bulunamadı."}
            else:
                tool_called = True
                try:
                    tool_result = await _call_analyze(client, analyze_url, text, diagvoice_api_key)
                except WellnessChatError:
                    raise
                except httpx.HTTPError as e:
                    _log.exception("wellness analyze request failed")
                    raise WellnessChatError(
                        "Duygu analizi servisine ulaşılamadı. Lütfen daha sonra tekrar deneyin.",
                        status_code=502,
                    ) from e

            openai_messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.get("id", ""),
                    "content": json.dumps(tool_result, ensure_ascii=False),
                }
            )

    raise WellnessChatError(
        "Yanıt oluşturulurken zaman aşımı oluştu. Lütfen tekrar deneyin.",
        status_code=503,
    )


def _ensure_wellness_ready(client_ip: str) -> None:
    if not _wellness_enabled():
        raise WellnessChatError(
            "Wellness Companion geçici olarak kapalı.",
            status_code=503,
        )
    if not check_rate_limit(client_ip):
        raise WellnessChatError(
            "Çok fazla mesaj gönderdiniz. Lütfen kısa bir süre bekleyin.",
            status_code=429,
        )


async def handle_wellness_chat(
    *,
    messages: list[dict[str, str]],
    client_ip: str,
    locale: str | None = None,
    session_id: str | None = None,
    http_client: httpx.AsyncClient | None = None,
) -> tuple[str, dict[str, Any]]:
    """Metin modu — (assistant_message, audit_details)."""
    _ensure_wellness_ready(client_ip)
    validated = validate_messages(messages, require_user=True)
    api_key, openai_base, model = _openai_config()
    analyze_url = _ipv4_loopback_url(_resolve_analyze_url())
    diagvoice_api_key = os.environ.get("DIAGVOICE_API_KEY", "").strip() or None

    owns_client = http_client is None
    client = http_client or httpx.AsyncClient(
        timeout=httpx.Timeout(LLM_TIMEOUT_SEC, connect=30.0),
    )
    try:
        content, audit = await _run_wellness_llm(
            client,
            validated=validated,
            api_key=api_key,
            openai_base=openai_base,
            model=model,
            analyze_url=analyze_url,
            diagvoice_api_key=diagvoice_api_key,
            route_mode="text",
        )
        if locale:
            audit["locale"] = locale
        if session_id:
            audit["session_id"] = session_id
        return content, audit
    finally:
        if owns_client:
            await client.aclose()


async def handle_wellness_chat_voice(
    *,
    audio_bytes: bytes,
    filename: str,
    content_type: str,
    messages: list[dict[str, str]],
    client_ip: str,
    locale: str | None = None,
    session_id: str | None = None,
    http_client: httpx.AsyncClient | None = None,
) -> tuple[str, str, dict[str, Any]]:
    """Ses modu — (assistant_message, transcript, audit_details)."""
    if not audio_bytes:
        raise WellnessChatError("Ses dosyası zorunludur.")
    if len(audio_bytes) > MAX_AUDIO_BYTES:
        raise WellnessChatError(
            "Ses dosyası çok büyük. Lütfen daha kısa bir kayıt gönderin.",
            status_code=413,
        )

    _ensure_wellness_ready(client_ip)
    validated_history = validate_messages(messages, require_user=False)

    api_key, openai_base, model = _openai_config()
    analyze_url = _ipv4_loopback_url(_resolve_analyze_url())
    stt_url = _resolve_stt_url()
    mf_url = _resolve_mental_fitness_url()
    validate_url = _resolve_validate_transcript_url()
    diagvoice_api_key = os.environ.get("DIAGVOICE_API_KEY", "").strip() or None

    owns_client = http_client is None
    client = http_client or httpx.AsyncClient(
        timeout=httpx.Timeout(max(LLM_TIMEOUT_SEC, VOICE_TIMEOUT_SEC), connect=30.0),
    )
    try:
        stt_task = _call_stt(
            client,
            stt_url,
            audio_bytes=audio_bytes,
            filename=filename,
            content_type=content_type,
            locale=locale,
        )
        mf_task = _call_mental_fitness(
            client,
            mf_url,
            audio_bytes=audio_bytes,
            filename=filename,
            content_type=content_type,
            api_key=diagvoice_api_key,
        )
        stt_body, mf_body = await asyncio.gather(stt_task, mf_task)

        transcript = _extract_transcript(stt_body)
        if not transcript:
            raise WellnessChatError(
                "Kayıt net anlaşılamadı. Lütfen tekrar deneyin.",
                status_code=400,
            )

        val_body = await _call_validate_transcript(
            client,
            validate_url,
            text=transcript,
            locale=locale,
            api_key=diagvoice_api_key,
        )
        if val_body.get("meaningful") is False:
            raise WellnessChatError(
                "Kayıt net anlaşılamadı. Lütfen tekrar deneyin.",
                status_code=400,
            )

        mf_summary = _summarize_mental_fitness(mf_body)
        voice_context = WELLNESS_VOICE_CONTEXT_TEMPLATE.format(
            transcript=transcript,
            mental_fitness_summary=mf_summary,
        )

        validated_turn = [
            *validated_history,
            {"role": "user", "content": transcript},
        ]

        content, audit = await _run_wellness_llm(
            client,
            validated=validated_turn,
            api_key=api_key,
            openai_base=openai_base,
            model=model,
            analyze_url=analyze_url,
            diagvoice_api_key=diagvoice_api_key,
            voice_context=voice_context,
            route_mode="voice",
        )
        audit["transcript_len"] = len(transcript)
        if locale:
            audit["locale"] = locale
        if session_id:
            audit["session_id"] = session_id
        return content, transcript, audit
    finally:
        if owns_client:
            await client.aclose()
