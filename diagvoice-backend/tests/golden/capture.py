"""
Çalışan sistemden golden snapshot kaydeder.

Kullanım (diagvoice-backend klasöründen):
    python -m tests.golden.capture --base-url http://127.0.0.1:8085
    python -m tests.golden.capture --base-url http://127.0.0.1:8085 --only analyze-fused

Her vaka varsayılan olarak 2 kez çalıştırılır; iki koşu arasında değişen alanlar
"volatile_paths" olarak kaydedilir ve karşılaştırmada yok sayılır.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from tests.golden.cases import BACKEND_ROOT, SNAPSHOT_DIR, Case, build_cases
from tests.golden.compare import changed_paths
from tests.golden.runner import make_client, send_case


def _git_commit() -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=BACKEND_ROOT, capture_output=True, text=True, timeout=5
        )
        return out.stdout.strip() or None
    except Exception:
        return None


def _server_info(client, base_url: str) -> Any:
    try:
        r = client.get(base_url.rstrip("/") + "/")
        return r.json()
    except Exception as e:  # bilgi amaçlı, kayıt için zorunlu değil
        return {"error": str(e)}


def _capture_case(client, base_url: str, case: Case, repeat: int, api_key: str | None) -> dict[str, Any]:
    runs = [send_case(client, base_url, case, api_key=api_key) for _ in range(repeat)]
    first = runs[0]
    warnings: list[str] = []

    statuses = sorted({r.status for r in runs})
    if len(statuses) > 1:
        warnings.append(f"koşular arasında farklı HTTP durumu: {statuses}")

    volatile: set[str] = set()
    for other in runs[1:]:
        if other.is_json and first.is_json:
            volatile.update(changed_paths(first.body, other.body))

    if case.path == "/togg-analyze" and any("prob" in p or "intensity" in p for p in volatile):
        warnings.append("TOGG skorları koşular arasında değişti: TOGG_DIVERSIFY_ENABLED=0 ile kaydedin")
    if first.status >= 500:
        warnings.append(f"sunucu hatası {first.status}")

    return {
        "case": case.to_dict(),
        "status": first.status,
        "is_json": first.is_json,
        "response": first.body,
        "volatile_paths": sorted(volatile),
        "seconds": [round(r.seconds, 3) for r in runs],
        "warnings": warnings,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Golden snapshot kaydı")
    ap.add_argument("--base-url", help="ör. http://127.0.0.1:8085 (--list dışında zorunlu)")
    ap.add_argument("--out", type=Path, default=SNAPSHOT_DIR)
    ap.add_argument("--only", action="append", default=[], help="vaka id'sinde geçen metin (tekrarlanabilir)")
    ap.add_argument("--repeat", type=int, default=2, help="vaka başına koşu sayısı (oynak alan tespiti)")
    ap.add_argument("--api-key", default=None)
    ap.add_argument("--timeout", type=float, default=600.0)
    ap.add_argument("--list", action="store_true", help="sadece vakaları listele")
    args = ap.parse_args(argv)

    cases = build_cases()
    if args.only:
        cases = [c for c in cases if any(s in c.id for s in args.only)]
    if args.list:
        for c in cases:
            print(c.id)
        print(f"{len(cases)} vaka")
        return 0
    if not args.base_url:
        ap.error("--base-url gerekli")
    if not cases:
        print("Eşleşen vaka yok.", file=sys.stderr)
        return 2

    args.out.mkdir(parents=True, exist_ok=True)
    meta = {
        "captured_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "base_url": args.base_url,
        "git_commit": _git_commit(),
        "repeat": args.repeat,
    }

    failures = 0
    t0 = time.monotonic()
    with make_client(args.timeout) as client:
        meta["server_info"] = _server_info(client, args.base_url)
        for i, case in enumerate(cases, 1):
            try:
                snap = _capture_case(client, args.base_url, case, max(1, args.repeat), args.api_key)
            except Exception as e:
                failures += 1
                print(f"[{i}/{len(cases)}] HATA  {case.id}: {e}", file=sys.stderr)
                continue
            snap["meta"] = meta
            (args.out / f"{case.id}.json").write_text(
                json.dumps(snap, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            flag = "UYARI" if snap["warnings"] else "ok   "
            print(
                f"[{i}/{len(cases)}] {flag} {case.id} status={snap['status']} "
                f"süre={snap['seconds']} oynak={len(snap['volatile_paths'])}"
            )
            for w in snap["warnings"]:
                print(f"        - {w}")

    print(f"\n{len(cases) - failures}/{len(cases)} vaka kaydedildi → {args.out} ({time.monotonic() - t0:.0f} sn)")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
