#!/usr/bin/env bash
# GPU sunucusunda canlıya alma — kendini korur:
#   1. kodu çek, image'ı build et (eski sistem bu sırada çalışmaya devam eder)
#   2. eski sistemi durdur, yeni düzeni başlat (gateway + worker-gpu + worker-cpu + redis)
#   3. tüm modeller hazır olana kadar bekle, 10 modelin her birine gerçek istek at (scripts/healthcheck.py)
#   4. herhangi biri sağlıksızsa: tanı loglarını kaydet ve OTOMATİK olarak kanıtlanmış yedek düzene dön
#      (docker-compose.single.yml, tek konteyner, her model ayrı süreç) ve onu da aynı kontrolle doğrula
#
#   cd /opt/api && scripts/deploy.sh
#   BRANCH=main scripts/deploy.sh
#   NO_ROLLBACK=1 scripts/deploy.sh      # hata olursa geri dönme (tanı için)
#   MODE=single scripts/deploy.sh        # doğrudan yedek düzeni kur
#
# Kesinti: eski sistem durdurulduğu andan modeller yüklenene kadar (HF önbelleği doluysa birkaç dakika).
set -uo pipefail
cd "$(dirname "$0")/.."

BRANCH="${BRANCH:-feat/prod-hardening}"
READY_TIMEOUT="${READY_TIMEOUT:-1500}"
MODE="${MODE:-multi}"
TS="$(date -u +%Y%m%dT%H%M%SZ)"
DIAG="deploy-logs/$TS"
mkdir -p "$DIAG" data/jobs data/audio_recordings

log() { echo "[$(date -u +%H:%M:%S)] $*" | tee -a "$DIAG/deploy.log"; }
die() { log "HATA: $*"; exit 1; }

SINGLE="docker compose -f docker-compose.single.yml"
MULTI="docker compose -f docker-compose.yml"

wait_healthy() {
  # $1 = etiket. Önce gateway cevap versin, sonra healthcheck.py 10/10 geçsin (her 30 sn'de bir dener).
  local label="$1" start
  start=$(date +%s)
  log "$label: modellerin yüklenmesi bekleniyor (en fazla ${READY_TIMEOUT}s)"
  until curl -sf -o /dev/null http://127.0.0.1:8085/health; do
    [ $(( $(date +%s) - start )) -ge "$READY_TIMEOUT" ] && { log "$label: gateway hiç cevap vermedi"; return 1; }
    sleep 10
  done
  while true; do
    if curl -sf -o /dev/null http://127.0.0.1:8085/ready; then
      if python3 scripts/healthcheck.py --timeout 300 > "$DIAG/healthcheck_$label.txt" 2>&1; then
        cat "$DIAG/healthcheck_$label.txt" | tee -a "$DIAG/deploy.log"
        return 0
      fi
    fi
    if [ $(( $(date +%s) - start )) -ge "$READY_TIMEOUT" ]; then
      log "$label: süre doldu. Son durum:"
      curl -s http://127.0.0.1:8085/ready >> "$DIAG/deploy.log" 2>&1; echo >> "$DIAG/deploy.log"
      cat "$DIAG/healthcheck_$label.txt" 2>/dev/null | tee -a "$DIAG/deploy.log"
      return 1
    fi
    sleep 30
  done
}

collect_diag() {
  local f="$1"
  log "tanı logları → $DIAG/"
  $f ps > "$DIAG/ps.txt" 2>&1 || true
  $f logs --no-color --tail=400 > "$DIAG/logs.txt" 2>&1 || true
  grep -E "model_ready|model_failed|worker_loaded|Traceback|Error|SystemExit|Zayıf" "$DIAG/logs.txt" | tail -60 > "$DIAG/errors.txt" || true
  free -h > "$DIAG/mem.txt" 2>&1; nvidia-smi >> "$DIAG/mem.txt" 2>&1 || true
}

# ---------------------------------------------------------------- 1. kod + build (eski sistem çalışırken)
log "git: $BRANCH"
git fetch -q origin || die "git fetch"
git checkout -q "$BRANCH" || die "git checkout"
git pull -q --ff-only origin "$BRANCH" || die "git pull (yerel değişiklik var mı? git status)"
log "commit: $(git log --oneline -1)"

