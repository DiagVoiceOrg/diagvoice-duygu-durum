from typing import Annotated, Any

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, status

from cms.database import get_db
from cms.deps import require_admin
from cms.schemas import UiProfileCreate, UiProfileOut, UiProfileUpdate
from cms.serialize import oid_str

router = APIRouter(prefix="/admin/profiles", tags=["admin-profiles"])


def _out(doc: dict[str, Any]) -> UiProfileOut:
    return UiProfileOut(
        id=oid_str(doc["_id"]),
        key=doc["key"],
        label=doc.get("label", ""),
        cards=doc.get("cards") or [],
    )


@router.get("", response_model=list[UiProfileOut])
async def list_profiles(_: Annotated[dict, Depends(require_admin)]):
    db = get_db()
    cursor = db.ui_profiles.find({}).sort("key", 1)
    docs = await cursor.to_list(500)
    return [_out(d) for d in docs]


@router.post("", response_model=UiProfileOut)
async def create_profile(body: UiProfileCreate, _: Annotated[dict, Depends(require_admin)]):
    db = get_db()
    exists = await db.ui_profiles.find_one({"key": body.key})
    if exists:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Profile key exists")
    from datetime import UTC, datetime

    cards = [c.model_dump(by_alias=True, exclude_none=True) for c in body.cards]
    doc = {"key": body.key, "label": body.label, "cards": cards, "updatedAt": datetime.now(UTC)}
    res = await db.ui_profiles.insert_one(doc)
    doc["_id"] = res.inserted_id
    return _out(doc)


@router.get("/{profile_id}", response_model=UiProfileOut)
async def get_profile(profile_id: str, _: Annotated[dict, Depends(require_admin)]):
    db = get_db()
    try:
        oid = ObjectId(profile_id)
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid id")
    doc = await db.ui_profiles.find_one({"_id": oid})
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return _out(doc)


@router.put("/{profile_id}", response_model=UiProfileOut)
async def update_profile(
    profile_id: str,
    body: UiProfileUpdate,
    _: Annotated[dict, Depends(require_admin)],
):
    db = get_db()
    try:
        oid = ObjectId(profile_id)
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid id")
    doc = await db.ui_profiles.find_one({"_id": oid})
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    update: dict[str, Any] = {}
    if body.label is not None:
        update["label"] = body.label
    if body.cards is not None:
        update["cards"] = [c.model_dump(by_alias=True, exclude_none=True) for c in body.cards]
    if update:
        from datetime import UTC, datetime

        update["updatedAt"] = datetime.now(UTC)
        await db.ui_profiles.update_one({"_id": oid}, {"$set": update})
    doc = await db.ui_profiles.find_one({"_id": oid})
    return _out(doc)


@router.delete("/{profile_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_profile(profile_id: str, _: Annotated[dict, Depends(require_admin)]):
    db = get_db()
    try:
        oid = ObjectId(profile_id)
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid id")
    doc = await db.ui_profiles.find_one({"_id": oid})
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    key = doc["key"]
    in_use = await db.pages.count_documents({"profileKey": key})
    if in_use > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Profile is referenced by pages",
        )
    await db.ui_profiles.delete_one({"_id": oid})
