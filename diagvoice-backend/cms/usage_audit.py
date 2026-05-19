"""
Fusion (8085) API kullanım logları — MongoDB fusion_api_logs.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional

from bson import ObjectId
from bson.errors import InvalidId

_log = logging.getLogger("diagvoice.usage_audit")

AUDIT_LOG_ENABLED = os.environ.get("AUDIT_LOG_ENABLED", "1").strip().lower() not in ("0", "false", "no")
AUDIT_MAX_JSON = max(1024, int(os.environ.get("AUDIT_LOG_MAX_JSON_BYTES", "65536")))
AUDIT_INCLUDE_TRANSCRIPT = os.environ.get("AUDIT_LOG_INCLUDE_TRANSCRIPT", "0").strip().lower() in (
    "1",
    "true",
    "yes",
)


def _skip_path(path: str) -> bool:
    raw = os.environ.get("AUDIT_LOG_SKIP_PREFIXES", "/admin,/public,/auth").strip()
    if not raw:
        return False
    for p in raw.split(","):
        p = p.strip()
        if p and path.startswith(p):
            return True
    return False


def outcome_from_status(http_status: int) -> str:
    if 200 <= http_status < 400:
        return "success"
    if 400 <= http_status < 500:
        return "client_error"
    return "server_error"


def client_ip_from_request(scope_headers: list[tuple[bytes, bytes]]) -> str:
    h = {k.decode("latin-1").lower(): v.decode("latin-1", errors="replace") for k, v in scope_headers}
    for key in ("x-forwarded-for", "x-real-ip"):
        if key in h:
            return h[key].split(",")[0].strip()[:200]
    return ""


def _json_size(obj: Any) -> int:
    try:
        return len(json.dumps(obj, default=str, ensure_ascii=False).encode("utf-8"))
    except Exception:
        return 0


def redact_fused_details(body: dict[str, Any]) -> dict[str, Any]:
    """STT metnini varsayılan olarak kısalt; AUDIT_LOG_INCLUDE_TRANSCRIPT=1 ile tam metin."""
    out: dict[str, Any] = {}
    for k, v in body.items():
        if k == "text" and isinstance(v, str) and not AUDIT_INCLUDE_TRANSCRIPT:
            t = v.strip()
            out["text_preview"] = (t[:200] + "…") if len(t) > 200 else t
            out["text_len"] = len(t)
            continue
        if isinstance(v, dict) and _json_size(v) > 12000:
            out[k] = {"_truncated": True, "keys": list(v.keys())[:50]}
        elif isinstance(v, list) and len(v) > 500:
            out[k] = {"_truncated": True, "len": len(v)}
        else:
            out[k] = v
    if _json_size(out) > AUDIT_MAX_JSON:
        return {"_truncated": True, "top_keys": list(body.keys())}
    return out


def truncate_proxy_json(body: Any, proxy_name: str) -> Any:
    if not isinstance(body, dict):
        return {"proxy": proxy_name, "raw_type": type(body).__name__}
    small = dict(body)
    if proxy_name == "analyze-turkish-psych-signals" and "predictions" in small:
        preds = small.get("predictions")
        top = small.get("top_prediction")
        return {
            "proxy": proxy_name,
            "top_prediction": top,
            "predictions_count": len(preds) if isinstance(preds, list) else None,
        }
    if _json_size(small) > AUDIT_MAX_JSON:
        return {"proxy": proxy_name, "keys": list(small.keys())[:30], "_truncated": True}
    return {"proxy": proxy_name, "body": small}


async def insert_fusion_audit(
    *,
    path: str,
    method: str,
    http_status: int,
    duration_ms: float,
    client_ip: str,
    details: Optional[dict[str, Any]] = None,
) -> None:
    if not AUDIT_LOG_ENABLED or _skip_path(path):
        return
    try:
        from cms.database import get_db

        doc: dict[str, Any] = {
            "created_at": datetime.now(timezone.utc),
            "path": path,
            "method": method,
            "http_status": http_status,
            "duration_ms": round(float(duration_ms), 2),
            "client_ip": (client_ip or "")[:200],
            "outcome": outcome_from_status(http_status),
            "details": details,
        }
        await get_db().fusion_api_logs.insert_one(doc)
    except Exception:
        _log.exception("fusion_api_logs insert failed path=%s", path)


def schedule_fusion_audit(
    *,
    path: str,
    method: str,
    http_status: int,
    duration_ms: float,
    client_ip: str,
    details: Optional[dict[str, Any]] = None,
) -> None:
    """Yanıtı bloklamamak için arka planda yaz."""
    if not AUDIT_LOG_ENABLED or _skip_path(path):
        return
    import asyncio

    asyncio.create_task(
        insert_fusion_audit(
            path=path,
            method=method,
            http_status=http_status,
            duration_ms=duration_ms,
            client_ip=client_ip,
            details=details,
        )
    )


async def list_logs(
    *,
    skip: int = 0,
    limit: int = 50,
    path_prefix: Optional[str] = None,
    outcome: Optional[str] = None,
    min_http_status: Optional[int] = None,
    from_iso: Optional[str] = None,
    to_iso: Optional[str] = None,
) -> tuple[list[dict[str, Any]], int]:
    from cms.database import get_db

    q: dict[str, Any] = {}
    if path_prefix:
        q["path"] = {"$regex": f"^{path_prefix}"}
    if outcome:
        q["outcome"] = outcome
    if min_http_status is not None:
        q["http_status"] = {"$gte": int(min_http_status)}
    if from_iso or to_iso:
        dr: dict[str, Any] = {}
        if from_iso:
            dr["$gte"] = datetime.fromisoformat(from_iso.replace("Z", "+00:00"))
        if to_iso:
            dr["$lte"] = datetime.fromisoformat(to_iso.replace("Z", "+00:00"))
        q["created_at"] = dr

    coll = get_db().fusion_api_logs
    total = await coll.count_documents(q)
    cursor = coll.find(q).sort("created_at", -1).skip(max(0, skip)).limit(min(200, max(1, limit)))
    rows = []
    async for doc in cursor:
        doc["id"] = str(doc.pop("_id"))
        if doc.get("created_at"):
            doc["created_at"] = doc["created_at"].isoformat()
        rows.append(doc)
    return rows, total


async def get_log_by_id(log_id: str) -> Optional[dict[str, Any]]:
    from cms.database import get_db

    try:
        oid = ObjectId(log_id)
    except InvalidId:
        return None
    doc = await get_db().fusion_api_logs.find_one({"_id": oid})
    if not doc:
        return None
    doc["id"] = str(doc.pop("_id"))
    if doc.get("created_at"):
        doc["created_at"] = doc["created_at"].isoformat()
    return doc


async def get_summary(*, from_iso: Optional[str] = None, to_iso: Optional[str] = None) -> dict[str, Any]:
    from cms.database import get_db

    match: dict[str, Any] = {}
    if from_iso or to_iso:
        dr: dict[str, Any] = {}
        if from_iso:
            dr["$gte"] = datetime.fromisoformat(from_iso.replace("Z", "+00:00"))
        if to_iso:
            dr["$lte"] = datetime.fromisoformat(to_iso.replace("Z", "+00:00"))
        match["created_at"] = dr

    coll = get_db().fusion_api_logs
    pipeline = []
    if match:
        pipeline.append({"$match": match})
    pipeline.extend(
        [
            {
                "$facet": {
                    "total": [{"$count": "c"}],
                    "by_outcome": [{"$group": {"_id": "$outcome", "count": {"$sum": 1}}}],
                    "by_path": [
                        {"$group": {"_id": "$path", "count": {"$sum": 1}}},
                        {"$sort": {"count": -1}},
                        {"$limit": 15},
                    ],
                }
            }
        ]
    )
    agg = await coll.aggregate(pipeline).to_list(1)
    facet = agg[0] if agg else {}
    total_list = facet.get("total") or []
    total = int(total_list[0]["c"]) if total_list else 0
    by_outcome = {x["_id"]: x["count"] for x in facet.get("by_outcome", []) if x.get("_id")}
    by_path = [{"path": x["_id"], "count": x["count"]} for x in facet.get("by_path", []) if x.get("_id")]
    return {
        "total": total,
        "by_outcome": by_outcome,
        "by_path": by_path,
    }
