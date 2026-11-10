#!/usr/bin/env sh
# Çalışan backend konteynerindeki paket sürümlerini sabitler.
# Sunucuda, depo kökünden çalıştırın:  sh scripts/freeze_requirements.sh
# Çıktı: diagvoice-backend/requirements.lock  (git'e eklenmeli)
set -eu

SERVICE="${SERVICE:-backend}"
OUT="diagvoice-backend/requirements.lock"

if ! docker compose ps --status running --services | grep -qx "$SERVICE"; then
  echo "HATA: '$SERVICE' servisi çalışmıyor. Önce: docker compose up -d $SERVICE" >&2
  exit 1
fi

{
  echo "# Otomatik üretildi: $(date -u +%Y-%m-%dT%H:%M:%SZ) — scripts/freeze_requirements.sh"
  echo "# Kaynak: çalışan '$SERVICE' konteyneri. Elle düzenlemeyin."
  docker compose exec -T "$SERVICE" python -c "import torch,sys; print(f'# python {sys.version.split()[0]} · torch {torch.__version__} · cuda {torch.version.cuda} · gpu {torch.cuda.is_available()}')"
  docker compose exec -T "$SERVICE" pip freeze --exclude-editable
} > "$OUT"

echo "Yazıldı: $OUT ($(grep -vc '^#' "$OUT") paket)"
grep -E '^(torch|torchaudio|transformers|librosa|opensmile|scikit-learn|numpy)==' "$OUT" || true
