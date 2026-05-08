"""Admin: Fusion API kullanım logları (fusion_api_logs)."""

from __future__ import annotations

import json
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from cms.deps import require_admin
from cms.usage_audit import AUDIT_MAX_JSON, get_log_by_id, get_summary, list_logs

router = APIRouter(prefix="/admin/usage", tags=["admin-usage"])


def _clip_details_for_response(details: Any) -> Any:
    if details is None:
        return None
    try:
        raw = json.dumps(details, default=str, ensure_ascii=False).encode("utf-8")
    except Exception:
        return {"_clipped": True, "_reason": "details not serializable"}
    if len(raw) <= min(AUDIT_MAX_JSON, 200_000):
        return details
    return {"_clipped": True, "_reason": "details too large for this endpoint", "max_bytes": min(AUDIT_MAX_JSON, 200_000)}


@router.get("/summary")
async def usage_summary(
    _: Annotated[dict, Depends(require_admin)],
    from_: Optional[str] = Query(None, alias="from"),
    to: Optional[str] = Query(None, alias="to"),
) -> dict[str, Any]:
    return await get_summary(from_iso=from_, to_iso=to)


@router.get("/logs")
async def usage_logs(
    _: Annotated[dict, Depends(require_admin)],
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    path: Optional[str] = Query(None, description="Path öneki (regex ^prefix)"),
    min_status: Optional[int] = Query(None, ge=100, le=599, description="http_status >= min_status"),
    outcome: Optional[str] = Query(None, description="success | client_error | server_error"),
    from_: Optional[str] = Query(None, alias="from"),
    to: Optional[str] = Query(None, alias="to"),
) -> dict[str, Any]:
    rows, total = await list_logs(
        skip=skip,
        limit=limit,
        path_prefix=path,
        min_http_status=min_status,
        outcome=outcome,
        from_iso=from_,
        to_iso=to,
    )
    return {"items": rows, "total": total, "skip": skip, "limit": limit}


@router.get("/logs/{log_id}")
async def usage_log_detail(log_id: str, _: Annotated[dict, Depends(require_admin)]) -> dict[str, Any]:
    doc = await get_log_by_id(log_id)
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Log not found")
    doc["details"] = _clip_details_for_response(doc.get("details"))
    return doc
