from bson import ObjectId


def oid_str(doc_id: ObjectId | str | None) -> str:
    if doc_id is None:
        return ""
    return str(doc_id)


def normalize_slug(slug: str) -> str:
    s = (slug or "").strip()
    if not s:
        return "/"
    if not s.startswith("/"):
        s = "/" + s
    return s.rstrip("/") or "/"
