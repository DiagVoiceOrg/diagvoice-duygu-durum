"""
Fusion API OpenAPI şemaları (Swagger / ReDoc / openapi.json).
Proxy yanıtları upstream modele göre değişir; bu modeller yalnızca Fusion'un kendi sözleşmesini tanımlar.
"""
from __future__ import annotations

from typing import Any

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TextSentimentRequest(BaseModel):
    text: str = Field(..., min_length=1, description="Analiz edilecek metin (genelde STT çıktısı).")


class TranscriptMeaningRequest(BaseModel):
    text: str = Field(..., description="STT metni")
    language: str = Field(
        ...,
        description="UI/STT dili: turkish | english | arabic vb. (mental_fitness servisi ile uyumlu)",
    )


class TurkishPsychSignalsRequest(BaseModel):
    text: str = Field(..., min_length=1, description="Türkçe psikolojik sinyal sınıflandırması için metin.")


class FusedValenceOut(BaseModel):
    valence: float | None = Field(None, ge=0.0, le=1.0)
    label: str | None = Field(None, description="POSITIVE veya NEGATIVE")
    w_text: float | None = Field(None, description="Metin ağırlığı (0–1)")


class FusedConfidenceOut(BaseModel):
    text: float | None = None
    audio: float | None = None
    disagreement: float | None = None
    dynamic_fusion: bool | None = None


class AnalyzeFusedResponse(BaseModel):
    """POST /analyze-fused birleşik yanıt şeması. Alt model alanları servise göre değişebilir."""

    model_config = ConfigDict(extra="ignore")

    text: str | None = Field(None, description="Whisper STT metni")
    text_error: str | None = None
    audio: dict[str, Any] | None = Field(None, description="Ses emosyonu (probs, intensity, …)")
    audio_error: str | None = None
    disease: dict[str, Any] | None = Field(None, description="WURSS / hastalık servisi")
    disease_error: str | None = None
    mental_fitness: dict[str, Any] | None = None
    mental_fitness_error: str | None = None
    age_gender: dict[str, Any] | None = None
    age_gender_error: str | None = None
    depression: dict[str, Any] | None = None
    depression_error: str | None = None
    benchmark_v2: dict[str, Any] | None = None
    benchmark_v2_error: str | None = None
    text_sentiment: dict[str, Any] | None = None
    text_sentiment_error: str | None = None
    valence_text: float | None = Field(None, ge=0.0, le=1.0)
    valence_audio: float | None = Field(None, ge=0.0, le=1.0)
    confidence: FusedConfidenceOut | None = None
    fused: FusedValenceOut | None = None


class ToggAnalyzeResponse(BaseModel):
    """POST /togg-analyze: paralel ses emosyonu + WURSS."""

    model_config = ConfigDict(extra="ignore")

    audio: dict[str, Any] | None = None
    audio_error: str | None = None
    disease: dict[str, Any] | None = None
    disease_error: str | None = None


class OpenApiLinks(BaseModel):
    swagger_ui: str = Field("/docs", description="Swagger UI")
    redoc: str = Field("/redoc", description="ReDoc")
    openapi_json: str = Field("/openapi.json", description="OpenAPI 3 JSON şeması", alias="schema")

    model_config = ConfigDict(populate_by_name=True)


class WellnessChatMessage(BaseModel):
    role: Literal["user", "assistant"] = Field(..., description="user veya assistant")
    content: str = Field(..., description="UTF-8 sohbet metni")


class WellnessChatRequest(BaseModel):
    messages: list[WellnessChatMessage] = Field(..., min_length=1)
    locale: str | None = Field(None, description="İsteğe bağlı: tr | en")
    session_id: str | None = Field(None, description="İsteğe bağlı anonim oturum kimliği")

    @model_validator(mode="after")
    def _at_least_one_user_message(self) -> "WellnessChatRequest":
        if not any(m.role == "user" and m.content.strip() for m in self.messages):
            raise ValueError("En az bir anlamlı user mesajı gerekir.")
        return self


class WellnessChatResponse(BaseModel):
    message: str = Field(..., min_length=1, description="Kullanıcıya gösterilen asistan metni")
    transcript: str | None = Field(
        None,
        description="Ses modunda STT metni (kullanıcı balonu); metin modunda yok.",
    )


class WellnessChatErrorResponse(BaseModel):
    error: str = Field(..., min_length=1)


class ServiceInfoResponse(BaseModel):
    """GET / servis özeti."""

    message: str
    deps: dict[str, str | None]
    togg_analyze: str | None = None
    proxy: dict[str, str] | None = None
    fusion: dict[str, Any] | None = None
    openapi: OpenApiLinks | None = Field(
        default_factory=OpenApiLinks,
        description="Etkileşimli API dokümantasyonu (FastAPI otomatik üretir).",
    )
