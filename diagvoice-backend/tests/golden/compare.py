"""JSON yanıtlarını toleranslı karşılaştırma."""

from __future__ import annotations

import difflib
import math
from dataclasses import dataclass, field, replace
from fnmatch import fnmatchcase
from typing import Any

# Her yanıtta değişmesi doğal olan alanlar.
DEFAULT_IGNORE: tuple[str, ...] = (
    "*processing_time*",
    "*elapsed*",
    "*latency*",
    "*uptime*",
    "*request_id*",
    "*timestamp*",
    "*created_at*",
    "*_ms",
)

# Serbest metin alanları: fp16 / farklı GPU ile Whisper birkaç karakter farklı yazabilir.
DEFAULT_FUZZY_TEXT: tuple[str, ...] = (
    "*.text",
    "*.transcript",
    "*.transcription",
)


@dataclass(frozen=True)
class Rules:
    abs_tol: float = 1e-3
    rel_tol: float = 1e-3
    ignore: tuple[str, ...] = DEFAULT_IGNORE
    fuzzy_text: tuple[str, ...] = DEFAULT_FUZZY_TEXT
    fuzzy_ratio: float = 0.9
    allow_extra_keys: bool = False

    def with_overrides(self, overrides: dict[str, Any] | None = None, extra_ignore: list[str] | None = None) -> "Rules":
        r = self
        if overrides:
            o = dict(overrides)
            for key in ("ignore", "fuzzy_text"):
                if key in o:
                    o[key] = tuple(getattr(r, key)) + tuple(o[key])
            r = replace(r, **o)
        if extra_ignore:
            r = replace(r, ignore=tuple(r.ignore) + tuple(extra_ignore))
        return r


@dataclass(frozen=True)
class Diff:
    path: str
    kind: str
    expected: Any = None
    actual: Any = None

    def __str__(self) -> str:
        return f"{self.path}: {self.kind} (beklenen={_short(self.expected)!s}, gelen={_short(self.actual)!s})"


def _short(v: Any, n: int = 120) -> str:
    s = repr(v)
    return s if len(s) <= n else s[: n - 3] + "..."


def _glob(pattern: str) -> str:
    # Yollarda liste indisleri var ("$.probs[0]"); fnmatch'te [..] karakter sınıfı olmasın.
    return pattern.replace("[", "[[]")


def _matches(path: str, patterns: tuple[str, ...]) -> bool:
    return any(path == p or fnmatchcase(path, _glob(p)) for p in patterns)


def _is_num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def compare(expected: Any, actual: Any, rules: Rules = Rules(), path: str = "$") -> list[Diff]:
    if path != "$" and _matches(path, rules.ignore):
        return []

    if _is_num(expected) and _is_num(actual):
        e, a = float(expected), float(actual)
        if math.isnan(e) and math.isnan(a):
            return []
        if math.isclose(e, a, rel_tol=rules.rel_tol, abs_tol=rules.abs_tol):
            return []
        return [Diff(path, f"sayı farkı Δ={abs(e - a):.6g}", expected, actual)]

    if type(expected) is not type(actual):
        return [Diff(path, "tip farkı", expected, actual)]

    if isinstance(expected, dict):
        diffs: list[Diff] = []
        for k in expected:
            sub = f"{path}.{k}"
            if k not in actual:
                if not _matches(sub, rules.ignore):
                    diffs.append(Diff(sub, "eksik alan", expected[k], None))
                continue
            diffs += compare(expected[k], actual[k], rules, sub)
        if not rules.allow_extra_keys:
            for k in actual:
                sub = f"{path}.{k}"
                if k not in expected and not _matches(sub, rules.ignore):
                    diffs.append(Diff(sub, "fazla alan", None, actual[k]))
        return diffs

    if isinstance(expected, list):
        if len(expected) != len(actual):
            return [Diff(path, f"liste uzunluğu {len(expected)} != {len(actual)}", expected, actual)]
        out: list[Diff] = []
        for i, (e, a) in enumerate(zip(expected, actual)):
            out += compare(e, a, rules, f"{path}[{i}]")
        return out

    if isinstance(expected, str):
        if expected == actual:
            return []
        if _matches(path, rules.fuzzy_text):
            ratio = difflib.SequenceMatcher(None, expected, actual).ratio()
            if ratio >= rules.fuzzy_ratio:
                return []
            return [Diff(path, f"metin benzerliği {ratio:.2f} < {rules.fuzzy_ratio}", expected, actual)]
        return [Diff(path, "değer farkı", expected, actual)]

    return [] if expected == actual else [Diff(path, "değer farkı", expected, actual)]


def changed_paths(a: Any, b: Any) -> list[str]:
    """İki koşu arasında değişen yollar (tolerans yok). Kayıt sırasında oynak alanları bulmak için."""
    strict = Rules(abs_tol=0.0, rel_tol=0.0, ignore=(), fuzzy_text=(), allow_extra_keys=False)
    return sorted({d.path for d in compare(a, b, strict)})
