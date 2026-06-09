"""Metin duygu + ses emosyonu birleştirme (4 sınıf: sadness, fear, happiness, anger)."""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from typing import Any

# Ses modeli sırası (voice_to_sentiment)
EMOTION_LABELS: tuple[str, ...] = ("sadness", "fear", "happiness", "anger")
EMOTION_ID2LABEL: dict[int, str] = {i: lab for i, lab in enumerate(EMOTION_LABELS)}

DEFAULT_AUDIO_VALENCE_WEIGHTS: tuple[float, ...] = (-1.0, -0.6, 1.0, -0.8)

# Metin prior vektörleri: [sadness, fear, happiness, anger]
_SENTIMENT_EMOTION_PRIORS: dict[str, tuple[float, float, float, float]] = {
    "POSITIVE": (0.05, 0.05, 0.85, 0.05),
    "NEGATIVE": (0.45, 0.15, 0.05, 0.35),
    "NEUTRAL": (0.25, 0.25, 0.25, 0.25),
}


@dataclass(frozen=True)
class FusionConfig:
    w_text: float = 0.5
    dynamic_fusion: bool = True
    w_text_min: float = 0.2
    w_text_max: float = 0.8
    audio_valence_weights: tuple[float, float, float, float] = DEFAULT_AUDIO_VALENCE_WEIGHTS


def load_fusion_config_from_env() -> FusionConfig:
    w_text = float(os.environ.get("FUSION_W_TEXT", "0.5"))
    w_text = max(0.0, min(1.0, w_text))
    dynamic = os.environ.get("DYNAMIC_FUSION", "1").strip().lower() not in {"0", "false", "no"}
    w_min = float(os.environ.get("W_TEXT_MIN", "0.2"))
    w_max = float(os.environ.get("W_TEXT_MAX", "0.8"))
    w_min = max(0.0, min(1.0, w_min))
    w_max = max(0.0, min(1.0, w_max))
    if w_min > w_max:
        w_min, w_max = w_max, w_min

    raw = os.environ.get("AUDIO_VALENCE_WEIGHTS", "")
    weights = DEFAULT_AUDIO_VALENCE_WEIGHTS
    if raw.strip():
        parts = [p.strip() for p in raw.split(",") if p.strip()]
        if len(parts) == 4:
            try:
                ws = tuple(float(p) for p in parts)
                if all(-1.0 <= w <= 1.0 for w in ws):
                    weights = ws  # type: ignore[assignment]
            except ValueError:
                pass

    return FusionConfig(
        w_text=w_text,
        dynamic_fusion=dynamic,
        w_text_min=w_min,
        w_text_max=w_max,
        audio_valence_weights=weights,
    )


def normalize_sentiment_label(label: str | None) -> str:
    """Positive/Negative/Notr → POSITIVE|NEGATIVE|NEUTRAL."""
    lab = (label or "").strip().upper()
    if lab in {"POSITIVE", "POS"}:
        return "POSITIVE"
    if lab in {"NEGATIVE", "NEG"}:
        return "NEGATIVE"
    if lab in {"NOTR", "NEUTRAL", "NÖTR", "NOTR."}:
        return "NEUTRAL"
    return "NEUTRAL"


def _normalize_probs(probs: list[float]) -> list[float]:
    p = [max(0.0, float(x)) for x in probs[:4]]
    if len(p) < 4:
        p.extend([0.0] * (4 - len(p)))
    s = sum(p)
    if s <= 0:
        return [0.25, 0.25, 0.25, 0.25]
    return [x / s for x in p]


def text_sentiment_to_valence(sentiment_label: str, score: float) -> float:
    norm = normalize_sentiment_label(sentiment_label)
    s = max(0.0, min(1.0, float(score)))
    if norm == "POSITIVE":
        v = s
    elif norm == "NEGATIVE":
        v = 1.0 - s
    else:
        v = 0.5
    return max(0.0, min(1.0, v))


def text_sentiment_to_emotion_probs(sentiment_label: str, score: float) -> list[float]:
    """Metin duygu etiketini 4 emosyon olasılık vektörüne map eder."""
    norm = normalize_sentiment_label(sentiment_label)
    prior = list(_SENTIMENT_EMOTION_PRIORS.get(norm, _SENTIMENT_EMOTION_PRIORS["NEUTRAL"]))
    s = max(0.0, min(1.0, float(score)))
    # Keskinlik: düşük skor → daha uniform; yüksek skor → prior belirgin
    sharpness = 0.35 + 0.65 * s
    uniform = [0.25, 0.25, 0.25, 0.25]
    mixed = [(1.0 - sharpness) * u + sharpness * p for u, p in zip(uniform, prior)]
    if norm == "NEUTRAL":
        # Nötr metin: düşük güven — fusion'da ses ağırlığı artsın diye daha flat
        mixed = [(0.7 * u + 0.3 * p) for u, p in zip(uniform, prior)]
    return _normalize_probs(mixed)


def text_valence_confidence(valence: float | None) -> float | None:
    if valence is None:
        return None
    v = float(valence)
    return max(0.0, min(1.0, abs(v - 0.5) * 2.0))


