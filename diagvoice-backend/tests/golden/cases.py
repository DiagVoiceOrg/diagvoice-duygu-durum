"""
Golden test vakaları: mevcut API'ye atılacak sabit istekler.

Her vaka tek bir HTTP isteğidir. `capture.py` bunları çalışan sisteme atıp yanıtı
`snapshots/<case_id>.json` olarak kaydeder; `test_golden.py` aynı isteği yeni sisteme atıp
kayıtla karşılaştırır.

Kapsam dışı (bilinçli):
- /analyze-mental-fitness/validate-transcript-meaning: DeepSeek LLM, deterministik değil.
- /wellness/*: OpenAI LLM, deterministik değil.
- /analyze-emotion-fusion: girdisi diğer servislerin çıktısı; /analyze-fused içinde zaten ölçülüyor.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

BACKEND_ROOT = Path(__file__).resolve().parents[2]
SAMPLES_DIR = BACKEND_ROOT / "test-data" / "ornek-ses-kayitlari"
SNAPSHOT_DIR = Path(__file__).resolve().parent / "snapshots"

# 3 konuşmalı Türkçe kayıt (STT/metin içerikli) + her duygu klasöründen 1 kayıt.
AUDIO_SAMPLES: list[str] = [
    "bu-harika-bir-gun.m4a",
    "dersten-kalacağım.m4a",
    "karisik.m4a",
    "anger/1s1Rl19d81ZDzADlnDAS.wav",
    "fear/0NV4vQzAppvyre1qM0ef.wav",
    "happy/1TqcKLyXmsch2iMjJ7hp.wav",
    "sad/02cNmaVN66MFAo9B0XUC.wav",
]

TEXT_SAMPLES: list[str] = [
    "Bugün kendimi çok iyi hissediyorum, her şey yolunda gidiyor.",
    "Son zamanlarda hiçbir şeyden zevk almıyorum, sürekli yorgunum ve uyuyamıyorum.",
    "Toplantı yarın saat üçte başlayacak.",
]


@dataclass(frozen=True)
class Case:
    id: str
    method: str
    path: str
    audio: Optional[str] = None          # SAMPLES_DIR'e göre göreli yol
    file_field: str = "file"
    form: dict[str, str] = field(default_factory=dict)
    query: dict[str, str] = field(default_factory=dict)
    json: Optional[dict[str, Any]] = None
    # Vaka bazında karşılaştırma ayarı (compare.Rules alanları), ör. {"abs_tol": 1e-2}
    rules: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_TR = str.maketrans("ıİşŞğĞçÇöÖüÜ", "iIsSgGcCoOuU")


def _slug(value: str) -> str:
    v = unicodedata.normalize("NFKD", value.translate(_TR)).encode("ascii", "ignore").decode("ascii")
    v = re.sub(r"\.[a-z0-9]+$", "", v.lower())
    return re.sub(r"[^a-z0-9]+", "-", v).strip("-")


def _audio_cases(path: str, **kw: Any) -> list[Case]:
    ep = _slug(path)
    return [Case(id=f"{ep}__{_slug(a)}", method="POST", path=path, audio=a, **kw) for a in AUDIO_SAMPLES]


def _text_cases(path: str) -> list[Case]:
    ep = _slug(path)
    return [
        Case(id=f"{ep}__text{i + 1}", method="POST", path=path, json={"text": t})
        for i, t in enumerate(TEXT_SAMPLES)
    ]


def build_cases() -> list[Case]:
    cases: list[Case] = []
    # Tek ses girdili model uçları
    for p in (
        "/analyze-voice-sentiment",
        "/analyze-depression",
        "/analyze-disease",
        "/analyze-age-gender",
        "/analyze-mental-fitness",
    ):
        cases += _audio_cases(p)

    # STT içeren uçlar
    tr = {"speech_language": "tr"}
    cases += _audio_cases("/analyze-voice-to-text", form=tr)
    cases += _audio_cases("/analyze-fused", form=tr)
    cases += _audio_cases("/analyze-emotion-v2", form=tr, query={"include_branches": "true"})

    # Benchmark (iş sağlığı) — transcript boş: sadece ses özellikleri
    cases += _audio_cases("/analyze-benchmark-v2", form={"transcript": ""})

    # Metin + ses füzyonu (sabit metinle)
    cases += _audio_cases(
        "/analyze-text-audio-fusion",
        file_field="audio",
        form={"text": TEXT_SAMPLES[0], "fusion_mode": "dynamic"},
    )

    # TOGG profili. Kayıt sırasında TOGG_DIVERSIFY_ENABLED=0 olmalı (bkz. README).
    cases += _audio_cases("/togg-analyze")

    # Sadece metin
    cases += _text_cases("/analyze-text-sentiment")
    cases += _text_cases("/analyze-turkish-psych-signals")

    ids = [c.id for c in cases]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        raise RuntimeError(f"Tekrarlanan vaka id'leri: {sorted(dupes)}")
    return cases


def case_from_dict(d: dict[str, Any]) -> Case:
    return Case(**d)
