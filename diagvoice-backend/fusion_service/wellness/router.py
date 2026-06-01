"""Wellness Companion HTTP routes."""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from starlette.datastructures import UploadFile

from fusion_service.schemas import WellnessChatErrorResponse, WellnessChatRequest, WellnessChatResponse
from fusion_service.wellness.audit import merge_wellness_audit, set_wellness_audit, wellness_audit_base
from fusion_service.wellness.service import (
    WellnessChatError,
    handle_wellness_chat,
    handle_wellness_chat_voice,
    parse_messages_json,
)

router = APIRouter(tags=["wellness"])
_log = logging.getLogger("diagvoice.wellness")

_VOICE_FILE_KEYS = ("file", "audio", "recording")


def _is_voice_upload(candidate: object) -> bool:
    """Starlette form → starlette.datastructures.UploadFile (FastAPI sınıfıyla aynı değil)."""
    return isinstance(candidate, UploadFile) or (
        hasattr(candidate, "read")
        and hasattr(candidate, "filename")
        and callable(getattr(candidate, "read", None))
    )


def _voice_upload_from_form(form) -> UploadFile | None:
    for key in _VOICE_FILE_KEYS:
        candidate = form.get(key)
        if _is_voice_upload(candidate):
            return candidate  # type: ignore[return-value]
    return None


def _client_ip(request: Request) -> str:
    from cms.usage_audit import client_ip_from_request

    return client_ip_from_request(request.scope.get("headers") or [])


def _error_response(request: Request, e: WellnessChatError) -> JSONResponse:
    set_wellness_audit(
        request,
        merge_wellness_audit(
            request,
            {
                "route": "wellness-companion-chat",
                "error_status": e.status_code,
                "error_message": (e.message or "")[:300],
            },
        ),
    )
    return JSONResponse(
        status_code=e.status_code,
        content=WellnessChatErrorResponse(error=e.message).model_dump(),
    )


@router.post(
    "/wellness/companion/chat",
    response_model=WellnessChatResponse,
    responses={
        400: {"model": WellnessChatErrorResponse},
        413: {"model": WellnessChatErrorResponse},
        429: {"model": WellnessChatErrorResponse},
        502: {"model": WellnessChatErrorResponse},
        503: {"model": WellnessChatErrorResponse},
    },
    summary="Wellness Companion sohbet",
    description=(
        "Landing widget orchestrator (tek public endpoint). "
        "Mod A: `application/json` — metin sohbet + LLM + isteğe bağlı psych tool. "
        "Mod B: `multipart/form-data` — `file` (ses) + `messages` (JSON string) + opsiyonel `locale`; "
        "içeride STT + mental fitness + LLM; yanıt `{ message, transcript? }`. "
        "Kullanım `fusion_api_logs` (MongoDB) koleksiyonuna yazılır."
    ),
)
async def wellness_companion_chat(request: Request):
    try:
        content_type = (request.headers.get("content-type") or "").lower()

        if "multipart/form-data" in content_type:
            form = await request.form()
            upload = _voice_upload_from_form(form)
            if upload is None:
                form_keys = list(form.keys())
                _log.warning(
                    "wellness voice multipart missing file part keys=%s",
                    form_keys,
                )
                request.state.wellness_audit_base = wellness_audit_base(
                    mode="voice",
                    message_count=0,
                )
                raise WellnessChatError(
                    "Ses kaydı alanı (file) eksik veya geçersiz. "
                    "multipart isteğinde `file` ile ses dosyası gönderilmelidir."
                )

            raw_messages = form.get("messages")
            if raw_messages is None or not str(raw_messages).strip():
                raise WellnessChatError("messages alanı zorunludur.")

            locale = str(form.get("locale") or "tr").strip() or "tr"
            session_id = str(form.get("session_id") or "").strip() or None
            messages = parse_messages_json(str(raw_messages))

            audio_bytes = await upload.read()
            filename = upload.filename or "recording.webm"
            content_type_file = upload.content_type or "application/octet-stream"

            request.state.wellness_audit_base = wellness_audit_base(
                mode="voice",
                locale=locale,
                session_id=session_id,
                message_count=len(messages),
                audio_bytes=len(audio_bytes),
                upload_filename=filename,
            )

            message, transcript, audit = await handle_wellness_chat_voice(
                audio_bytes=audio_bytes,
                filename=filename,
                content_type=content_type_file,
                messages=messages,
                client_ip=_client_ip(request),
                locale=locale,
                session_id=session_id,
            )
            audit["transcript_len"] = len(transcript)
            set_wellness_audit(request, merge_wellness_audit(request, audit))
            return WellnessChatResponse(message=message, transcript=transcript)

        body_bytes = await request.body()
        payload = json.loads(body_bytes.decode("utf-8"))
        body = WellnessChatRequest.model_validate(payload)

        request.state.wellness_audit_base = wellness_audit_base(
            mode="text",
            locale=body.locale,
            session_id=body.session_id,
            message_count=len(body.messages),
        )

        message, audit = await handle_wellness_chat(
            messages=[m.model_dump() for m in body.messages],
            client_ip=_client_ip(request),
            locale=body.locale,
            session_id=body.session_id,
        )
        set_wellness_audit(request, merge_wellness_audit(request, audit))
        return WellnessChatResponse(message=message)

    except WellnessChatError as e:
        return _error_response(request, e)
    except json.JSONDecodeError:
        request.state.wellness_audit_base = wellness_audit_base(mode="text")
        return _error_response(request, WellnessChatError("Geçersiz JSON gövdesi."))
    except ValidationError as e:
        errs = e.errors()
        msg = errs[0].get("msg", "Geçersiz istek.") if errs else "Geçersiz istek."
        if not getattr(request.state, "wellness_audit_base", None):
            request.state.wellness_audit_base = wellness_audit_base(mode="text")
        return _error_response(request, WellnessChatError(str(msg)))
