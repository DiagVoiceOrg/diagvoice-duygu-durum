"""Wellness Companion → fusion_api_logs (MongoDB) audit yardımcıları."""

from __future__ import annotations

from typing import Any

from starlette.requests import Request

from cms.usage_audit import redact_wellness_details


def wellness_audit_base(
    *,
    mode: str,
    locale: str | None = None,
    session_id: str | None = None,
    message_count: int | None = None,
    audio_bytes: int | None = None,
    upload_filename: str | None = None,
) -> dict[str, Any]:
    base: dict[str, Any] = {
        "route": "wellness-companion-chat",
        "mode": mode,
    }
    if locale:
        base["locale"] = locale
    if session_id:
        base["session_id"] = session_id
    if message_count is not None:
        base["message_count"] = message_count
    if audio_bytes is not None:
        base["audio_bytes"] = audio_bytes
    if upload_filename:
        base["upload_filename"] = (upload_filename or "")[:120]
    return base


def set_wellness_audit(request: Request, details: dict[str, Any]) -> None:
    """Handler sonunda request.state.audit_details — middleware MongoDB'ye yazar."""
    request.state.audit_details = redact_wellness_details(details)


def merge_wellness_audit(request: Request, details: dict[str, Any]) -> dict[str, Any]:
    base = getattr(request.state, "wellness_audit_base", None)
    if isinstance(base, dict):
        merged = {**base, **details}
    else:
        merged = details
    return redact_wellness_details(merged)
