"""Admin: müşteriler ve API anahtarları. Yalnızca admin JWT ile."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from cms.deps import require_admin
from fusion_service.apikeys import scopes as S
from fusion_service.apikeys.limiter import limiter
from fusion_service.apikeys.store import ApiKey, get_store, new_key

router = APIRouter(prefix="/admin", tags=["admin-api-keys"])
Admin = Annotated[dict, Depends(require_admin)]


class ClientIn(BaseModel):
    name: str = Field(..., min_length=2, max_length=120)
    contact_email: str = ""
    notes: str = ""


class ClientPatch(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=120)
    contact_email: Optional[str] = None
    notes: Optional[str] = None
    status: Optional[Literal["active", "disabled"]] = None


class Limits(BaseModel):
    rpm: Optional[int] = Field(None, ge=0, le=100_000, description="Dakikalık istek sınırı (0 = sınırsız)")
    max_concurrent: Optional[int] = Field(None, ge=0, le=1_000, description="Aynı anda en fazla istek (0 = sınırsız)")
    monthly_quota: Optional[int] = Field(None, ge=0, description="Aylık istek kotası (0 = sınırsız)")


class KeyIn(BaseModel):
    type: Literal["sk", "pk"] = "sk"
    name: str = Field(..., min_length=2, max_length=120, description="Örn. 'TOGG prod'")
    scopes: list[str] = Field(..., min_length=1, description="Örn. ['analyze:togg'] veya ['*']")
    allowed_origins: list[str] = Field(default_factory=list, description="Yalnızca pk: izinli tarayıcı origin'leri")
    limits: Limits = Field(default_factory=Limits)
    expires_at: Optional[datetime] = None


class KeyPatch(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=120)
    scopes: Optional[list[str]] = None
    allowed_origins: Optional[list[str]] = None
    limits: Optional[Limits] = None
    expires_at: Optional[datetime] = None


def _key_out(k: ApiKey) -> dict[str, Any]:
    d = k.public()
    d["active_requests"] = limiter.active(k.key_id)
    return d


@router.get("/scopes")
async def list_scopes(_: Admin) -> dict[str, Any]:
    return {"scopes": [{"scope": s, **m} for s, m in S.MODELS.items()] + [{"scope": S.ALL, "title": "Tüm analizler", "path": None}]}


@router.post("/clients", status_code=201)
async def create_client(body: ClientIn, _: Admin) -> dict:
    return await get_store().create_client(body.name.strip(), body.contact_email.strip(), body.notes)


@router.get("/clients")
async def list_clients(_: Admin) -> dict:
    return {"items": await get_store().list_clients()}


@router.patch("/clients/{client_id}")
async def patch_client(client_id: str, body: ClientPatch, _: Admin) -> dict:
    fields = body.model_dump(exclude_none=True)
    if not fields:
        raise HTTPException(400, "Değişecek alan yok")
    c = await get_store().update_client(client_id, fields)
    if not c:
        raise HTTPException(404, "Müşteri bulunamadı")
    return c


def _validate_key_body(key_type: str, scopes: list[str], origins: list[str]) -> list[str]:
    try:
        scopes = S.validate(scopes)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    if key_type == "pk" and not origins:
        raise HTTPException(400, "pk anahtarı için en az bir allowed_origins gerekli")
    return scopes


@router.post("/clients/{client_id}/keys", status_code=201)
async def create_key(client_id: str, body: KeyIn, admin: Admin) -> dict:
    store = get_store()
    client = await store.get_client(client_id)
    if not client:
        raise HTTPException(404, "Müşteri bulunamadı")
    scopes = _validate_key_body(body.type, body.scopes, body.allowed_origins)
    raw, rec = new_key(
        key_type=body.type, client_id=client_id, name=body.name.strip(), scopes=scopes,
        allowed_origins=body.allowed_origins, limits=body.limits.model_dump(), expires_at=body.expires_at,
        created_by=str(admin.get("sub", "")),
    )
    rec.client_name = client["name"]
    await store.insert_key(rec)
    return {"api_key": raw, "warning": "Bu anahtar yalnızca şimdi gösterilir; güvenli bir yerde saklayın.", "key": _key_out(rec)}


@router.get("/keys")
async def list_keys(_: Admin, client_id: Optional[str] = Query(None)) -> dict:
    return {"items": [_key_out(k) for k in await get_store().list_keys(client_id)]}


async def _get_or_404(key_id: str) -> ApiKey:
    k = await get_store().get_key(key_id)
    if not k:
        raise HTTPException(404, "Anahtar bulunamadı")
    return k


@router.patch("/keys/{key_id}")
async def patch_key(key_id: str, body: KeyPatch, _: Admin) -> dict:
    k = await _get_or_404(key_id)
    fields: dict[str, Any] = {}
    if body.name is not None:
        fields["name"] = body.name.strip()
    if body.scopes is not None or body.allowed_origins is not None:
        scopes = body.scopes if body.scopes is not None else k.scopes
        origins = body.allowed_origins if body.allowed_origins is not None else k.allowed_origins
        fields["scopes"] = _validate_key_body(k.type, scopes, origins)
        fields["allowed_origins"] = origins
    if body.limits is not None:
        lim = dict(k.limits)
        lim.update(body.limits.model_dump(exclude_none=True))
        fields["limits"] = lim
    if "expires_at" in body.model_fields_set:
        fields["expires_at"] = body.expires_at
    if not fields:
        raise HTTPException(400, "Değişecek alan yok")
    return _key_out(await get_store().update_key(key_id, fields))


@router.post("/keys/{key_id}/revoke")
async def revoke_key(key_id: str, _: Admin) -> dict:
    await _get_or_404(key_id)
    k = await get_store().update_key(key_id, {"status": "revoked", "revoked_at": datetime.now(timezone.utc)})
    return _key_out(k)


@router.post("/keys/{key_id}/rotate", status_code=201)
async def rotate_key(key_id: str, admin: Admin) -> dict:
    """Aynı ayarlarla yeni anahtar üretir, eskisini iptal eder."""
    old = await _get_or_404(key_id)
    if old.status != "active":
        raise HTTPException(400, "Yalnızca aktif anahtar yenilenebilir")
    store = get_store()
    raw, rec = new_key(
        key_type=old.type, client_id=old.client_id, name=old.name, scopes=old.scopes, allowed_origins=old.allowed_origins,
        limits=old.limits, expires_at=old.expires_at, created_by=str(admin.get("sub", "")),
    )
    rec.client_name = old.client_name
    await store.insert_key(rec)
    await store.update_key(key_id, {"status": "revoked", "revoked_at": datetime.now(timezone.utc)})
    return {"api_key": raw, "warning": "Bu anahtar yalnızca şimdi gösterilir; eski anahtar iptal edildi.",
            "key": _key_out(rec), "revoked_key_id": key_id}


@router.get("/keys/{key_id}/usage")
async def key_usage(key_id: str, _: Admin, days: int = Query(30, ge=1, le=366)) -> dict:
    k = await _get_or_404(key_id)
    rows = await get_store().usage(key_id, days)
    month = limiter.month()
    return {
        "key": _key_out(k),
        "month": month,
        "month_total": sum(r["count"] for r in rows if r["date"].startswith(month)),
        "daily": rows,
    }
