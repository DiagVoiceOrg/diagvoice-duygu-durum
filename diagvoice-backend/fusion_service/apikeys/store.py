"""
Müşteri ve API anahtarı kayıtları.

Mongo koleksiyonları:
  clients      { _id, name, contact_email, status: active|disabled, notes, created_at }
  api_keys     { _id, key_id (unique), type, client_id, name, secret_hash, scopes, allowed_origins,
                 limits: {rpm, max_concurrent, monthly_quota}, status: active|revoked,
                 expires_at, last_used_at, created_by, created_at, revoked_at }
  usage_daily  { key_id, client_id, date (YYYY-MM-DD), route, count, errors }

Doğrulama yolunda anahtar 60 sn bellekte tutulur; iptal/rotate yerel önbelleği hemen temizler.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional, Protocol

from fusion_service.apikeys import keys as K
from fusion_service.apikeys import scopes as S

_log = logging.getLogger("diagvoice.apikeys")
CACHE_TTL_SEC = 60.0

DEFAULT_LIMITS = {"rpm": 120, "max_concurrent": 5, "monthly_quota": 0}  # 0 = sınırsız


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class ApiKey:
    key_id: str
    type: str
    client_id: str
    name: str
    secret_hash: str
    scopes: list[str]
    allowed_origins: list[str] = field(default_factory=list)
    limits: dict[str, int] = field(default_factory=lambda: dict(DEFAULT_LIMITS))
    status: str = "active"
    expires_at: Optional[datetime] = None
    last_used_at: Optional[datetime] = None
    created_by: str = ""
    created_at: datetime = field(default_factory=_now)
    revoked_at: Optional[datetime] = None
    client_name: str = ""
    client_status: str = "active"

    def limit(self, name: str) -> int:
        return int((self.limits or {}).get(name, DEFAULT_LIMITS[name]) or 0)

    def public(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("secret_hash", None)
        d["masked"] = K.mask(self.type, self.key_id)
        return d


class KeyStore(Protocol):
    async def get_key(self, key_id: str) -> Optional[ApiKey]: ...
    async def touch(self, key: ApiKey) -> None: ...
    async def record_usage(self, key: ApiKey, route: str, error: bool) -> None: ...
    async def monthly_count(self, key_id: str, month: str) -> int: ...
    # admin
    async def create_client(self, name: str, contact_email: str = "", notes: str = "") -> dict: ...
    async def list_clients(self) -> list[dict]: ...
    async def get_client(self, client_id: str) -> Optional[dict]: ...
    async def update_client(self, client_id: str, fields: dict) -> Optional[dict]: ...
    async def insert_key(self, key: ApiKey) -> None: ...
    async def list_keys(self, client_id: Optional[str] = None) -> list[ApiKey]: ...
    async def update_key(self, key_id: str, fields: dict) -> Optional[ApiKey]: ...
    async def usage(self, key_id: str, days: int = 30) -> list[dict]: ...


def new_key(*, key_type: str, client_id: str, name: str, scopes: list[str], allowed_origins: list[str] | None,
            limits: dict | None, expires_at: Optional[datetime], created_by: str) -> tuple[str, ApiKey]:
    raw, key_id, secret_hash = K.generate(key_type)
    lim = dict(DEFAULT_LIMITS)
    lim.update({k: int(v) for k, v in (limits or {}).items() if k in DEFAULT_LIMITS and v is not None})
    rec = ApiKey(
        key_id=key_id, type=key_type, client_id=client_id, name=name, secret_hash=secret_hash,
        scopes=S.validate(scopes), allowed_origins=list(allowed_origins or []), limits=lim,
        expires_at=expires_at, created_by=created_by,
    )
    return raw, rec


# --------------------------------------------------------------------------- Mongo
class MongoKeyStore:
    def __init__(self) -> None:
        self._cache: dict[str, tuple[float, Optional[ApiKey]]] = {}
        self._indexes_done = False

    @staticmethod
    def _db():
        from cms.database import get_db

        return get_db()

    async def ensure_indexes(self) -> None:
        if self._indexes_done:
            return
        db = self._db()
        await db.api_keys.create_index("key_id", unique=True)
        await db.api_keys.create_index("client_id")
        await db.usage_daily.create_index([("key_id", 1), ("date", 1), ("route", 1)], unique=True)
        await db.clients.create_index("name")
        self._indexes_done = True

    @staticmethod
    def _to_key(doc: dict, client: Optional[dict]) -> ApiKey:
        return ApiKey(
            key_id=doc["key_id"], type=doc["type"], client_id=str(doc["client_id"]), name=doc.get("name", ""),
            secret_hash=doc["secret_hash"], scopes=list(doc.get("scopes") or []),
            allowed_origins=list(doc.get("allowed_origins") or []), limits=dict(doc.get("limits") or DEFAULT_LIMITS),
            status=doc.get("status", "active"), expires_at=doc.get("expires_at"), last_used_at=doc.get("last_used_at"),
            created_by=doc.get("created_by", ""), created_at=doc.get("created_at") or _now(), revoked_at=doc.get("revoked_at"),
            client_name=(client or {}).get("name", ""), client_status=(client or {}).get("status", "active"),
        )

    async def _client_doc(self, client_id: str) -> Optional[dict]:
        from bson import ObjectId

        try:
            return await self._db().clients.find_one({"_id": ObjectId(client_id)})
        except Exception:
            return None

    async def get_key(self, key_id: str) -> Optional[ApiKey]:
        hit = self._cache.get(key_id)
        if hit and time.monotonic() - hit[0] < CACHE_TTL_SEC:
            return hit[1]
        doc = await self._db().api_keys.find_one({"key_id": key_id})
        rec = None
        if doc:
            rec = self._to_key(doc, await self._client_doc(str(doc["client_id"])))
        self._cache[key_id] = (time.monotonic(), rec)
        return rec

    def invalidate(self, key_id: Optional[str] = None) -> None:
        if key_id is None:
            self._cache.clear()
        else:
            self._cache.pop(key_id, None)

    async def touch(self, key: ApiKey) -> None:
        # En fazla dakikada bir yaz
        now = _now()
        if key.last_used_at and (now - key.last_used_at.replace(tzinfo=timezone.utc)).total_seconds() < 60:
            return
        key.last_used_at = now
        try:
            await self._db().api_keys.update_one({"key_id": key.key_id}, {"$set": {"last_used_at": now}})
        except Exception:
            _log.exception("api_keys last_used_at güncellenemedi key_id=%s", key.key_id)

    async def record_usage(self, key: ApiKey, route: str, error: bool) -> None:
        try:
            await self._db().usage_daily.update_one(
                {"key_id": key.key_id, "date": _now().strftime("%Y-%m-%d"), "route": route},
                {"$inc": {"count": 1, "errors": 1 if error else 0}, "$setOnInsert": {"client_id": key.client_id}},
                upsert=True,
            )
        except Exception:
            _log.exception("usage_daily yazılamadı key_id=%s", key.key_id)

    async def monthly_count(self, key_id: str, month: str) -> int:
        cur = self._db().usage_daily.aggregate([
            {"$match": {"key_id": key_id, "date": {"$regex": f"^{month}"}}},
            {"$group": {"_id": None, "n": {"$sum": "$count"}}},
        ])
        async for row in cur:
            return int(row.get("n", 0))
        return 0

    # --- admin ---
    @staticmethod
    def _client_out(doc: dict) -> dict:
        d = dict(doc)
        d["id"] = str(d.pop("_id"))
        return d

    async def create_client(self, name: str, contact_email: str = "", notes: str = "") -> dict:
        doc = {"name": name, "contact_email": contact_email, "notes": notes, "status": "active", "created_at": _now()}
        res = await self._db().clients.insert_one(doc)
        doc["_id"] = res.inserted_id
        return self._client_out(doc)

    async def list_clients(self) -> list[dict]:
        return [self._client_out(d) async for d in self._db().clients.find().sort("created_at", -1)]

    async def get_client(self, client_id: str) -> Optional[dict]:
        d = await self._client_doc(client_id)
        return self._client_out(d) if d else None

    async def update_client(self, client_id: str, fields: dict) -> Optional[dict]:
        doc = await self._client_doc(client_id)  # geçersiz id → None (404)
        if doc is None:
            return None
        await self._db().clients.update_one({"_id": doc["_id"]}, {"$set": fields})
        self.invalidate()  # müşteri durumu anahtar kayıtlarına gömülü
        return await self.get_client(client_id)

    async def insert_key(self, key: ApiKey) -> None:
        d = asdict(key)
        d.pop("client_name", None)
        d.pop("client_status", None)
        await self._db().api_keys.insert_one(d)
        self.invalidate(key.key_id)

    async def list_keys(self, client_id: Optional[str] = None) -> list[ApiKey]:
        q = {"client_id": client_id} if client_id else {}
        out = []
        clients: dict[str, Optional[dict]] = {}
        async for d in self._db().api_keys.find(q).sort("created_at", -1):
            cid = str(d["client_id"])
            if cid not in clients:
                clients[cid] = await self._client_doc(cid)
            out.append(self._to_key(d, clients[cid]))
        return out

    async def update_key(self, key_id: str, fields: dict) -> Optional[ApiKey]:
        await self._db().api_keys.update_one({"key_id": key_id}, {"$set": fields})
        self.invalidate(key_id)
        return await self.get_key(key_id)

    async def usage(self, key_id: str, days: int = 30) -> list[dict]:
        rows = []
        async for d in self._db().usage_daily.find({"key_id": key_id}).sort("date", -1).limit(days * 20):
            rows.append({"date": d["date"], "route": d["route"], "count": d.get("count", 0), "errors": d.get("errors", 0)})
        return rows


# --------------------------------------------------------------------------- bellek (testler)
class MemoryKeyStore:
    def __init__(self) -> None:
        self.clients: dict[str, dict] = {}
        self.keys: dict[str, ApiKey] = {}
        self.usage_rows: dict[tuple[str, str, str], dict] = {}
        self._n = 0
        self._lock = asyncio.Lock()

    def invalidate(self, key_id: Optional[str] = None) -> None:
        pass

    async def get_key(self, key_id: str) -> Optional[ApiKey]:
        k = self.keys.get(key_id)
        if k and k.client_id in self.clients:
            k.client_name = self.clients[k.client_id]["name"]
            k.client_status = self.clients[k.client_id]["status"]
        return k

    async def touch(self, key: ApiKey) -> None:
        key.last_used_at = _now()

    async def record_usage(self, key: ApiKey, route: str, error: bool) -> None:
        k = (key.key_id, _now().strftime("%Y-%m-%d"), route)
        row = self.usage_rows.setdefault(k, {"date": k[1], "route": route, "count": 0, "errors": 0})
        row["count"] += 1
        row["errors"] += 1 if error else 0

    async def monthly_count(self, key_id: str, month: str) -> int:
        return sum(r["count"] for (kid, d, _), r in self.usage_rows.items() if kid == key_id and d.startswith(month))

    async def create_client(self, name: str, contact_email: str = "", notes: str = "") -> dict:
        async with self._lock:
            self._n += 1
            cid = f"c{self._n:04d}"
        doc = {"id": cid, "name": name, "contact_email": contact_email, "notes": notes, "status": "active", "created_at": _now()}
        self.clients[cid] = doc
        return dict(doc)

    async def list_clients(self) -> list[dict]:
        return [dict(c) for c in self.clients.values()]

    async def get_client(self, client_id: str) -> Optional[dict]:
        c = self.clients.get(client_id)
        return dict(c) if c else None

    async def update_client(self, client_id: str, fields: dict) -> Optional[dict]:
        if client_id not in self.clients:
            return None
        self.clients[client_id].update(fields)
        return dict(self.clients[client_id])

    async def insert_key(self, key: ApiKey) -> None:
        self.keys[key.key_id] = key

    async def list_keys(self, client_id: Optional[str] = None) -> list[ApiKey]:
        return [k for k in self.keys.values() if client_id is None or k.client_id == client_id]

    async def update_key(self, key_id: str, fields: dict) -> Optional[ApiKey]:
        k = self.keys.get(key_id)
        if not k:
            return None
        for f, v in fields.items():
            setattr(k, f, v)
        return k

    async def usage(self, key_id: str, days: int = 30) -> list[dict]:
        return [dict(r) for (kid, _, _), r in self.usage_rows.items() if kid == key_id]


_store: Optional[KeyStore] = None


def get_store() -> KeyStore:
    global _store
    if _store is None:
        _store = MongoKeyStore()
    return _store


def set_store(store: KeyStore) -> None:
    """Testler için."""
    global _store
    _store = store