def text_sentiment_confidence(sentiment_label: str, score: float) -> float:
    norm = normalize_sentiment_label(sentiment_label)
    s = max(0.0, min(1.0, float(score)))
    if norm == "NEUTRAL":
        return max(0.0, min(1.0, 0.15 + 0.25 * (1.0 - abs(s - 0.5) * 2.0)))
    return s


def audio_entropy_confidence(probs: Any) -> float | None:
    if not isinstance(probs, list) or len(probs) < 4:
        return None
    try:
        p = _normalize_probs([float(x) for x in probs[:4]])
        ent = -sum(x * math.log(max(x, 1e-12)) for x in p)
        ent_max = math.log(4.0)
        conf = 1.0 - (ent / ent_max)
        return max(0.0, min(1.0, conf))
    except Exception:
        return None


def audio_overall_confidence(intensity: float | None, probs: Any) -> float | None:
    ent_conf = audio_entropy_confidence(probs)
    if intensity is None and ent_conf is None:
        return None
    inten = max(0.0, min(1.0, float(intensity))) if intensity is not None else None
    if inten is None:
        return ent_conf
    if ent_conf is None:
        return inten
    return max(0.0, min(1.0, 0.5 * inten + 0.5 * ent_conf))


def emotion_probs_to_valence(
    probs: list[float],
    intensity: float | None,
    weights: tuple[float, ...] = DEFAULT_AUDIO_VALENCE_WEIGHTS,
) -> float:
    p = _normalize_probs(probs)
    w = list(weights[:4])
    if len(w) < 4:
        w = list(DEFAULT_AUDIO_VALENCE_WEIGHTS)
    v_raw = sum(pi * wi for pi, wi in zip(p, w))
    v_raw = max(-1.0, min(1.0, v_raw))
    if intensity is None:
        return max(0.0, min(1.0, (v_raw + 1.0) / 2.0))
    inten = max(0.0, min(1.0, float(intensity)))
    v = 0.5 + inten * (v_raw / 2.0)
    return max(0.0, min(1.0, float(v)))


def audio_probs_to_valence(
    probs: Any,
    intensity: float | None = None,
    weights: tuple[float, ...] = DEFAULT_AUDIO_VALENCE_WEIGHTS,
) -> float | None:
    if not isinstance(probs, list) or len(probs) < 4:
        return None
    try:
        return emotion_probs_to_valence([float(x) for x in probs[:4]], intensity, weights)
    except Exception:
        return None


def fuse_emotion_probs(p_text: list[float], p_audio: list[float], w_text: float) -> list[float]:
    w = max(0.0, min(1.0, float(w_text)))
    pt = _normalize_probs(p_text)
    pa = _normalize_probs(p_audio)
    fused = [w * t + (1.0 - w) * a for t, a in zip(pt, pa)]
    return _normalize_probs(fused)


def compute_w_text_used(
    valence_text: float | None,
    valence_audio: float | None,
    text_result: dict[str, Any] | None,
    audio_result: dict[str, Any] | None,
    config: FusionConfig,
) -> float:
    w_text = config.w_text
    if not config.dynamic_fusion:
        return w_text

    text_conf = None
    if text_result and "score" in text_result:
        lab = text_result.get("sentiment") or text_result.get("label")
        if lab is not None:
            text_conf = text_sentiment_confidence(str(lab), float(text_result.get("score", 0.5)))
    if text_conf is None and valence_text is not None:
        text_conf = text_valence_confidence(valence_text)

    audio_conf = None
    if isinstance(audio_result, dict):
        audio_conf = audio_overall_confidence(
            audio_result.get("intensity"),
            audio_result.get("probs"),
        )

    if text_conf is None or audio_conf is None:
        return w_text

    ratio = text_conf / (text_conf + audio_conf + 1e-9)
    return config.w_text_min + (config.w_text_max - config.w_text_min) * ratio


def prob_disagreement(p_a: list[float], p_b: list[float]) -> float:
    """L1 mesafe / 2 → [0,1]."""
    a = _normalize_probs(p_a)
    b = _normalize_probs(p_b)
    return sum(abs(x - y) for x, y in zip(a, b)) / 2.0


def agreement_level(disagreement: float) -> str:
    if disagreement < 0.25:
        return "high"
    if disagreement < 0.45:
        return "medium"
    return "low"


def fuse(valence_text: float | None, valence_audio: float | None, w_text: float) -> dict[str, Any]:
    if valence_text is None and valence_audio is None:
        return {"valence": None, "label": None, "w_text": w_text}

    if valence_text is None:
        v = valence_audio
        w = 0.0
    elif valence_audio is None:
        v = valence_text
        w = 1.0
    else:
        w = w_text
        v = w * valence_text + (1.0 - w) * valence_audio

    label = "POSITIVE" if v is not None and v >= 0.5 else "NEGATIVE"
    return {"valence": v, "label": label, "w_text": w}


