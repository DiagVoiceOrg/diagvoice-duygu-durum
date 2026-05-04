from datetime import UTC, datetime, timedelta

import bcrypt
from jose import JWTError, jwt

from cms.config import settings

_BCRYPT_MAX_BYTES = 72


def normalize_password_for_bcrypt(plain: str) -> str:
    """bcrypt en fazla 72 bayt kabul eder; UTF-8 kesiminde yarım karakter bırakmamak için kısalt."""
    raw = plain.encode("utf-8")
    if len(raw) <= _BCRYPT_MAX_BYTES:
        return plain
    cut = raw[:_BCRYPT_MAX_BYTES]
    while cut and (cut[-1] & 0b1100_0000) == 0b1000_0000:
        cut = cut[:-1]
    return cut.decode("utf-8", errors="ignore")


def hash_password(password: str) -> str:
    """passlib + bcrypt 4.1+ uyumsuz; doğrudan bcrypt kullan (72 bayt sınırı normalize ile)."""
    raw = normalize_password_for_bcrypt(password).encode("utf-8")
    return bcrypt.hashpw(raw, bcrypt.gensalt()).decode("ascii")


def verify_password(plain: str, hashed: str) -> bool:
    raw = normalize_password_for_bcrypt(plain).encode("utf-8")
    try:
        digest = hashed.encode("ascii") if isinstance(hashed, str) else hashed
        return bcrypt.checkpw(raw, digest)
    except (ValueError, TypeError):
        return False


def create_access_token(sub: str, role: str) -> str:
    expire = datetime.now(UTC) + timedelta(hours=settings.jwt_expire_hours)
    payload = {"sub": sub, "role": role, "exp": expire}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except JWTError:
        return None
