"""Wellness Companion HTTP routes."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from fusion_service.schemas import WellnessChatErrorResponse, WellnessChatRequest, WellnessChatResponse
from fusion_service.wellness.service import WellnessChatError, handle_wellness_chat

router = APIRouter(tags=["wellness"])


def _client_ip(request: Request) -> str:
    from cms.usage_audit import client_ip_from_request

    return client_ip_from_request(request.scope.get("headers") or [])


@router.post(
    "/wellness/companion/chat",
    response_model=WellnessChatResponse,
    responses={
        400: {"model": WellnessChatErrorResponse},
        429: {"model": WellnessChatErrorResponse},
        502: {"model": WellnessChatErrorResponse},
        503: {"model": WellnessChatErrorResponse},
    },
    summary="Wellness Companion sohbet",
    description=(
        "Landing widget sohbet orchestrator: OpenAI + isteğe bağlı "
        "`analyze-turkish-psych-signals` tool. Yanıtta yalnızca doğal dil `message` döner."
    ),
)
async def wellness_companion_chat(request: Request, body: WellnessChatRequest):
    try:
        message, audit = await handle_wellness_chat(
            messages=[m.model_dump() for m in body.messages],
            client_ip=_client_ip(request),
        )
        request.state.audit_details = audit
        return WellnessChatResponse(message=message)
    except WellnessChatError as e:
        request.state.audit_details = {
            "route": "wellness-companion-chat",
            "error_status": e.status_code,
        }
        return JSONResponse(
            status_code=e.status_code,
            content=WellnessChatErrorResponse(error=e.message).model_dump(),
        )
