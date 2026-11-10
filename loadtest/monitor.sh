#!/usr/bin/env bash
# GPU sunucusunda, test boyunca kaynak kullanımını kaydeder. Ctrl+C ile durdurun.
#
#   cd /opt/api && sudo loadtest/monitor.sh            # çıktı: loadtest/monitor/<zaman>/
#
# Dosyalar:
#   system.csv      zaman, cpu%, load1, ram kullanılan/toplam MB, swap MB, disk boş GB, TCP bağlantı sayıları
#   gpu.csv         nvidia-smi: kullanım %, bellek MB, sıcaklık
#   docker.csv      docker stats (backend konteyneri)
#   events.log      supervisord çıkış/yeniden başlama, OOM, segfault, nginx hata satırları
set -uo pipefail

cd "$(dirname "$0")/.."
INTERVAL="${INTERVAL:-2}"
OUT="loadtest/monitor/$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$OUT"
echo "Kayıt: $OUT (her ${INTERVAL}s)"

echo "ts,cpu_pct,load1,mem_used_mb,mem_total_mb,swap_used_mb,disk_free_gb,tcp_estab_443,tcp_estab_8085,tcp_timewait,listen_overflows" > "$OUT/system.csv"
echo "ts,gpu_util_pct,gpu_mem_used_mb,gpu_mem_total_mb,gpu_temp_c" > "$OUT/gpu.csv"
echo "ts,cpu_pct,mem_usage,net_io,block_io,pids" > "$OUT/docker.csv"

# Olay akışları (arka planda)
docker compose logs -f --since 0s backend 2>&1 \
  | grep --line-buffered -iE "exited|spawned|FATAL|SIGSEGV|core dumped|Traceback|Killed|out of memory|CUDA error|insert failed" \
  | sed -u "s/^/[backend] /" >> "$OUT/events.log" &
P1=$!
tail -n0 -F /var/log/nginx/error.log 2>/dev/null | sed -u "s/^/[nginx] /" >> "$OUT/events.log" &
P2=$!
(dmesg -wT 2>/dev/null || journalctl -kf 2>/dev/null) \
  | grep --line-buffered -iE "oom|killed process|segfault|possible SYN flooding|nf_conntrack" \
  | sed -u "s/^/[kernel] /" >> "$OUT/events.log" &
P3=$!
trap 'kill $P1 $P2 $P3 2>/dev/null; echo; echo "Durduruldu: $OUT"; exit 0' INT TERM

prev=$(awk '/^cpu /{print $2+$3+$4+$5+$6+$7+$8, $5+$6}' /proc/stat)
while true; do
  ts=$(date -u +%H:%M:%S)
  cur=$(awk '/^cpu /{print $2+$3+$4+$5+$6+$7+$8, $5+$6}' /proc/stat)
  cpu=$(echo "$prev $cur" | awk '{dt=$3-$1; di=$4-$2; printf "%.1f", (dt>0 ? 100*(dt-di)/dt : 0)}')
  prev=$cur
  load1=$(cut -d' ' -f1 /proc/loadavg)
  read -r mt mu < <(free -m | awk '/^Mem:/{print $2, $3}')
  su=$(free -m | awk '/^Swap:/{print $3}')
  df_gb=$(df -BG --output=avail / | tail -1 | tr -dc '0-9')
  e443=$(ss -Htn state established '( sport = :443 )' 2>/dev/null | wc -l)
  e8085=$(ss -Htn state established '( sport = :8085 )' 2>/dev/null | wc -l)
  tw=$(ss -Htn state time-wait 2>/dev/null | wc -l)
  ovf=$(nstat -az TcpExtListenOverflows 2>/dev/null | awk '/TcpExtListenOverflows/{print $2}')
  echo "$ts,$cpu,$load1,$mu,$mt,$su,$df_gb,$e443,$e8085,$tw,${ovf:-}" >> "$OUT/system.csv"

  nvidia-smi --query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu --format=csv,noheader,nounits 2>/dev/null \
    | sed "s/ //g; s/^/$ts,/" >> "$OUT/gpu.csv"

  docker stats --no-stream --format '{{.CPUPerc}},{{.MemUsage}},{{.NetIO}},{{.BlockIO}},{{.PIDs}}' \
    "$(docker compose ps -q backend 2>/dev/null)" 2>/dev/null | sed "s/^/$ts,/" >> "$OUT/docker.csv"

  sleep "$INTERVAL"
done
