"""
API anahtarı biçimi, üretimi ve doğrulaması.

Biçim: dv_<tür>_<key_id>_<secret>
  tür     sk (secret, sunucudan sunucuya) | pk (publishable, tarayıcı; origin kısıtlı)
  key_id  8 karakter, küçük harf + rakam; Mongo'da arama anahtarı (gizli değil)
  secret  32 karakter; yalnızca HMAC-SHA256(API_KEY_PEPPER, secret) saklanır

Tam anahtar yalnızca oluşturulduğu anda bir kez gösterilir.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import string
from dataclasses import dataclass

KEY_TYPES = ("sk", "pk")
_ALPHABET = string.ascii_lowercase + string.digits
_SECRET_ALPHABET = string.ascii_letters + string.digits
_KEY_RE = re.compile(r"^dv_(sk|pk)_([a-z0-9]{8})_([A-Za-z0-9]{32})$")

# Geliştirme ortamında pepper yoksa sabit bir değer kullanılır; prod'da başlangıç kontrolü (security.py) bunu engeller.
_DEV_PEPPER = "dev-only-api-key-pepper-change-me"


def pepper() -> bytes:
    return (os.environ.get("API_KEY_PEPPER") or _DEV_PEPPER).encode("utf-8")


@dataclass(frozen=True)
class ParsedKey:
    type: str
    key_id: str
    secret: str


def generate(key_type: str) -> tuple[str, str, str]:
    """(tam_anahtar, key_id, secret_hash) döner."""
    if key_type not in KEY_TYPES:
        raise ValueError(f"key_type sk|pk olmalı: {key_type}")
    key_id = "".join(secrets.choice(_ALPHABET) for _ in range(8))
    secret = "".join(secrets.choice(_SECRET_ALPHABET) for _ in range(32))
    return f"dv_{key_type}_{key_id}_{secret}", key_id, hash_secret(secret)


def parse(raw: str | None) -> ParsedKey | None:
    if not raw:
        return None
    m = _KEY_RE.match(raw.strip())
    if not m:
        return None
    return ParsedKey(type=m.group(1), key_id=m.group(2), secret=m.group(3))


def hash_secret(secret: str) -> str:
    return hmac.new(pepper(), secret.encode("utf-8"), hashlib.sha256).hexdigest()


def verify(secret: str, secret_hash: str) -> bool:
    return hmac.compare_digest(hash_secret(secret), secret_hash or "")


def mask(key_type: str, key_id: str) -> str:
    """Listelemede gösterilecek kısaltılmış biçim."""
    return f"dv_{key_type}_{key_id}_…"


def extract_from_headers(headers) -> str | None:
    """`Authorization: Bearer dv_...` veya `X-API-Key: dv_...`."""
    auth = headers.get("authorization") or ""
    if auth.lower().startswith("bearer "):
        token = auth[7:].strip()
        if token.startswith("dv_"):
            return token
    xk = headers.get("x-api-key")
    return xk.strip() if xk else None
