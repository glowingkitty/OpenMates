#!/bin/bash
# Safe, bounded Docker cache cleanup for the OpenMates dev host.
#
# This script deliberately never prunes volumes, containers, or networks.
# Every Docker call is time-bounded so a full/unhealthy daemon cannot prevent
# later scheduled runs from trying again.

set -uo pipefail

LOCK_FILE="${OPENMATES_DOCKER_CLEANUP_LOCK:-/tmp/openmates-docker-cleanup.lock}"
DOCKER_TIMEOUT_SECONDS="${OPENMATES_DOCKER_CLEANUP_TIMEOUT_SECONDS:-300}"
BUILD_CACHE_KEEP="${OPENMATES_DOCKER_BUILD_CACHE_KEEP:-8GB}"
AGGRESSIVE_DISK_PERCENT="${OPENMATES_DOCKER_AGGRESSIVE_PERCENT:-85}"
MAX_LOG_BYTES="${OPENMATES_DOCKER_CLEANUP_MAX_LOG_BYTES:-10485760}"
CLEANUP_LOG="${OPENMATES_DOCKER_CLEANUP_LOG:-}"

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
    echo "Docker cleanup already running; skipping overlapping invocation."
    exit 0
fi

# Cron opens its append target before starting this script. Truncating that
# same inode is safe and bounds the log without breaking the active descriptor.
if [ -n "$CLEANUP_LOG" ] && [ -f "$CLEANUP_LOG" ]; then
    LOG_BYTES=$(stat -c '%s' "$CLEANUP_LOG" 2>/dev/null || echo 0)
    if [ "$LOG_BYTES" -gt "$MAX_LOG_BYTES" ]; then
        : > "$CLEANUP_LOG"
    fi
fi

run_docker() {
    local label="$1"
    shift
    echo "$label"
    if ! timeout "${DOCKER_TIMEOUT_SECONDS}s" docker "$@"; then
        echo "WARNING: $label failed or timed out; the next scheduled run will retry."
        return 1
    fi
}

DISK_USE_PCT=$(df -P / | awk 'NR == 2 {gsub(/%/, "", $5); print $5}')
DISK_FREE_BEFORE=$(df -hP / | awk 'NR == 2 {print $4}')
echo "Docker cleanup starting: ${DISK_USE_PCT}% used, ${DISK_FREE_BEFORE} free."

# Diagnostic only: never let accounting block cleanup.
run_docker "Current Docker usage:" system df || true

if [ "$DISK_USE_PCT" -ge "$AGGRESSIVE_DISK_PERCENT" ]; then
    AGGRESSIVE=true
    IMAGE_AGE_FILTER="until=24h"
    run_docker "Pruning all unused BuildKit cache (disk pressure mode):" builder prune -a -f || true
else
    AGGRESSIVE=false
    IMAGE_AGE_FILTER="until=168h"
    run_docker "Capping unused BuildKit cache at ${BUILD_CACHE_KEEP}:" builder prune -a -f --keep-storage "$BUILD_CACHE_KEEP" || true
fi

# image prune -a removes only images unused by every container. A minimum age
# avoids racing a just-finished build. No container or volume prune is allowed.
run_docker "Pruning unused images older than ${IMAGE_AGE_FILTER#until=}:" image prune -a -f --filter "$IMAGE_AGE_FILTER" || true

DISK_USE_AFTER=$(df -P / | awk 'NR == 2 {gsub(/%/, "", $5); print $5}')
DISK_FREE_AFTER=$(df -hP / | awk 'NR == 2 {print $4}')
echo "Docker cleanup complete: ${DISK_USE_AFTER}% used, ${DISK_FREE_AFTER} free."
echo "Preserved all Docker volumes, containers, and networks."

# Keep the daily-meeting signal, but never turn a reporting problem into a
# cleanup failure.
PYTHONPATH="$(dirname "$0")" python3 -c "
from _nightly_report import write_nightly_report
write_nightly_report(
    job='docker-cleanup',
    status='warning' if ${DISK_USE_AFTER} >= ${AGGRESSIVE_DISK_PERCENT} else 'ok',
    summary='Safe Docker cleanup completed. Free disk: ${DISK_FREE_AFTER} (${DISK_USE_AFTER}% used).',
    details={
        'free_disk_before': '${DISK_FREE_BEFORE}',
        'free_disk_after': '${DISK_FREE_AFTER}',
        'disk_use_pct_before': ${DISK_USE_PCT},
        'disk_use_pct_after': ${DISK_USE_AFTER},
        'aggressive_mode': '${AGGRESSIVE}' == 'true',
        'volumes_pruned': False,
        'containers_pruned': False,
    },
)
" || echo "WARNING: cleanup report write failed."
