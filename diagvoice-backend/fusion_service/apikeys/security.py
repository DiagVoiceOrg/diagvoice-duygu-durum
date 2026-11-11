"""
Başlangıçta zayıf sır kontrolü.

DIAGVOICE_ENV=production iken (docker-compose varsayılanı) JWT_SECRET, CMS_ADMIN_PASSWORD veya
API_KEY_PEPPER eksik/zayıfsa uygulama BAŞLAMAZ. Yerel geliştirmede yalnızca uyarı verir.
"""
from __future__ import annotations

import logging
import os

_log = logging.getLogger("diagvoice.security")

_WEAK = {"", "admin123", "change-me-in-production", "dev-change-me", "changeme", "password", "secret"}


def is_production() -> bool:
    return os.environ.get("DIAGVOICE_ENV", "").strip().lower() in ("production", "prod")


def problems(cms_enabled: bool) -> list[str]:
    out: list[str] = []
    pepper = os.environ.get("API_KEY_PEPPER", "")
    if len(pepper) < 32 or pepper in _WEAK:
        out.append("API_KEY_PEPPER en az 32 karakter olmalı (ör. `openssl rand -hex 32`)")
    if cms_enabled:
        from cms.config import settings

        if len(settings.jwt_secret) < 32 or settings.jwt_secret in _WEAK:
            out.append("JWT_SECRET en az 32 karakter olmalı ve varsayılan değer olmamalı")
        if len(settings.cms_admin_password) < 12 or settings.cms_admin_password in _WEAK:
            out.append("CMS_ADMIN_PASSWORD en az 12 karakter olmalı ve varsayılan değer olmamalı")
    return out


def check_or_exit(cms_enabled: bool) -> None:
    found = problems(cms_enabled)
    if not found:
        return
    msg = "Zayıf/eksik sır: " + "; ".join(found)
    if is_production():
        _log.critical(msg + " — DIAGVOICE_ENV=production, uygulama başlatılmıyor.")
        raise SystemExit(msg)
    _log.warning(msg + " (geliştirme ortamı: devam ediliyor)")
