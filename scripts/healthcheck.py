#!/usr/bin/env python3
"""
Tüm modellerin gerçekten çalıştığını doğrular (sunucuda, yalnızca standart kütüphane).

  python3 scripts/healthcheck.py                       # http://127.0.0.1:8085
  python3 scripts/healthcheck.py --base http://127.0.0.1:8085 --timeout 300

Her model için gerçek bir istek atar; yanıtta hata alanı veya boş sonuç varsa başarısız sayar.
Çıkış kodu: 0 = 10/10 model sağlıklı, 1 = en az biri sorunlu.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AUDIO = ROOT / "diagvoice-backend" / "test-data" / "ornek-ses-kayitlari" / "bu-harika-bir-gun.m4a"
TEXT = "Bugün kendimi çok iyi hissediyorum, her şey yolunda."


def _multipart(fields: dict[str, str], file_field: str, path: Path) -> tuple[bytes, str]:
    b = uuid.uuid4().hex
    parts = []
    for k, v in fields.items():
        parts.append(f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    parts.append(f'--{b}\r\nContent-Disposition: form-data; name="{file_field}"; filename="{path.name}"\r\n'
                 f"Content-Type: audio/mp4\r\n\r\n".encode() + path.read_bytes() + b"\r\n")
    parts.append(f"--{b}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={b}"


def call(base: str, path: str, *, timeout: float, audio_field: str | None = None, form: dict | None = None,
         json_body: dict | None = None, method: str = "POST") -> tuple[int, object, float]:
    if audio_field:
        data, ctype = _multipart(form or {}, audio_field, AUDIO)
    elif json_body is not None:
        data, ctype = json.dumps(json_body).encode(), "application/json"
    else:
        data, ctype = None, None
    req = urllib.request.Request(base + path, data=data, method=method if data else "GET",
                                 headers={"User-Agent": "diagvoice-healthcheck/1.0"})  # Cloudflare varsayılan UA'yı engelliyor
    if ctype:
        req.add_header("Content-Type", ctype)
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read()
            status = r.status
    except urllib.error.HTTPError as e:
        body, status = e.read(), e.code
    except Exception as e:  # bağlantı hatası
        return 0, {"error": f"{type(e).__name__}: {e}"}, time.perf_counter() - t0
    try:
        parsed = json.loads(body)
    except ValueError:
        parsed = body[:300].decode("utf-8", "replace")
    return status, parsed, time.perf_counter() - t0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8085")
    ap.add_argument("--timeout", type=float, default=300)
    a = ap.parse_args()
    base = a.base.rstrip("/")
    results: list[tuple[str, bool, str]] = []

    def check(name: str, ok: bool, detail: str) -> None:
        results.append((name, ok, detail))
        print(f"{'OK  ' if ok else 'HATA'}  {name:22} {detail}", flush=True)

    # 1) Tam analiz: 8 model (stt, metin duygu, ses emosyonu, WURSS, mental fitness, yaş-cinsiyet, depresyon, iş sağlığı)
    st, b, sec = call(base, "/analyze-fused", timeout=a.timeout, audio_field="file", form={"speech_language": "tr"})
    fused_map = {
        "stt": ("text", "text_error"),
        "text_sentiment": ("text_sentiment", "text_sentiment_error"),
        "emotion_audio": ("audio", "audio_error"),
        "disease_wurss": ("disease", "disease_error"),
        "mental_fitness": ("mental_fitness", "mental_fitness_error"),
        "age_gender": ("age_gender", "age_gender_error"),
        "depression": ("depression", "depression_error"),
        "occupational_health": ("benchmark_v2", "benchmark_v2_error"),
    }
    for name, (field, err) in fused_map.items():
        if st != 200 or not isinstance(b, dict):
            check(name, False, f"/analyze-fused HTTP {st}: {str(b)[:160]}")
            continue
        val, e = b.get(field), b.get(err)
        good = e is None and val not in (None, "", {})
        check(name, good, f"{sec:.1f}s" if good else f"{err}={str(e)[:160]} {field}={'boş' if not val else 'dolu'}")

    # 2) Ses emosyonu v2 (çok kipli; kendi içinde STT çağırır)
    st, b, sec = call(base, "/analyze-emotion-v2", timeout=a.timeout, audio_field="file", form={"speech_language": "tr"})
    good = st == 200 and isinstance(b, dict) and bool(b.get("prediction"))
    check("emotion_v2", good, f"{sec:.1f}s" if good else f"HTTP {st}: {str(b)[:160]}")

    # 3) Türkçe psikolojik sinyaller (metin)
    st, b, sec = call(base, "/analyze-turkish-psych-signals", timeout=a.timeout, json_body={"text": TEXT})
    good = st == 200 and isinstance(b, dict) and bool(b.get("predictions"))
    check("turkish_psych", good, f"{sec:.1f}s" if good else f"HTTP {st}: {str(b)[:160]}")

    # 4) TOGG akışı (araç senaryosu)
    st, b, sec = call(base, "/togg-analyze", timeout=a.timeout, audio_field="file")
    good = st == 200 and isinstance(b, dict) and b.get("audio") and b.get("disease") and not b.get("audio_error") and not b.get("disease_error")
    check("togg-analyze", bool(good), f"{sec:.2f}s" if good else f"HTTP {st}: {str(b)[:160]}")

    # 5) Metin + ses füzyonu (text_sentiment'in wav2vec dalı)
    st, b, sec = call(base, "/analyze-text-audio-fusion", timeout=a.timeout, audio_field="audio",
                      form={"text": TEXT, "fusion_mode": "dynamic"})
    good = st == 200 and isinstance(b, dict) and b.get("fusion") is not None
    check("text_audio_fusion", bool(good), f"{sec:.1f}s" if good else f"HTTP {st}: {str(b)[:160]}")

    failed = [n for n, ok, _ in results if not ok]
    models = 10 - len({n for n in failed if n in list(fused_map) + ["emotion_v2", "turkish_psych"]})
    print(f"\nSONUÇ: {models}/10 model sağlıklı" + (f" — sorunlu: {', '.join(failed)}" if failed else ""))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