log "build (eski sistem çalışmaya devam ediyor)"
$MULTI build >> "$DIAG/build.log" 2>&1 || die "build başarısız — $DIAG/build.log (eski sistem çalışıyor, dokunulmadı)"
$MULTI pull -q redis >> "$DIAG/build.log" 2>&1 || die "redis image çekilemedi"

# ---------------------------------------------------------------- ön kontrol (eski sistem hâlâ çalışırken)
# Prod'da zayıf/eksik sırla uygulama başlamaz → yeni VE yedek düzen açılamaz. Kesintiden önce yakala.
python3 - <<'PYEOF' || die "ön kontrol başarısız — .env'i düzeltin (eski sistem çalışıyor, dokunulmadı)"
import re, sys
env = {}
for line in open(".env", encoding="utf-8"):
    m = re.match(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$", line)
    if m:
        v = re.sub(r"\s+#.*$", "", m.group(2)).strip().strip('"').strip("'")
        env[m.group(1)] = v
weak = {"", "admin123", "change-me", "change-me-in-production", "dev-change-me", "changeme", "password", "secret"}
bad = []
if len(env.get("API_KEY_PEPPER", "")) < 32: bad.append("API_KEY_PEPPER (en az 32 karakter: openssl rand -hex 32)")
if env.get("CMS_ENABLED", "1") not in ("0", "false", "no"):
    if len(env.get("JWT_SECRET", "")) < 32 or env.get("JWT_SECRET") in weak: bad.append("JWT_SECRET (en az 32 karakter)")
    if len(env.get("CMS_ADMIN_PASSWORD", "")) < 12 or env.get("CMS_ADMIN_PASSWORD") in weak: bad.append("CMS_ADMIN_PASSWORD (en az 12 karakter)")
if not env.get("MONGO_URI"): bad.append("MONGO_URI")
if bad:
    print("Eksik/zayıf: " + "; ".join(bad)); sys.exit(1)
print("sırlar: tamam")
PYEOF
command -v nvidia-smi >/dev/null && nvidia-smi -L >> "$DIAG/deploy.log" 2>&1 || die "GPU görünmüyor (nvidia-smi)"

# ---------------------------------------------------------------- 2. geçiş
if [ "$MODE" = "single" ]; then
  log "MODE=single: yedek düzen kuruluyor"
  $MULTI down --remove-orphans >> "$DIAG/deploy.log" 2>&1 || true
  $SINGLE up -d --remove-orphans >> "$DIAG/deploy.log" 2>&1 || die "single up"
  wait_healthy single && { log "TAMAM: yedek düzen (tek konteyner) canlıda, 10/10 model sağlıklı"; exit 0; }
  collect_diag "$SINGLE"; die "yedek düzen de sağlıklı açılmadı — $DIAG/errors.txt"
fi

log "eski sistem durduruluyor (volume'lar korunur)"
$SINGLE down --remove-orphans >> "$DIAG/deploy.log" 2>&1 || true
log "yeni düzen başlatılıyor: gateway + worker-gpu + worker-cpu + redis"
$MULTI up -d --remove-orphans >> "$DIAG/deploy.log" 2>&1
up_rc=$?

if [ $up_rc -eq 0 ] && wait_healthy multi; then
  log "TAMAM: yeni düzen canlıda, 10/10 model sağlıklı"
  $MULTI ps | tee -a "$DIAG/deploy.log"
  exit 0
fi

# ---------------------------------------------------------------- 3. geri dönüş
collect_diag "$MULTI"
log "yeni düzen sağlıklı açılmadı — ilk hatalar:"
head -20 "$DIAG/errors.txt" | tee -a "$DIAG/deploy.log"
if [ "${NO_ROLLBACK:-0}" = 1 ]; then
  die "NO_ROLLBACK=1 — sistem bu haliyle bırakıldı"
fi
log "GERİ DÖNÜŞ: yedek düzene (tek konteyner, her model ayrı süreç) geçiliyor"
$MULTI down --remove-orphans >> "$DIAG/deploy.log" 2>&1 || true
$SINGLE up -d --remove-orphans >> "$DIAG/deploy.log" 2>&1 || die "yedek düzen başlatılamadı"
if wait_healthy single; then
  log "GERİ DÖNÜŞ TAMAM: yedek düzen canlıda, 10/10 model sağlıklı. Yeni düzenin hatası: $DIAG/errors.txt"
  exit 2
fi
collect_diag "$SINGLE"
die "yedek düzen de sağlıklı değil — $DIAG/errors.txt"
