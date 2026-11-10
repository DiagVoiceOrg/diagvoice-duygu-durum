"""OpenAPI tag tanımları (Swagger UI grupları)."""
from __future__ import annotations

from typing import Any

# Swagger/ReDoc'ta yalnızca dış istemcilere açık analiz uçları görünür.
# FE/iç uçlar (CMS auth, public, admin-*, wellness, "/") şemadan gizlidir: include_in_schema=False
# (fusion_service/app.py). Uçlar çalışmaya devam eder, sadece dokümantasyonda yer almaz.
OPENAPI_TAGS = [
    {
        "name": "analysis",
        "description": "Bileşik analiz: birden fazla model çıktısını tek istekte birleştirir.",
    },
    {
        "name": "proxy",
        "description": (
            "Tek model analiz uçları. Yanıt gövdesi ve HTTP kodu ilgili model servisiyle aynıdır; "
            "şema modele göre değişir."
        ),
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
