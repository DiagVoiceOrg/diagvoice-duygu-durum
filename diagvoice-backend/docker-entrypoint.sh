#!/bin/sh
# WORKER_MODE=worker (varsayılan): fusion + worker-gpu + worker-cpu (registry.yaml)
# WORKER_MODE=legacy: eski düzen, her model ayrı süreç (geri dönüş için)
set -eu
MODE="${WORKER_MODE:-worker}"
case "$MODE" in
  worker) CONF=/app/supervisord.worker.conf ;;
  legacy) CONF=/app/supervisord.conf ;;
  *) echo "WORKER_MODE worker|legacy olmalı: $MODE" >&2; exit 1 ;;
esac
echo "diagvoice: WORKER_MODE=$MODE ($CONF)"
exec supervisord -c "$CONF"
