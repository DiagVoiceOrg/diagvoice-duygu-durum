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


class EmotionFusionTextInput(BaseModel):
    sentiment: str | None = Field(None, description="POSITIVE/Negative/Notr vb.")
    label: str | None = Field(None, description="Alternatif etiket alanı")
    score: float = Field(..., ge=0.0, le=1.0)


class EmotionFusionAudioInput(BaseModel):
    probs: list[float] = Field(..., min_length=4, max_length=4)
    intensity: float | None = Field(None, ge=0.0, le=1.0)
    pred_label: str | None = None
    pred_id: int | None = None


class EmotionFusionRequest(BaseModel):
    text_sentiment: EmotionFusionTextInput | None = None
    audio: EmotionFusionAudioInput | None = None

    @model_validator(mode="after")
    def _at_least_one_modality(self) -> "EmotionFusionRequest":
        if self.text_sentiment is None and self.audio is None:
            raise ValueError("text_sentiment veya audio gerekli.")
        return self


class EmotionFusionResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    unified_emotion: dict[str, Any] | None = None
    valence_text: float | None = Field(None, ge=0.0, le=1.0)
    valence_audio: float | None = Field(None, ge=0.0, le=1.0)
    confidence: FusedConfidenceOut | None = None
    fused: FusedValenceOut | None = None


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
    unified_emotion: dict[str, Any] | None = Field(
        None,
        description="Metin+ses 4-sınıf birleşik emosyon (sadness/fear/happiness/anger)",
    )


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


class WellnessBrand(BaseModel):
    """Marka bilgisi. Gönderilen alan varsayılanı (DiagVoice) ezer."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(None, min_length=1, max_length=80, description="Marka/ürün adı (ör. TOGG)")
    description: str | None = Field(None, max_length=2000, description="Markanın kısa tanıtımı")
    creator: str | None = Field(None, min_length=1, max_length=120,
                                description="'Seni kim tasarladı?' sorusunun cevabı (varsayılan: marka adı)")
    website: str | None = Field(None, max_length=200, description="Yönlendirme yapılacak site (https://...)")
    referrals: bool | None = Field(None, description="Uygun durumlarda siteye nazik yönlendirme yapılsın mı")

    @model_validator(mode="after")
    def _website_scheme(self) -> "WellnessBrand":
        if self.website and not self.website.startswith(("https://", "http://")):
            raise ValueError("brand.website http:// veya https:// ile başlamalı.")
        return self


class WellnessConfig(BaseModel):
    """
    Sohbet özelleştirmesi. Gönderilen her alan varsayılan değeri ezer; gönderilmeyen alan varsayılanda kalır.
    Wellness çerçevesi (tanı koymama, ilaç önermeme, güvenlik kuralları) değiştirilemez ve her zaman uygulanır.
    """

    model_config = ConfigDict(extra="forbid")

    # --- kimlik ve davranış (system prompt'un özelleştirilebilir katmanı)
    system_prompt: str | None = Field(
        None, max_length=8000,
        description="Özelleştirilebilir katmanın TAMAMININ yerine geçer (kimlik, marka, tarz). "
                    "Wellness çerçevesi yine de eklenir. Verilirse aşağıdaki kimlik alanları kullanılmaz.",
    )
    assistant_name: str | None = Field(None, min_length=1, max_length=80, description="Asistanın adı")
    brand: WellnessBrand | None = None
    style: str | None = Field(None, max_length=1500, description="Konuşma tarzı (varsayılan: sakin, empatik, ...)")
    response_format: str | None = Field(None, max_length=1500, description="Yanıt biçimi (varsayılan: kısa, doğal)")
    introduce_self: bool | None = Field(None, description="İlk mesajda kendini tanıtsın mı (varsayılan: evet)")
    instructions: str | None = Field(None, max_length=4000, description="Varsayılan prompt'a eklenecek ek talimatlar")

    # --- model ayarları
    model: str | None = Field(None, max_length=100, description="LLM modeli (sunucudaki izin listesinden)")
    temperature: float | None = Field(None, ge=0.0, le=1.5)
    top_p: float | None = Field(None, gt=0.0, le=1.0)
    max_tokens: int | None = Field(None, ge=16, le=4000, description="Yanıt başına en fazla token")
    presence_penalty: float | None = Field(None, ge=-2.0, le=2.0)
    frequency_penalty: float | None = Field(None, ge=-2.0, le=2.0)

    # --- araçlar
    psych_analysis: bool | None = Field(
        None, description="Duygusal içerikte Türkçe psikolojik sinyal analizini kullansın mı (varsayılan: evet)")
    max_tool_rounds: int | None = Field(None, ge=0, le=3)


class WellnessChatRequest(BaseModel):
    messages: list[WellnessChatMessage] = Field(..., min_length=1)
    locale: str | None = Field(None, description="İsteğe bağlı: tr | en")
    session_id: str | None = Field(None, description="İsteğe bağlı anonim oturum kimliği")
    config: WellnessConfig | None = Field(None, description="İsteğe bağlı özelleştirme (bkz. WellnessConfig)")

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
