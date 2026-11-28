#!/bin/bash
# Safe, bounded Docker cache cleanup for the OpenMates dev host.
#
# This script deliberately never prunes volumes, containers, or networks.
# Every Docker call is time-bounded so a full/unhealthy daemon cannot prevent
# later scheduled runs from trying again.

set -uo pipefail

# After cutover every scheduled/manual cleanup joins the elected host owner.
DISK_REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if python3 "$DISK_REPO_ROOT/scripts/disk_coordinator.py" configured-check --repository "$DISK_REPO_ROOT"; then
    DISK_CONFIGURATION_STATUS=0
else
    DISK_CONFIGURATION_STATUS=$?
fi
if [ "$DISK_CONFIGURATION_STATUS" -eq 0 ]; then
    if ! python3 "$DISK_REPO_ROOT/scripts/disk_coordinator.py" owner-check; then
        exec python3 "$DISK_REPO_ROOT/scripts/disk_coordinator.py" maintenance --repository "$DISK_REPO_ROOT" --kind docker
    fi
elif [ "$DISK_CONFIGURATION_STATUS" -ne 3 ]; then
    echo "Disk coordinator state is uncertain; refusing independent cleanup." >&2
    exit 1
fi

LOCK_FILE="${OPENMATES_DOCKER_CLEANUP_LOCK:-/tmp/openmates-docker-cleanup.lock}"
DOCKER_TIMEOUT_SECONDS="${OPENMATES_DOCKER_CLEANUP_TIMEOUT_SECONDS:-300}"
# Images and BuildKit cache share one budget (TASK-7646, owner decision 2026-11-17):
# the build cache keeps what the budget leaves after the images, 80% of it from
# the pressure mark on. Cleanup starts at 75%, well before the 10 GiB floor.
DOCKER_BUDGET_MB="${OPENMATES_DOCKER_BUDGET_MB:-20000}"
AGGRESSIVE_DISK_PERCENT="${OPENMATES_DOCKER_AGGRESSIVE_PERCENT:-75}"
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

# Image bytes as Docker reports them ("9.493GB"); unknown counts as 0, so the cap
# then falls back to the whole budget for the build cache.
IMAGES_MB=$(timeout 60s docker system df --format '{{.Type}}={{.Size}}' 2>/dev/null | python3 -c '
import re, sys
units = {"B": 1e-6, "KB": 1e-3, "MB": 1, "GB": 1e3, "TB": 1e6}
for line in sys.stdin:
    kind, _, size = line.strip().partition("=")
    match = re.match(r"([\d.]+)\s*([KMGT]?B)$", size)
    if kind == "Images" and match:
        print(int(float(match.group(1)) * units[match.group(2)]))
' 2>/dev/null || true)
IMAGES_MB="${IMAGES_MB:-0}"

if [ "$DISK_USE_PCT" -ge "$AGGRESSIVE_DISK_PERCENT" ]; then
    AGGRESSIVE=true
    # Keep recent build handoff images, but don't block the host all day on
    # dangling intermediate images. Tagged rollback images remain protected.
    IMAGE_AGE_FILTER="until=1h"
    BUDGET_MB=$((DOCKER_BUDGET_MB * 80 / 100))
else
    AGGRESSIVE=false
    IMAGE_AGE_FILTER="until=168h"
    BUDGET_MB="$DOCKER_BUDGET_MB"
fi
CACHE_KEEP_MB=$((BUDGET_MB - IMAGES_MB))
if [ "$CACHE_KEEP_MB" -lt 0 ]; then
    CACHE_KEEP_MB=0
fi
# Below the cleanup target (resource_budget.CLEANUP_TARGET_FREE, 40 GiB) the shared
# image budget no longer protects build cache: a chat once had to prune 8 GB of it by
# hand to get CI moving (TASK-5181). Cache of a running build is in use and stays.
CLEANUP_TARGET_GIB="${OPENMATES_DISK_CLEANUP_TARGET_GIB:-40}"
DISK_FREE_GIB=$(df -P -B1G / | awk 'NR == 2 {print $4}')
DISK_FREE_GIB="${DISK_FREE_GIB:-0}"
EMERGENCY=false
if [ "$DISK_FREE_GIB" -lt "${CLEANUP_TARGET_GIB%.*}" ]; then
    EMERGENCY=true
    CACHE_KEEP_MB=0
fi
run_docker "Capping unused BuildKit cache at ${CACHE_KEEP_MB}MB (budget ${BUDGET_MB}MB minus ${IMAGES_MB}MB of images):" \
    builder prune -a -f --keep-storage "${CACHE_KEEP_MB}MB" || true

# Unused tags may pin rollback images. Retain every tagged image and only prune
# aged dangling images; Docker also protects container-referenced images.
run_docker "Pruning dangling images older than ${IMAGE_AGE_FILTER#until=}:" image prune -f --filter "$IMAGE_AGE_FILTER" || true

# Tagged images no container uses (old builds, rollback tags) used to be kept
# forever, so images grew past their budget while the disk filled (TASK-5181).
# Over the image budget or from UNUSED_IMAGE_DISK_PERCENT used, remove unused
# images older than a day; images of running or stopped containers stay.
UNUSED_IMAGE_DISK_PERCENT="${OPENMATES_DOCKER_UNUSED_IMAGE_PERCENT:-85}"
if [ "$IMAGES_MB" -gt "$BUDGET_MB" ] || [ "$DISK_USE_PCT" -ge "$UNUSED_IMAGE_DISK_PERCENT" ] || [ "$EMERGENCY" = true ]; then
    run_docker "Pruning unused images older than 24h (images ${IMAGES_MB}MB, budget ${BUDGET_MB}MB, disk ${DISK_USE_PCT}%):" \
        image prune -a -f --filter "until=24h" || true
fi

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