def build_emotion_fusion_payload(
    text_result: dict[str, Any] | None,
    audio_result: dict[str, Any] | None,
    config: FusionConfig | None = None,
) -> dict[str, Any]:
    """
    Metin + ses sonuçlarından unified_emotion, valence_*, fused, confidence üretir.
    Tek modality varsa unified_emotion yalnızca o kaynaktan türetilir.
    """
    cfg = config or load_fusion_config_from_env()
    weights = cfg.audio_valence_weights

    valence_text: float | None = None
    p_text: list[float] | None = None
    text_source: dict[str, Any] | None = None

    if text_result and "score" in text_result:
        sentiment_label = text_result.get("sentiment") or text_result.get("label")
        if sentiment_label is not None:
            lab_str = str(sentiment_label)
            score = float(text_result.get("score", 0.5))
            valence_text = text_sentiment_to_valence(lab_str, score)
            p_text = text_sentiment_to_emotion_probs(lab_str, score)
            text_source = {
                "sentiment": lab_str,
                "normalized": normalize_sentiment_label(lab_str),
                "score": score,
                "valence": valence_text,
                "probs": p_text,
            }

    valence_audio: float | None = None
    p_audio: list[float] | None = None
    audio_source: dict[str, Any] | None = None

    if isinstance(audio_result, dict) and isinstance(audio_result.get("probs"), list):
        probs = audio_result.get("probs")
        intensity = audio_result.get("intensity")
        valence_audio = audio_probs_to_valence(probs, intensity, weights)
        p_audio = _normalize_probs([float(x) for x in probs[:4]])
        audio_source = {
            "pred_label": audio_result.get("pred_label"),
            "pred_id": audio_result.get("pred_id"),
            "intensity": intensity,
            "valence": valence_audio,
            "probs": p_audio,
        }

    w_text_used = compute_w_text_used(valence_text, valence_audio, text_result, audio_result, cfg)

    unified_emotion: dict[str, Any] | None = None
    disagreement: float | None = None

    if p_text is not None and p_audio is not None:
        p_fused = fuse_emotion_probs(p_text, p_audio, w_text_used)
        disagreement = prob_disagreement(p_text, p_audio)
        pred_id = int(max(range(4), key=lambda i: p_fused[i]))
        unified_emotion = {
            "pred_id": pred_id,
            "pred_label": EMOTION_ID2LABEL[pred_id],
            "probs": p_fused,
            "labels": EMOTION_ID2LABEL,
            "agreement": agreement_level(disagreement),
            "disagreement": disagreement,
            "w_text": w_text_used,
            "sources": {
                "text": text_source,
                "audio": audio_source,
            },
        }
        fused_valence = emotion_probs_to_valence(p_fused, audio_result.get("intensity") if audio_result else None, weights)
        fused = {"valence": fused_valence, "label": "POSITIVE" if fused_valence >= 0.5 else "NEGATIVE", "w_text": w_text_used}
    elif p_text is not None:
        pred_id = int(max(range(4), key=lambda i: p_text[i]))
        unified_emotion = {
            "pred_id": pred_id,
            "pred_label": EMOTION_ID2LABEL[pred_id],
            "probs": p_text,
            "labels": EMOTION_ID2LABEL,
            "agreement": None,
            "disagreement": None,
            "w_text": 1.0,
            "sources": {"text": text_source, "audio": None},
        }
        fused = fuse(valence_text, None, 1.0)
    elif p_audio is not None:
        pred_id = int(max(range(4), key=lambda i: p_audio[i]))
        if isinstance(audio_result, dict) and audio_result.get("pred_id") is not None:
            try:
                pred_id = int(audio_result["pred_id"])
            except (TypeError, ValueError):
                pass
        unified_emotion = {
            "pred_id": pred_id,
            "pred_label": EMOTION_ID2LABEL.get(pred_id, EMOTION_ID2LABEL[int(max(range(4), key=lambda i: p_audio[i]))]),
            "probs": p_audio,
            "labels": EMOTION_ID2LABEL,
            "agreement": None,
            "disagreement": None,
            "w_text": 0.0,
            "sources": {"text": None, "audio": audio_source},
        }
        fused = fuse(None, valence_audio, 0.0)
    else:
        fused = fuse(None, None, cfg.w_text)

    text_conf = text_valence_confidence(valence_text)
    if text_result and text_result.get("score") is not None:
        lab = text_result.get("sentiment") or text_result.get("label")
        if lab is not None:
            text_conf = text_sentiment_confidence(str(lab), float(text_result["score"]))

    audio_conf = audio_overall_confidence(
        audio_result.get("intensity") if isinstance(audio_result, dict) else None,
        audio_result.get("probs") if isinstance(audio_result, dict) else None,
    )

    confidence = {
        "text": text_conf,
        "audio": audio_conf,
        "disagreement": disagreement,
        "dynamic_fusion": cfg.dynamic_fusion,
    }

    return {
        "unified_emotion": unified_emotion,
        "valence_text": valence_text,
        "valence_audio": valence_audio,
        "fused": fused,
        "confidence": confidence,
    }
