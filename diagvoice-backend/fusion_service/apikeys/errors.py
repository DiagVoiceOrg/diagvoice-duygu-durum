"""Tutarlı hata gövdesi: {"error": {"code", "message", "request_id"}}.

Eski uçlarda geriye dönük uyum için ayrıca "detail" alanı eklenir.
"""
from __future__ import annotations

from typing import Optional

from fastapi import Request
from fastapi.responses import JSONResponse

# HTTP durumu → varsayılan kod (handler'lardan gelen HTTPException'lar için)
STATUS_CODES = {
    400: "invalid_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    413: "payload_too_large",
    422: "invalid_request",
    429: "rate_limited",
    500: "internal_error",
    502: "upstream_error",
    503: "service_unavailable",
    504: "upstream_timeout",
}


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, headers: Optional[dict] = None) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.headers = headers or {}


def request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "") or ""


def error_response(request: Request, status: int, code: str, message: str, *, legacy: bool = False,
                   headers: Optional[dict] = None, extra: Optional[dict] = None) -> JSONResponse:
    err = {"code": code, "message": message, "request_id": request_id(request)}
    if extra:
        err.update(extra)
    body: dict = {"error": err}
    if legacy:
        body["detail"] = message
    h = dict(headers or {})
    if err["request_id"]:
        h.setdefault("X-Request-ID", err["request_id"])
    return JSONResponse(status_code=status, content=body, headers=h)


def code_for_status(status: int) -> str:
    return STATUS_CODES.get(status, "error")
