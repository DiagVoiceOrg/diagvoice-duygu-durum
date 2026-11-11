#!/usr/bin/env bash
# GPU sunucusunda dağıtım: kodu çek → build → başlat → hazır olmasını bekle → duman testi.
#
#   cd /opt/api && scripts/deploy.sh                 # feat/prod-hardening dalı
#   BRANCH=main scripts/deploy.sh
#   SKIP_BUILD=1 scripts/deploy.sh                   # yalnızca kod değiştiyse (bind mount) yeniden başlat
#
# Geri dönüş (tek konteyner, eski düzen):
#   docker compose down && docker compose -f docker-compose.single.yml up -d
set -euo pipefail
cd "$(dirname "$0")/.."

BRANCH="${BRANCH:-feat/prod-hardening}"
READY_TIMEOUT="${READY_TIMEOUT:-1200}"

log() { echo "[$(date -u +%H:%M:%S)] $*"; }

log "git: $BRANCH"
git fetch -q origin
git checkout -q "$BRANCH"
git pull -q --ff-only origin "$BRANCH"
log "commit: $(git log --oneline -1)"

if [ "${SKIP_BUILD:-0}" != 1 ]; then
  log "build"
  docker compose build
fi

log "başlat"
docker compose up -d --remove-orphans

log "gateway /ready bekleniyor (en fazla ${READY_TIMEOUT}s; ilk açılışta model indirmeleri sürebilir)"
start=$(date +%s)
until curl -sf -o /dev/null http://127.0.0.1:8085/ready; do
  if [ $(( $(date +%s) - start )) -ge "$READY_TIMEOUT" ]; then
    log "HATA: hazır olmadı. Durum:"
    curl -s http://127.0.0.1:8085/ready || true; echo
    docker compose ps
    exit 1
  fi
  sleep 10
done
log "hazır: $(curl -s http://127.0.0.1:8085/ready)"

F=diagvoice-backend/test-data/ornek-ses-kayitlari/bu-harika-bir-gun.m4a
code=$(curl -s -o /tmp/dv_smoke.json -w '%{http_code}' -F "file=@$F" http://127.0.0.1:8085/togg-analyze)
log "duman testi /togg-analyze: HTTP $code"
[ "$code" = 200 ] || { cat /tmp/dv_smoke.json; exit 1; }
python3 -c 'import json; d=json.load(open("/tmp/dv_smoke.json")); assert d["audio"] and d["disease"], d; print("  audio:", d["audio"]["pred_label"], "| disease:", d["disease"]["pred_label"])'
log "tamam"
