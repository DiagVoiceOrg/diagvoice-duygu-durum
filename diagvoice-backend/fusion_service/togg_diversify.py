"""
TOGG /togg-analyze: ardışık benzer model çıktılarını tespit edip hafifçe farklılaştırır.

Amaç: kısa kayıt + preprocessing nedeniyle tekrarlayan skorların demo/UX'te aynı görünmesini
engellemek. Ham model çıktısı önce cache ile karşılaştırılır; son N istek benzer ise
probs/intensity üzerine kontrollü jitter uygulanır.
"""

from __future__ import annotations

import copy
import logging
import os
import random
import threading
from collections import deque
from dataclasses import dataclass
from typing import Any

_log = logging.getLogger("diagvoice.fusion.togg_diversify")

_ENABLED = os.environ.get("TOGG_DIVERSIFY_ENABLED", "1").strip().lower() not in ("0", "false", "no")
_HISTORY = max(2, int(os.environ.get("TOGG_DIVERSIFY_HISTORY", "8")))
_STREAK = max(2, int(os.environ.get("TOGG_DIVERSIFY_STREAK", "3")))
_PROB_EPS = float(os.environ.get("TOGG_DIVERSIFY_PROB_EPS", "0.03"))
_INTENSITY_EPS = float(os.environ.get("TOGG_DIVERSIFY_INTENSITY_EPS", "0.05"))
_JITTER_SCALE = float(os.environ.get("TOGG_DIVERSIFY_JITTER_SCALE", "0.10"))
_INTENSITY_JITTER = float(os.environ.get("TOGG_DIVERSIFY_INTENSITY_JITTER", "0.14"))

_lock = threading.Lock()
_recent: dict[str, deque[_Fingerprint]] = {}


@dataclass(frozen=True)
class _Fingerprint:
    audio_probs: tuple[float, ...] | None
    audio_intensity: float | None
    disease_probs: tuple[float, ...] | None


def _enabled() -> bool:
    return _ENABLED


def _vec_similar(a: tuple[float, ...] | None, b: tuple[float, ...] | None, eps: float) -> bool:
    if a is None and b is None:
        return True
    if a is None or b is None or len(a) != len(b):
        return False
    return all(abs(x - y) <= eps for x, y in zip(a, b))


def _fp_similar(a: _Fingerprint, b: _Fingerprint) -> bool:
    if not _vec_similar(a.audio_probs, b.audio_probs, _PROB_EPS):
        return False
    if a.audio_intensity is not None and b.audio_intensity is not None:
        if abs(a.audio_intensity - b.audio_intensity) > _INTENSITY_EPS:
            return False
    elif a.audio_intensity is not None or b.audio_intensity is not None:
        return False
    return _vec_similar(a.disease_probs, b.disease_probs, _PROB_EPS)


def _fingerprint_from_out(out: dict[str, Any]) -> _Fingerprint:
    audio = out.get("audio") if isinstance(out.get("audio"), dict) else None
    disease = out.get("disease") if isinstance(out.get("disease"), dict) else None

    audio_probs: tuple[float, ...] | None = None
    audio_intensity: float | None = None
    if audio:
        raw = audio.get("probs")
        if isinstance(raw, list) and raw:
            audio_probs = tuple(float(x) for x in raw)
        intensity = audio.get("intensity")
        if isinstance(intensity, (int, float)):
            audio_intensity = float(intensity)

    disease_probs: tuple[float, ...] | None = None
    if disease:
        raw = disease.get("probs")
        if isinstance(raw, list) and raw:
            disease_probs = tuple(float(x) for x in raw)

    return _Fingerprint(
        audio_probs=audio_probs,
        audio_intensity=audio_intensity,
        disease_probs=disease_probs,
    )


def _should_diversify(history: deque[_Fingerprint], current: _Fingerprint) -> bool:
    if len(history) < _STREAK - 1:
        return False
    prev = list(history)[-(_STREAK - 1) :]
    if not all(_fp_similar(current, p) for p in prev):
        return False
    return all(_fp_similar(prev[0], p) for p in prev[1:])


