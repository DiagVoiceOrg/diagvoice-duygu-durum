"""
registry.yaml'daki artefaktların SHA256'sını hesaplar.

  python scripts/hash_models.py            # kontrol: uyuşmayan/eksik olanları listeler
  python scripts/hash_models.py --write    # boş veya farklı sha256 değerlerini dosyaya yazar

MODEL_ROOT ortam değişkeni verilirse oradaki dosyalar kullanılır (sunucuda /app/models).
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "diagvoice-backend"
sys.path.insert(0, str(BACKEND))

from dv_worker import registry as R  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()
    reg = R.load(BACKEND / "registry.yaml")
    text = reg.path.read_text(encoding="utf-8")
    problems = 0
    for m in reg.models.values():
        for art in m.artifacts:
            if not art.path.is_file():
                print(f"EKSİK   {m.id}.{art.name}: {art.path}")
                problems += 1
                continue
            digest = R.sha256_file(art.path)
            if digest == art.sha256:
                print(f"OK      {m.id}.{art.name}")
                continue
            print(f"{'YAZILDI' if a.write else 'FARKLI '} {m.id}.{art.name}: {digest}")
            problems += 0 if a.write else 1
            if a.write:
                rel = art.path.relative_to(reg.model_root).as_posix() if art.path.is_relative_to(reg.model_root) else str(art.path)
                pat = re.compile(rf"(path:\s*{re.escape(rel)}\s*\n\s*sha256:\s*)(\"[^\"]*\"|[0-9a-f]*)")
                text, n = pat.subn(rf'\g<1>{digest}', text, count=1)
                if n == 0:
                    print(f"  ! registry'de '{rel}' satırının altında sha256 bulunamadı; elle ekleyin", file=sys.stderr)
    if a.write:
        reg.path.write_text(text, encoding="utf-8")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
