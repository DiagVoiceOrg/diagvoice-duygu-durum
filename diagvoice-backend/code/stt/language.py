from __future__ import annotations

from typing import Optional

# Fusion / UI kodları
SPEECH_LANGUAGE_CODES = frozenset({"tr", "en", "ar", "auto"})

# voice_to_text Form alanına giden Whisper dil adları (+ auto → otomatik tespit için boş)
WHISPER_LANGUAGE_NAMES = frozenset({"turkish", "english", "arabic"})


def normalize_speech_language_code(raw: Optional[str], *, default: str = "tr") -> str:
    """UI / Fusion kodu: tr | en | ar | auto."""
    s = (raw or default).strip().lower()
    if s in SPEECH_LANGUAGE_CODES:
        return s
    alias = {
        "turkish": "tr",
        "türkçe": "tr",
        "turkce": "tr",
        "english": "en",
        "ingilizce": "en",
        "arabic": "ar",
        "arab": "ar",
        "عربي": "ar",
        "العربية": "ar",
        "detect": "auto",
        "automatic": "auto",
    }
    return alias.get(s, default)


def resolve_whisper_language(language: Optional[str]) -> Optional[str]:
    """
    UI/Fusion/STT kodunu Whisper dil adına çevirir.
    Boş, auto, detect → None (otomatik tespit).
    """
    if language is None or not str(language).strip():
        return None

    key = str(language).strip().lower()
    if key in {"auto", "detect", "automatic"}:
        return None

    code = normalize_speech_language_code(key, default="")
    if code == "auto":
        return None
    if code in {"tr", "en", "ar"}:
        return speech_language_to_form_value(code)

    mapping = {
        "turkish": "turkish",
        "türkçe": "turkish",
        "turkce": "turkish",
        "english": "english",
        "ingilizce": "english",
        "arabic": "arabic",
        "arab": "arabic",
        "عربي": "arabic",
        "العربية": "arabic",
    }
    if key in mapping:
        return mapping[key]

    return "turkish"


def speech_language_to_form_value(raw: Optional[str]) -> str:
    """Fusion → voice_to_text `language` form alanı (Whisper adları). auto → auto."""
    code = normalize_speech_language_code(raw)
    if code == "auto":
        return "auto"
    return {"tr": "turkish", "en": "english", "ar": "arabic"}.get(code, "turkish")
