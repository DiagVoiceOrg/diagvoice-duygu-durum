"""OpenAPI tag tanımları (Swagger UI grupları)."""
from __future__ import annotations

from typing import Any

OPENAPI_TAGS = [
    {
        "name": "meta",
        "description": "Servis bilgisi ve OpenAPI bağlantıları.",
    },
    {
        "name": "wellness",
        "description": "Wellness Companion landing sohbet widget (LLM + Türkçe psik sinyal tool).",
    },
    {
        "name": "analysis",
        "description": "Bileşik analiz: birden fazla model çıktısını tek istekte birleştirir.",
    },
    {
        "name": "proxy",
        "description": (
            "İç model servislerine aracı endpoint'ler. Yanıt gövdesi ve HTTP kodu upstream ile aynıdır; "
            "şema modele göre değişir."
        ),
    },
    {
        "name": "auth",
        "description": "CMS JWT kimlik doğrulama.",
    },
    {
        "name": "public",
        "description": "Yayınlanmış demo sayfaları ve UI profilleri (kimlik doğrulama gerekmez).",
    },
    {
        "name": "admin-pages",
        "description": "CMS demo sayfa yönetimi (admin JWT).",
    },
    {
        "name": "admin-profiles",
        "description": "CMS UI profil / kart yapılandırması (admin JWT).",
    },
    {
        "name": "admin-diagnostics",
        "description": "İç ML servis sağlık kontrolleri (admin JWT).",
    },
    {
        "name": "admin-usage",
        "description": "Fusion API kullanım logları (admin JWT).",
    },
]

PROXY_JSON_RESPONSES: dict[int | str, dict[str, Any]] = {
    200: {
        "description": "Upstream model servisi JSON gövdesi (alanlar modele göre değişir).",
        "content": {
            "application/json": {
                "schema": {"type": "object", "additionalProperties": True},
            }
        },
    },
    400: {"description": "Geçersiz istek veya zorunlu alan eksik"},
    503: {"description": "İlgili upstream servis devre dışı (ortam değişkeni boş)"},
}
