#!/usr/bin/env bash
# DiagVoice yük testi — kademeleri sırayla çalıştırır.
#
#   loadtest/run.sh                       # sadece planı gösterir (istek atmaz)
#   loadtest/run.sh --go                  # tüm planı çalıştırır
#   loadtest/run.sh --go --from fused_50  # bu kademeden devam eder
#   loadtest/run.sh --go --only "fused_1 fused_10"
#
# Ortam: BASE_URL (varsayılan https://aiapi.diagvoice.com), COOLDOWN (sn, varsayılan 60),
#        RECOVER_MAX (sn, sunucunun toparlanması için en fazla bekleme, varsayılan 600).
set -euo pipefail

cd "$(dirname "$0")/.."

BASE_URL="${BASE_URL:-https://aiapi.diagvoice.com}"
COOLDOWN="${COOLDOWN:-60}"
RECOVER_MAX="${RECOVER_MAX:-600}"
ORIGIN_IP="${ORIGIN_IP:-}"   # verilirse Cloudflare atlanır, istekler doğrudan sunucuya gider
HOST="${BASE_URL#*://}"; HOST="${HOST%%[/:]*}"
CURL_RESOLVE=()
[ -n "$ORIGIN_IP" ] && CURL_RESOLVE=(--resolve "$HOST:443:$ORIGIN_IP")

PLAN=(
  # 1) Gerçek kullanım: /analyze-fused (STT + tüm modeller)
  fused_1            # tekil istek — referans süre
  fused_10           # 10 eşzamanlı kullanıcı, 3 dk sürekli
  fused_25
  fused_50
  fused_100          # 100 eşzamanlı kullanıcı, 3 dk sürekli
  fused_100_burst    # 100 istek aynı anda
  fused_1000_burst   # 1000 istek aynı anda
  # 2) Kısa GPU işi: /analyze-text-sentiment
  text_1
  text_10
  text_100
  text_1000_burst
  # 3) Model yok, sadece karşılama katmanı (nginx + uvicorn + audit): GET /
  root_1000_burst
  root_5000_burst
  root_10000_burst
  root_25000_burst
  root_50000_burst
)

GO=0; FROM=""; ONLY=""
while [ $# -gt 0 ]; do
  case "$1" in
    --go) GO=1 ;;
    --from) FROM="$2"; shift ;;
    --only) ONLY="$2"; shift ;;
    *) echo "bilinmeyen argüman: $1" >&2; exit 2 ;;
  esac
  shift
done

stages=()
if [ -n "$ONLY" ]; then
  read -r -a stages <<< "$ONLY"
else
  started=$([ -z "$FROM" ] && echo 1 || echo 0)
  for s in "${PLAN[@]}"; do
    [ "$s" = "$FROM" ] && started=1
    [ "$started" = 1 ] && stages+=("$s")
  done
fi
[ ${#stages[@]} -gt 0 ] || { echo "çalıştırılacak kademe yok" >&2; exit 2; }

echo "Hedef: $BASE_URL${ORIGIN_IP:+ (doğrudan $ORIGIN_IP, Cloudflare atlanıyor)}"
echo "Kademeler: ${stages[*]}"
echo "Kademeler arası bekleme: ${COOLDOWN}s (+ sunucu toparlanana kadar, en fazla ${RECOVER_MAX}s)"
if [ "$GO" != 1 ]; then
  echo
  echo "Bu bir kuru çalıştırma; istek atılmadı. Başlatmak için: loadtest/run.sh --go"
  exit 0
fi

command -v k6 >/dev/null || { echo "k6 bulunamadı (https://k6.io/docs/get-started/installation/)" >&2; exit 1; }
RUN_DIR="loadtest/results/$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$RUN_DIR"
echo "Sonuçlar: $RUN_DIR"

# Sunucu sağlıklı mı: GET / art arda 3 kez 200 ve /analyze-text-sentiment 200.
healthy() {
  for _ in 1 2 3; do
    [ "$(curl -s "${CURL_RESOLVE[@]}" -o /dev/null -m 15 -w '%{http_code}' "$BASE_URL/")" = 200 ] || return 1
    sleep 2
  done
  [ "$(curl -s "${CURL_RESOLVE[@]}" -o /dev/null -m 60 -w '%{http_code}' -H 'Content-Type: application/json' \
        -d '{"text":"saglik kontrolu bugun iyiyim"}' "$BASE_URL/analyze-text-sentiment")" = 200 ]  # ASCII: Windows curl UTF-8 göndermiyor
}

wait_healthy() {
  local waited=0
  until healthy; do
    if [ "$waited" -ge "$RECOVER_MAX" ]; then
      echo "!! Sunucu ${RECOVER_MAX}s içinde toparlanmadı. Test durduruldu." | tee -a "$RUN_DIR/run.log"
      exit 3
    fi
    sleep 10; waited=$((waited + 10))
  done
  [ "$waited" -gt 0 ] && echo "   sunucu ${waited}s sonra toparlandı" | tee -a "$RUN_DIR/run.log"
  return 0
}

echo "Başlangıç sağlık kontrolü…"
wait_healthy

for s in "${stages[@]}"; do
  echo "=== $(date -u +%H:%M:%S) $s ===" | tee -a "$RUN_DIR/run.log"
  set +e
  k6 run --quiet -e BASE_URL="$BASE_URL" -e STAGE="$s" -e ORIGIN_IP="$ORIGIN_IP" -e SUMMARY_OUT="$RUN_DIR/$s.json" \
    loadtest/k6/diagvoice.js 2>&1 | tee -a "$RUN_DIR/run.log"
  rc=${PIPESTATUS[0]}
  set -e
  [ "$rc" = 99 ] && echo "   (hata oranı eşiği aşıldı, kademe erken durduruldu)" | tee -a "$RUN_DIR/run.log"
  echo "   bekleniyor ${COOLDOWN}s…"
  sleep "$COOLDOWN"
  wait_healthy
done

echo "Bitti. Özet: $RUN_DIR/run.log"
