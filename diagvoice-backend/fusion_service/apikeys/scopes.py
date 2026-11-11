"""
Scope kataloğu ve yol → scope eşlemesi.

Scope'lar API anahtarına verilir. "*" tüm analizlere izin verir.
F2'de model listesi registry.yaml'dan gelecek; şimdilik sabit.
"""
from __future__ import annotations

# scope → (açıklama, /v1 yolu)
MODELS: dict[str, dict[str, str]] = {
    "analyze:togg": {"title": "TOGG profili: ses emosyonu + WURSS", "path": "/v1/analyze/togg"},
    "analyze:fused": {"title": "Tam analiz: STT + tüm modeller", "path": "/v1/analyze/fused"},
    "model:stt": {"title": "Konuşma tanıma (Whisper)", "path": "/v1/analyze/stt"},
    "model:emotion_audio": {"title": "Ses emosyonu (WavLM)", "path": "/v1/analyze/emotion_audio"},
    "model:disease_wurss": {"title": "WURSS sağlık sinyali (Wav2Vec2)", "path": "/v1/analyze/disease_wurss"},
    "model:depression": {"title": "Depresyon", "path": "/v1/analyze/depression"},
    "model:age_gender": {"title": "Yaş ve cinsiyet", "path": "/v1/analyze/age_gender"},
    "model:mental_fitness": {"title": "Mental fitness", "path": "/v1/analyze/mental_fitness"},
    "model:emotion_v2": {"title": "Çok kipli emosyon v2", "path": "/v1/analyze/emotion_v2"},
    "model:occupational_health": {"title": "İş sağlığı (benchmark v2)", "path": "/v1/analyze/occupational_health"},
    "model:text_sentiment": {"title": "Metin duygu analizi", "path": "/v1/analyze/text_sentiment"},
    "model:turkish_psych": {"title": "Türkçe psikolojik sinyaller", "path": "/v1/analyze/turkish_psych"},
    "model:text_audio_fusion": {"title": "Metin + ses füzyonu", "path": None},
}

ALL = "*"

# registry.yaml'da `v1:` bloğu olan modeller: /v1/analyze/<id> ucu ve model:<id> scope'u otomatik açılır.
# (Yukarıdaki sabit liste mevcut, elle yazılmış uçlar içindir.)
REGISTRY_V1: dict[str, dict] = {}


def _load_registry_models() -> None:
    try:
        from dv_worker import registry as _R

        reg = _R.load()
    except Exception:  # registry okunamazsa yalnızca sabit uçlar açık kalır
        return
    for m in reg.models.values():
        if not m.v1 or not m.enabled:
            continue
        scope = f"model:{m.id}"
        if scope in MODELS:
            continue
        path = f"/v1/analyze/{m.id}"
        MODELS[scope] = {"title": m.title, "path": path}
        REGISTRY_V1[m.id] = {
            "group": m.group,
            "endpoint": str(m.v1.get("endpoint", "/analyze")),
            "input": str(m.v1.get("input", "audio")),
            "title": m.title,
        }


_load_registry_models()

# Eski (sürümsüz) uçlar → scope. Bu yollarda anahtar F1 geçiş döneminde isteğe bağlıdır (API_KEY_LEGACY_MODE).
LEGACY_PATHS: dict[str, str] = {
    "/togg-analyze": "analyze:togg",
    "/analyze-fused": "analyze:fused",
    "/analyze-voice-to-text": "model:stt",
    "/analyze-text-sentiment": "model:text_sentiment",
    "/analyze-emotion-fusion": "model:text_sentiment",
    "/analyze-voice-sentiment": "model:emotion_audio",
    "/analyze-emotion-v2": "model:emotion_v2",
    "/analyze-disease": "model:disease_wurss",
    "/analyze-mental-fitness": "model:mental_fitness",
    "/analyze-mental-fitness/validate-transcript-meaning": "model:mental_fitness",
    "/analyze-age-gender": "model:age_gender",
    "/analyze-text-audio-fusion": "model:text_audio_fusion",
    "/analyze-benchmark-v2": "model:occupational_health",
    "/analyze-turkish-psych-signals": "model:turkish_psych",
    "/analyze-depression": "model:depression",
}

# /v1 yolları → scope (GET /v1/models ve /v1/me yalnızca geçerli anahtar ister, scope istemez)
V1_PATHS: dict[str, str] = {m["path"]: s for s, m in MODELS.items() if m["path"]}


def scope_for_path(path: str) -> tuple[str | None, bool]:
    """(gerekli_scope, v1_mi). Korunmayan yol için (None, False)."""
    if path.startswith("/v1/"):
        return V1_PATHS.get(path), True
    return LEGACY_PATHS.get(path), False


def allowed(key_scopes: list[str], scope: str | None) -> bool:
    if scope is None:
        return True
    return ALL in key_scopes or scope in key_scopes


def visible_models(key_scopes: list[str]) -> list[dict]:
    out = []
    for s, m in MODELS.items():
        if m["path"] and allowed(key_scopes, s):
            out.append({"id": s.split(":", 1)[1], "scope": s, "title": m["title"], "path": m["path"]})
    return out


def validate(scopes: list[str]) -> list[str]:
    bad = [s for s in scopes if s != ALL and s not in MODELS]
    if bad:
        raise ValueError(f"Bilinmeyen scope: {', '.join(bad)}")
    return sorted(set(scopes))
