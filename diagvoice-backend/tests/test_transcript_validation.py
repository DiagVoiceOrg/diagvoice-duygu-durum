"""Transkript doğrulaması OpenAI'ye gider; DeepSeek ayarları okunmaz."""
from __future__ import annotations

import io
import json
import sys
import urllib.error
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "mental_fitness"))
import transcript_validation as TV  # noqa: E402

TEXT = "Bugün işte çok yoğun bir gün geçirdim ama akşam arkadaşlarımla buluşunca rahatladım."

ENV = [
    "TRANSCRIPT_VALIDATION_LLM", "DEEPSEEK_TRANSCRIPT_VALIDATION",
    "REQUIRE_TRANSCRIPT_VALIDATION", "REQUIRE_DEEPSEEK_TRANSCRIPT_VALIDATION",
    "TRANSCRIPT_VALIDATION_API_KEY", "TRANSCRIPT_VALIDATION_API_BASE", "TRANSCRIPT_VALIDATION_MODEL",
    "OPENAI_API_KEY", "OPENAI_API_BASE", "OPENAI_MODEL",
    "DEEPSEEK_API_KEY", "DEEPSEEK_API_BASE", "DEEPSEEK_MODEL",
]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for n in ENV:
        monkeypatch.delenv(n, raising=False)


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture
def capture(monkeypatch):
    calls = []
    state = {"answer": {"meaningful": True, "reason": "coherent"}, "error": None}

    def fake_urlopen(req, timeout=None):
        calls.append({"url": req.full_url, "auth": req.headers.get("Authorization"), "body": json.loads(req.data)})
        if state["error"]:
            raise state["error"]
        content = json.dumps(state["answer"])
        return _Resp(json.dumps({"choices": [{"message": {"content": content}}]}).encode())

    monkeypatch.setattr(TV.urllib.request, "urlopen", fake_urlopen)
    return calls, state


def test_uses_openai_settings_not_deepseek(monkeypatch, capture):
    calls, _ = capture
    monkeypatch.setenv("DEEPSEEK_TRANSCRIPT_VALIDATION", "1")  # eski bayrak hâlâ LLM'i açar
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4o-mini")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-deepseek")
    monkeypatch.setenv("DEEPSEEK_API_BASE", "https://api.deepseek.com/v1")
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-chat")

    ok, reason = TV.validate_transcript_meaningfulness(TEXT, "turkish", api_key=None)
    assert ok is True and reason == "coherent"
    c = calls[-1]
    assert c["url"] == "https://api.openai.com/v1/chat/completions"
    assert c["auth"] == "Bearer sk-openai"
    assert c["body"]["model"] == "gpt-4o-mini"
    assert c["body"]["response_format"] == {"type": "json_object"}


def test_dedicated_overrides(monkeypatch, capture):
    calls, state = capture
    monkeypatch.setenv("TRANSCRIPT_VALIDATION_LLM", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
    monkeypatch.setenv("TRANSCRIPT_VALIDATION_API_KEY", "sk-ayri")
    monkeypatch.setenv("TRANSCRIPT_VALIDATION_API_BASE", "https://proxy.example/v1/")
    monkeypatch.setenv("TRANSCRIPT_VALIDATION_MODEL", "gpt-4o")
    state["answer"] = {"meaningful": False, "reason": "gibberish"}
    ok, reason = TV.validate_transcript_meaningfulness(TEXT, "tr", api_key=None)
    assert ok is False and reason == "gibberish"
    c = calls[-1]
    assert c["url"] == "https://proxy.example/v1/chat/completions"
    assert c["auth"] == "Bearer sk-ayri" and c["body"]["model"] == "gpt-4o"


def test_llm_off_or_no_key_uses_heuristic_only(monkeypatch, capture):
    calls, _ = capture
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
    assert TV.validate_transcript_meaningfulness(TEXT, "tr", api_key=None) == (True, "llm_disabled_heuristic_only")
    monkeypatch.delenv("OPENAI_API_KEY")
    monkeypatch.setenv("TRANSCRIPT_VALIDATION_LLM", "1")
    assert TV.validate_transcript_meaningfulness(TEXT, "tr", api_key=None) == (True, "llm_api_key_missing_heuristic_only")
    assert not calls
    # yerel filtre LLM'den önce çalışır
    ok, reason = TV.validate_transcript_meaningfulness("çay yok " * 30, "tr", api_key=None)
    assert ok is False and reason and not calls


def test_llm_error_raises_and_flags(monkeypatch, capture):
    _, state = capture
    monkeypatch.setenv("TRANSCRIPT_VALIDATION_LLM", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
    state["error"] = urllib.error.HTTPError("u", 429, "quota", {}, io.BytesIO(b'{"error":"quota"}'))
    with pytest.raises(RuntimeError, match="HTTP 429"):
        TV.validate_transcript_meaningfulness(TEXT, "tr", api_key=None)
    assert TV.llm_required() is False
    monkeypatch.setenv("REQUIRE_DEEPSEEK_TRANSCRIPT_VALIDATION", "1")
    assert TV.llm_required() is True  # eski ad geçerli
    monkeypatch.setenv("REQUIRE_TRANSCRIPT_VALIDATION", "0")
    assert TV.llm_required() is False  # yeni ad önceliklidir
