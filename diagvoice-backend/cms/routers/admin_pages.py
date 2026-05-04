from typing import Annotated, Any

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, status

from cms.database import get_db
from cms.deps import require_admin
from cms.schemas import PageCreate, PageOut, PageUpdate
from cms.serialize import normalize_slug, oid_str

router = APIRouter(prefix="/admin/pages", tags=["admin-pages"])


def _out(doc: dict[str, Any]) -> PageOut:
    return PageOut(
        id=oid_str(doc["_id"]),
        slug=doc["slug"],
        title=doc["title"],
        description=doc.get("description"),
        published=bool(doc.get("published")),
        sortOrder=int(doc.get("sortOrder", 0)),
        profileKey=doc.get("profileKey", ""),
        layout=doc.get("layout", "demo_default"),
        updatedAt=doc.get("updatedAt"),
    )


@router.get("", response_model=list[PageOut])
async def list_pages(_: Annotated[dict, Depends(require_admin)]):
    db = get_db()
    cursor = db.pages.find({}).sort("sortOrder", 1)
    docs = await cursor.to_list(500)
    return [_out(d) for d in docs]


@router.post("", response_model=PageOut)
async def create_page(body: PageCreate, _: Annotated[dict, Depends(require_admin)]):
    db = get_db()
    slug = normalize_slug(body.slug)
    exists = await db.pages.find_one({"slug": slug})
    if exists:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Slug exists")
    prof = await db.ui_profiles.find_one({"key": body.profileKey})
    if not prof:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown profileKey")
    from datetime import UTC, datetime

    doc = {
        "slug": slug,
        "title": body.title,
        "description": body.description,
        "published": body.published,
        "sortOrder": body.sortOrder,
        "profileKey": body.profileKey,
        "layout": body.layout,
        "updatedAt": datetime.now(UTC),
    }
    res = await db.pages.insert_one(doc)
    doc["_id"] = res.inserted_id
    return _out(doc)


@router.get("/{page_id}", response_model=PageOut)
async def get_page(page_id: str, _: Annotated[dict, Depends(require_admin)]):
    db = get_db()
    try:
        oid = ObjectId(page_id)
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid id")
    doc = await db.pages.find_one({"_id": oid})
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return _out(doc)


@router.put("/{page_id}", response_model=PageOut)
async def update_page(
    page_id: str,
    body: PageUpdate,
    _: Annotated[dict, Depends(require_admin)],
):
    db = get_db()
    try:
        oid = ObjectId(page_id)
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid id")
    doc = await db.pages.find_one({"_id": oid})
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    update: dict[str, Any] = {}
    if body.title is not None:
        update["title"] = body.title
    if body.description is not None:
        update["description"] = body.description
    if body.published is not None:
        update["published"] = body.published
    if body.sortOrder is not None:
        update["sortOrder"] = body.sortOrder
    if body.profileKey is not None:
        prof = await db.ui_profiles.find_one({"key": body.profileKey})
        if not prof:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown profileKey")
        update["profileKey"] = body.profileKey
    if body.layout is not None:
        update["layout"] = body.layout

    if update:
        from datetime import UTC, datetime

        update["updatedAt"] = datetime.now(UTC)
        await db.pages.update_one({"_id": oid}, {"$set": update})
    doc = await db.pages.find_one({"_id": oid})
    return _out(doc)


@router.delete("/{page_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_page(page_id: str, _: Annotated[dict, Depends(require_admin)]):
    db = get_db()
    try:
        oid = ObjectId(page_id)
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid id")
    res = await db.pages.delete_one({"_id": oid})
    if res.deleted_count == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
