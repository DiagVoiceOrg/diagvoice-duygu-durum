"""Wellness Companion — LLM orchestration + Türkçe psik sinyal tool."""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

import httpx

from fusion_service.wellness.prompt import WELLNESS_SYSTEM_PROMPT
from fusion_service.wellness.rate_limit import check_rate_limit

_log = logging.getLogger("diagvoice.wellness")

MAX_MESSAGES = int(os.environ.get("WELLNESS_MAX_MESSAGES", "40"))
MAX_CONTENT_LEN = int(os.environ.get("WELLNESS_MAX_CONTENT_LEN", "4000"))
MAX_TOOL_ROUNDS = max(1, int(os.environ.get("WELLNESS_MAX_TOOL_ROUNDS", "3")))
LLM_TIMEOUT_SEC = float(os.environ.get("WELLNESS_LLM_TIMEOUT_SEC", "120"))
ANALYZE_TIMEOUT_SEC = float(os.environ.get("WELLNESS_ANALYZE_TIMEOUT_SEC", "60"))

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


def _resolve_analyze_url() -> str:
    for env_name in ("WELLNESS_ANALYZE_URL", "DIAGVOICE_ANALYZE_URL"):
        raw = os.environ.get(env_name, "").strip()
        if raw:
            return raw
    psych = os.environ.get("TURKISH_PSYCH_CLASSIFIER_URL", "").strip()
    if psych:
        return psych
    fusion_port = os.environ.get("FUSION_PORT", "8085")
    return f"http://127.0.0.1:{fusion_port}/analyze-turkish-psych-signals"


def _ipv4_loopback_url(url: str) -> str:
    if not url:
        return url
    return re.sub(r"(?i)//localhost(?=:|/)", "//127.0.0.1", url.strip())


def validate_messages(messages: list[dict[str, str]]) -> list[dict[str, str]]:
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
    if not has_user:
        raise WellnessChatError("En az bir anlamlı user mesajı gerekir.")
    return out


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


async def handle_wellness_chat(
    *,
    messages: list[dict[str, str]],
    client_ip: str,
    http_client: httpx.AsyncClient | None = None,
) -> tuple[str, dict[str, Any]]:
    """
    Returns (assistant_message, audit_details).
    """
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

    validated = validate_messages(messages)
    api_key, openai_base, model = _openai_config()
    analyze_url = _ipv4_loopback_url(_resolve_analyze_url())
    diagvoice_api_key = os.environ.get("DIAGVOICE_API_KEY", "").strip() or None

    openai_messages: list[dict[str, Any]] = [
        {"role": "system", "content": WELLNESS_SYSTEM_PROMPT},
        *validated,
    ]

    tool_called = False
    owns_client = http_client is None
    client = http_client or httpx.AsyncClient(
        timeout=httpx.Timeout(LLM_TIMEOUT_SEC, connect=30.0),
    )

    try:
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
                    "message_count": len(validated),
                    "tool_called": tool_called,
                    "tool_rounds": _round,
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
                        tool_result = await _call_analyze(
                            client, analyze_url, text, diagvoice_api_key
                        )
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
    finally:
        if owns_client:
            await client.aclose()