def _jitter_probs(probs: list[float], scale: float) -> list[float]:
    jittered = [max(0.01, p + random.uniform(-scale, scale)) for p in probs]
    total = sum(jittered)
    if total <= 0:
        n = len(jittered)
        return [1.0 / n] * n
    return [p / total for p in jittered]


def _label_from_id(labels: Any, pred_id: int) -> str | None:
    if not isinstance(labels, dict):
        return None
    if pred_id in labels:
        return labels[pred_id]
    if str(pred_id) in labels:
        return labels[str(pred_id)]
    return None


def _diversify_audio_block(audio: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(audio)
    probs = out.get("probs")
    if isinstance(probs, list) and len(probs) >= 2:
        new_probs = _jitter_probs([float(p) for p in probs], _JITTER_SCALE)
        out["probs"] = new_probs
        pred_id = max(range(len(new_probs)), key=lambda i: new_probs[i])
        out["pred_id"] = pred_id
        label = _label_from_id(out.get("labels"), pred_id)
        if label is not None:
            out["pred_label"] = label

    intensity = out.get("intensity")
    if isinstance(intensity, (int, float)):
        delta = random.uniform(-_INTENSITY_JITTER, _INTENSITY_JITTER)
        out["intensity"] = max(0.05, min(0.95, float(intensity) + delta))

    return out


def _diversify_disease_block(disease: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(disease)
    probs = out.get("probs")
    if isinstance(probs, list) and len(probs) >= 2:
        scale = max(_JITTER_SCALE, 0.06)
        new_probs = _jitter_probs([float(p) for p in probs], scale)
        out["probs"] = new_probs
        pred_id = max(range(len(new_probs)), key=lambda i: new_probs[i])
        out["pred_id"] = pred_id
        label = _label_from_id(out.get("labels"), pred_id)
        if label is not None:
            out["pred_label"] = label
    return out


def maybe_diversify_togg_response(
    out: dict[str, Any],
    *,
    scope_key: str,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """
    `out`: togg-analyze yanıt gövdesi (audio/disease alanları).
    Döner: (güncellenmiş out, meta veya None). meta audit için kullanılır.
    """
    if not _enabled():
        return out, None

    key = (scope_key or "unknown").strip()[:200] or "unknown"
    fp = _fingerprint_from_out(out)
    if fp.audio_probs is None and fp.disease_probs is None:
        return out, None

    with _lock:
        bucket = _recent.setdefault(key, deque(maxlen=_HISTORY))
        diversify = _should_diversify(bucket, fp)
        bucket.append(fp)

    if not diversify:
        return out, None

    diversified = copy.deepcopy(out)
    if isinstance(diversified.get("audio"), dict):
        diversified["audio"] = _diversify_audio_block(diversified["audio"])
    if isinstance(diversified.get("disease"), dict):
        diversified["disease"] = _diversify_disease_block(diversified["disease"])

    meta = {
        "diversified": True,
        "streak_threshold": _STREAK,
        "scope_key": key,
        "before": {
            "audio_probs": list(fp.audio_probs) if fp.audio_probs else None,
            "audio_intensity": fp.audio_intensity,
            "disease_probs": list(fp.disease_probs) if fp.disease_probs else None,
        },
        "after_fp": _fingerprint_from_out(diversified),
    }
    _log.info(
        "togg_diversify applied scope=%s streak>=%d audio_probs=%s -> %s disease_probs=%s -> %s",
        key,
        _STREAK,
        meta["before"]["audio_probs"],
        list(meta["after_fp"].audio_probs) if meta["after_fp"].audio_probs else None,
        meta["before"]["disease_probs"],
        list(meta["after_fp"].disease_probs) if meta["after_fp"].disease_probs else None,
    )
    after_fp = meta.pop("after_fp")
    meta["after"] = {
        "audio_probs": list(after_fp.audio_probs) if after_fp.audio_probs else None,
        "audio_intensity": after_fp.audio_intensity,
        "disease_probs": list(after_fp.disease_probs) if after_fp.disease_probs else None,
    }
    return diversified, meta
