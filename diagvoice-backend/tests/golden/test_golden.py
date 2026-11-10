"""
Golden karşılaştırma: kayıtlı snapshot'lardaki isteği hedef sisteme atar, yanıtı karşılaştırır.

    GOLDEN_BASE_URL=http://127.0.0.1:8085 python -m pytest tests/golden -q
    GOLDEN_API_KEY=dv_sk_...   # F1 sonrası key zorunluysa
    GOLDEN_ONLY=analyze-fused  # sadece id'sinde geçen vakalar (virgülle birden fazla)

GOLDEN_BASE_URL verilmezse testler atlanır (yerel geliştirme / CI'da servis yoksa).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from tests.golden.cases import SNAPSHOT_DIR, case_from_dict
from tests.golden.compare import Rules, compare

BASE_URL = os.environ.get("GOLDEN_BASE_URL", "").strip()
API_KEY = os.environ.get("GOLDEN_API_KEY", "").strip() or None
ONLY = [s for s in os.environ.get("GOLDEN_ONLY", "").split(",") if s.strip()]
MAX_DIFFS_SHOWN = 25


SNAP_DIR = Path(os.environ.get("GOLDEN_SNAPSHOT_DIR", "").strip() or SNAPSHOT_DIR)


def _snapshot_files() -> list[Path]:
    files = sorted(SNAP_DIR.glob("*.json")) if SNAP_DIR.is_dir() else []
    if ONLY:
        files = [f for f in files if any(s in f.stem for s in ONLY)]
    return files


SNAPSHOTS = _snapshot_files()


@pytest.fixture(scope="module")
def client():
    from tests.golden.runner import make_client

    with make_client() as c:
        yield c


@pytest.mark.golden
@pytest.mark.skipif(not BASE_URL, reason="GOLDEN_BASE_URL tanımlı değil")
@pytest.mark.skipif(not SNAPSHOTS, reason="snapshot yok: önce `python -m tests.golden.capture` çalıştırın")
@pytest.mark.parametrize("snap_path", SNAPSHOTS, ids=[p.stem for p in SNAPSHOTS])
def test_golden(snap_path: Path, client) -> None:
    from tests.golden.runner import send_case

    snap = json.loads(snap_path.read_text(encoding="utf-8"))
    case = case_from_dict(snap["case"])
    rules = Rules().with_overrides(case.rules, extra_ignore=snap.get("volatile_paths"))

    got = send_case(client, BASE_URL, case, api_key=API_KEY)

    assert got.status == snap["status"], f"HTTP durumu {snap['status']} beklendi, {got.status} geldi: {got.body!r:.500}"
    if not snap["is_json"]:
        assert got.body == snap["response"]
        return
    assert got.is_json, f"JSON beklendi, gelen: {got.body!r:.500}"

    diffs = compare(snap["response"], got.body, rules)
    if diffs:
        shown = "\n".join(f"  - {d}" for d in diffs[:MAX_DIFFS_SHOWN])
        more = f"\n  ... ve {len(diffs) - MAX_DIFFS_SHOWN} fark daha" if len(diffs) > MAX_DIFFS_SHOWN else ""
        pytest.fail(f"{len(diffs)} fark ({case.path}, {case.audio or 'metin'}):\n{shown}{more}")
