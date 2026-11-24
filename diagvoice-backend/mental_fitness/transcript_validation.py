"""Transkript anlamlılık kontrolü: önce yerel tekrar filtresi, sonra OpenAI (sohbetle aynı sağlayıcı).

Ortam değişkenleri (hepsi isteğe bağlı; boşsa sohbetin OPENAI_* ayarları kullanılır):
  TRANSCRIPT_VALIDATION_LLM=1           LLM kontrolünü aç (eski ad: DEEPSEEK_TRANSCRIPT_VALIDATION)
  REQUIRE_TRANSCRIPT_VALIDATION=1       LLM'e ulaşılamazsa isteği 502 ile reddet
                                        (eski ad: REQUIRE_DEEPSEEK_TRANSCRIPT_VALIDATION; varsayılan 0 = yerel filtreyle devam)
  TRANSCRIPT_VALIDATION_API_KEY         yoksa OPENAI_API_KEY
  TRANSCRIPT_VALIDATION_API_BASE        yoksa OPENAI_API_BASE, o da yoksa https://api.openai.com/v1
  TRANSCRIPT_VALIDATION_MODEL           yoksa OPENAI_MODEL, o da yoksa gpt-4o-mini
DEEPSEEK_API_KEY / DEEPSEEK_API_BASE / DEEPSEEK_MODEL artık okunmaz.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from collections import Counter

DEFAULT_API_BASE = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-4o-mini"


def _env_flag(*names: str) -> bool:
    for n in names:
        v = os.environ.get(n, "").strip().lower()
        if v:
            return v in ("1", "true", "yes")
    return False


def _env_first(*names: str) -> str:
    for n in names:
        v = os.environ.get(n, "").strip()
        if v:
            return v
    return ""


def llm_enabled() -> bool:
    return _env_flag("TRANSCRIPT_VALIDATION_LLM", "DEEPSEEK_TRANSCRIPT_VALIDATION")


def llm_required() -> bool:
    return _env_flag("REQUIRE_TRANSCRIPT_VALIDATION", "REQUIRE_DEEPSEEK_TRANSCRIPT_VALIDATION")


def llm_api_key() -> str:
    return _env_first("TRANSCRIPT_VALIDATION_API_KEY", "OPENAI_API_KEY")


def llm_api_base() -> str:
    return (_env_first("TRANSCRIPT_VALIDATION_API_BASE", "OPENAI_API_BASE") or DEFAULT_API_BASE).rstrip("/")


def llm_model() -> str:
    return _env_first("TRANSCRIPT_VALIDATION_MODEL", "OPENAI_MODEL") or DEFAULT_MODEL


def transcript_is_low_information_repetition(text: str) -> tuple[bool, str]:
    """
    STT çıktısı çoğu zaman anlamsız tekrarlardan oluşuyorsa (ör. onlarca kez 'çay yok'),
    LLM'e gitmeden False dönmek için kaba kontrol.

    Returns:
        (reject, reason_code) — reject True ise transkript mental fitness için uygun değil.
    """
    raw = (text or "").strip()
    if len(raw) < 24:
        return False, ""

    words = re.findall(r"\w+", raw.lower(), flags=re.UNICODE)
    n = len(words)
    if n < 14:
        return False, ""

    uniq = len(set(words))
    diversity = uniq / n
    if diversity < 0.14:
        return True, "high_repetition_low_word_diversity"

    top_count = Counter(words).most_common(1)[0][1]
    if top_count / n > 0.32:
        return True, "single_word_dominated"

    if n >= 24:
        bigrams = [f"{words[i]}_{words[i + 1]}" for i in range(n - 1)]
        buniq = len(set(bigrams))
        if n >= 30 and buniq <= 3:
            return True, "tiny_phrase_looped"
        if len(bigrams) > 0 and buniq / len(bigrams) < 0.06 and n >= 28:
            return True, "bigram_loop_low_diversity"

    return False, ""


def _extract_json_object(raw: str) -> dict:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
        raw = re.sub(r"\s*```\s*$", "", raw)
    m = re.search(r"\{[\s\S]*\}", raw)
    if not m:
        raise ValueError("Model yanıtında JSON nesnesi bulunamadı")
    return json.loads(m.group())


def _language_prompt_name(language_ui: str) -> str:
    key = (language_ui or "").strip().lower()
    return {
        "turkish": "Turkish",
        "english": "English",
        "arabic": "Arabic",
        "tr": "Turkish",
        "en": "English",
        "ar": "Arabic",
    }.get(key, language_ui or "unknown")


def validate_transcript_meaningfulness(
    text: str,
    language_ui: str,
    *,
    api_key: str | None,
    base_url: str | None = None,
    model: str | None = None,
    timeout_s: float = 45.0,
) -> tuple[bool, str]:
    """
    Önce tekrar / düşük çeşitlilik filtresi; ardından (LLM açık ve anahtar varsa) OpenAI ile doğrular.

    Returns:
        (meaningful, reason) — reason kısa kod veya İngilizce gerekçe / skip nedeni.
    Raises:
        RuntimeError — LLM'e ulaşılamadı veya yanıt çözümlenemedi.
    """
    trimmed = (text or "").strip()
    if len(trimmed) > 8000:
        trimmed = trimmed[:8000] + "…"

    reject, rep_reason = transcript_is_low_information_repetition(trimmed)
    if reject:
        return False, rep_reason

    # Harici LLM varsayılan KAPALI; yalnızca TRANSCRIPT_VALIDATION_LLM=1 iken çağrılır.
    if not llm_enabled():
        return True, "llm_disabled_heuristic_only"

    key = (api_key if api_key is not None else llm_api_key()).strip()
    if not key:
        return True, "llm_api_key_missing_heuristic_only"

    url = (base_url or llm_api_base()).rstrip("/") + "/chat/completions"
    mdl = model or llm_model()
    lang_name = _language_prompt_name(language_ui)

    system = (
        "You judge whether a speech transcript is coherent, substantive speech in the given language "
        "for downstream mental-health-related modelling (not clinical diagnosis). "
        "Respond with ONE JSON object only, no markdown: "
        '{"meaningful": <true|false>, "reason": "<brief under 120 chars, English>"}. '
        "Set meaningful=false if ANY apply: (1) gibberish, random characters, or unrelated fragments; "
        "(2) obsessive repetition — the same short phrase or 1–3 words looped many times with almost no new content "
        '(e.g. dozens of repeats like "no tea no tea" / Turkish equivalents); '
        "(3) mantra-like drilling with no progression or varied ideas; "
        "(4) clearly stuck/errorful ASR spam. "
        "meaningful=true for normal conversation, explanations, or varied sentences even if brief. "
        "Poetic or deliberate repetition with clear structure still counts as meaningful."
    )
    user_msg = f'Expected spoken language (UI selection): {lang_name} ({language_ui}).\nTranscript:\n"""{trimmed}"""'

    payload = {
        "model": mdl,
        "temperature": 0,
        "max_tokens": 200,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_msg},
        ],
    }

    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"Transcript LLM HTTP {e.code}: {err_body}") from e
    except Exception as e:
        raise RuntimeError(f"Transcript LLM isteği başarısız: {e}") from e

    try:
        content = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as e:
        raise RuntimeError(f"Transcript LLM yanıt şekli beklenenden farklı: {body!r}") from e

    try:
        obj = _extract_json_object(content)
        meaningful = bool(obj.get("meaningful"))
        reason = str(obj.get("reason", "") or "").strip() or ("coherent" if meaningful else "not_meaningful")
        return meaningful, reason[:500]
    except (json.JSONDecodeError, ValueError, TypeError) as e:
        raise RuntimeError(f"Transcript LLM JSON çözümlenemedi: {content[:400]} ({e})") from e
