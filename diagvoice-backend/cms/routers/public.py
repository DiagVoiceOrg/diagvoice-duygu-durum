from typing import Any

from fastapi import APIRouter, HTTPException, Query, status

from cms.database import get_db
from cms.schemas import PageOut, PageWithProfileOut, UiProfileOut
from cms.serialize import normalize_slug, oid_str

router = APIRouter(prefix="/public", tags=["public"])


def _profile_from_doc(doc: dict[str, Any] | None) -> UiProfileOut | None:
    if not doc:
        return None
    cards = doc.get("cards") or []
    return UiProfileOut(id=oid_str(doc["_id"]), key=doc["key"], label=doc.get("label", ""), cards=cards)


def _page_from_doc(doc: dict[str, Any]) -> PageOut:
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


@router.get("/pages", response_model=list[PageOut])
async def list_published_pages():
    db = get_db()
    cursor = db.pages.find({"published": True}).sort("sortOrder", 1)
    docs = await cursor.to_list(500)
    return [_page_from_doc(d) for d in docs]


@router.get("/pages/by-slug", response_model=PageWithProfileOut)
async def get_page_by_slug(slug: str = Query(..., description='Örn. "/" veya "/demo"')):
    db = get_db()
    norm = normalize_slug(slug)
    doc = await db.pages.find_one({"slug": norm, "published": True})
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Page not found")
    base = _page_from_doc(doc)
    prof_doc = await db.ui_profiles.find_one({"key": doc.get("profileKey")})
    prof = _profile_from_doc(prof_doc)
    return PageWithProfileOut(**base.model_dump(), profile=prof)


@router.get("/profiles/{key}", response_model=UiProfileOut)
async def get_profile_by_key(key: str):
    db = get_db()
    doc = await db.ui_profiles.find_one({"key": key})
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found")
    p = _profile_from_doc(doc)
    assert p is not None
    return p
