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


def _slim_emotion_probs(probs: list) -> list:
    out = []
    for x in (probs or [])[:4]:
        try:
            out.append(round(float(x), 3))
        except (TypeError, ValueError):
            out.append(x)
    return out


def _slim_unified_emotion(ue: dict[str, Any]) -> dict[str, Any]:
    slim = {k: v for k, v in ue.items() if k not in ("probs", "sources")}
    if isinstance(ue.get("probs"), list):
        slim["probs"] = _slim_emotion_probs(ue["probs"])
    sources = ue.get("sources")
    if isinstance(sources, dict):
        src_out: dict[str, Any] = {}
        for sk, sv in sources.items():
            if isinstance(sv, dict):
                row = {kk: sv[kk] for kk in sv if kk != "probs"}
                if isinstance(sv.get("probs"), list):
                    row["probs"] = _slim_emotion_probs(sv["probs"])
                src_out[sk] = row
            else:
                src_out[sk] = sv
        slim["sources"] = src_out
    return slim


def redact_fused_details(body: dict[str, Any]) -> dict[str, Any]:
    """STT metnini varsayılan olarak kısalt; AUDIT_LOG_INCLUDE_TRANSCRIPT=1 ile tam metin."""
    out: dict[str, Any] = {}
    for k, v in body.items():
        if k == "text" and isinstance(v, str) and not AUDIT_INCLUDE_TRANSCRIPT:
            t = v.strip()
            out["text_preview"] = (t[:200] + "…") if len(t) > 200 else t
            out["text_len"] = len(t)
            continue
        if k == "unified_emotion" and isinstance(v, dict):
            out[k] = _slim_unified_emotion(v)
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


def redact_wellness_details(details: dict[str, Any]) -> dict[str, Any]:
    """
    Wellness Companion audit — transcript / asistan metni / session varsayılan olarak kısaltılır.
    AUDIT_LOG_INCLUDE_TRANSCRIPT=1 ile transcript tam metin yazılabilir.
    """
    if not isinstance(details, dict):
        return {"route": "wellness-companion-chat", "_invalid_details": True}

    out: dict[str, Any] = {}
    for k, v in details.items():
        if k in ("transcript", "assistant_message", "message") and isinstance(v, str):
            t = v.strip()
            if k == "transcript" and not AUDIT_INCLUDE_TRANSCRIPT:
                out["transcript_preview"] = (t[:200] + "…") if len(t) > 200 else t
                out["transcript_len"] = len(t)
                continue
            if k in ("assistant_message", "message"):
                out["response_preview"] = (t[:200] + "…") if len(t) > 200 else t
                out["response_len"] = len(t)
                continue
        if k == "session_id" and isinstance(v, str) and v.strip():
            sid = v.strip()
            out["session_id_suffix"] = sid[-12:] if len(sid) > 12 else sid
            continue
        if k == "messages" and isinstance(v, list):
            out["messages_count"] = len(v)
            continue
        out[k] = v

    if _json_size(out) > AUDIT_MAX_JSON:
        return {
            "route": out.get("route", "wellness-companion-chat"),
            "_truncated": True,
            "top_keys": list(details.keys())[:30],
        }
    return out


AUDIT_ERROR_BODY_MAX = max(512, int(os.environ.get("AUDIT_LOG_ERROR_BODY_BYTES", "16384")))


def _clip_text(value: Any, limit: int = 2000) -> str:
    s = str(value).strip()
    return s if len(s) <= limit else s[: limit - 1] + "…"


def normalize_error_detail(detail: Any, *, limit: int = 2000) -> Any:
    if detail is None:
        return None
    if isinstance(detail, str):
        return _clip_text(detail, limit)
    if isinstance(detail, (dict, list)):
        try:
            raw = json.dumps(detail, default=str, ensure_ascii=False).encode("utf-8")
        except Exception:
            return _clip_text(detail, limit)
        if len(raw) <= limit:
            return detail
        return {"_truncated": True, "preview": raw[:limit].decode("utf-8", errors="replace")}
    return _clip_text(detail, limit)


def summarize_validation_errors(errors: list[Any]) -> str:
    if not errors:
        return "Request validation failed"
    first = errors[0]
    if not isinstance(first, dict):
        return _clip_text(first)
    loc = ".".join(str(x) for x in first.get("loc", ()))
    msg = first.get("msg", "Validation error")
    return f"{loc}: {msg}" if loc else str(msg)


def error_details_from_validation(errors: list[Any]) -> dict[str, Any]:
    clipped = errors[:20] if isinstance(errors, list) else []
    return {
        "error_type": "request_validation",
        "error_source": "fusion_handler",
        "error_summary": summarize_validation_errors(clipped),
        "validation_errors": clipped,
    }


def error_details_from_http_exception(status_code: int, detail: Any) -> dict[str, Any]:
    return {
        "error_type": "http_exception",
        "error_source": "fusion_handler",
        "http_status": status_code,
        "error_summary": _clip_text(detail if isinstance(detail, str) else json.dumps(detail, default=str)),
        "detail": normalize_error_detail(detail),
    }


def error_details_from_unhandled(exc: BaseException) -> dict[str, Any]:
    return {
        "error_type": type(exc).__name__,
        "error_source": "fusion_unhandled",
        "error_summary": _clip_text(exc),
        "error_message": _clip_text(exc, 800),
    }


def error_details_from_response_body(http_status: int, body: bytes) -> dict[str, Any]:
    """Middleware yedek: handler audit yazmadıysa HTTP yanıt gövdesinden özet çıkar."""
    out: dict[str, Any] = {
        "error_type": "http_error",
        "error_source": "response_body",
        "http_status": http_status,
    }
    if not body:
        out["error_summary"] = f"HTTP {http_status} (empty body)"
        return out

    clipped = body[:AUDIT_ERROR_BODY_MAX]
    text = clipped.decode("utf-8", errors="replace").strip()
    try:
        parsed = json.loads(text)
    except Exception:
        out["error_summary"] = _clip_text(text or f"HTTP {http_status}")
        if len(body) > AUDIT_ERROR_BODY_MAX:
            out["_body_truncated"] = True
        return out

    if isinstance(parsed, dict):
        if parsed.get("detail") is not None:
            out["detail"] = normalize_error_detail(parsed["detail"])
            out["error_summary"] = _clip_text(
                parsed["detail"] if isinstance(parsed["detail"], str) else out["detail"]
            )
        elif parsed.get("error") is not None:
            out["error_message"] = _clip_text(parsed["error"])
            out["error_summary"] = out["error_message"]
        else:
            out["response_body"] = normalize_error_detail(parsed)
            out["error_summary"] = _clip_text(parsed)
    else:
        out["error_summary"] = _clip_text(parsed)

    if len(body) > AUDIT_ERROR_BODY_MAX:
        out["_body_truncated"] = True
    return out


def merge_error_audit(existing: Any, error_info: dict[str, Any]) -> dict[str, Any]:
    if isinstance(existing, dict):
        return {**existing, **error_info}
    return dict(error_info)


def set_request_error_audit(request: Any, error_info: dict[str, Any]) -> None:
    """Exception handler / middleware — mevcut audit_details ile birleştir."""
    if request is None or not hasattr(request, "state"):
        return
    existing = getattr(request.state, "audit_details", None)
    request.state.audit_details = merge_error_audit(existing, error_info)


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
    audio_recording: Optional[dict[str, Any]] = None,
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
        if audio_recording:
            doc["audio_recording"] = audio_recording
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
    audio_recording: Optional[dict[str, Any]] = None,
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
            audio_recording=audio_recording,
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
