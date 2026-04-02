#!/bin/bash
# Docker Cleanup Script for OpenMates
# This script safely cleans up Docker resources without deleting volumes or containers
# It removes: dangling images, unused images, build cache, and unused networks
#
# Runs weekly via cron. When disk usage exceeds 90%, applies aggressive cleanup
# (removes images older than 24h instead of 7 days).

set -e

echo "=========================================="
echo "Docker Cleanup Script"
echo "=========================================="
echo ""

# Show current disk usage
echo "Current Docker disk usage:"
docker system df
echo ""

# Show current disk space
echo "Current disk space:"
df -h / | tail -1
echo ""

# Determine cleanup aggressiveness based on disk usage
DISK_USE_PCT=$(df / | tail -1 | awk '{print $5}' | tr -d '%')
if [ "$DISK_USE_PCT" -ge 90 ]; then
    echo "⚠️  Disk usage at ${DISK_USE_PCT}% — applying AGGRESSIVE cleanup (images >24h)"
    IMAGE_AGE_FILTER="until=24h"
    AGGRESSIVE=true
else
    echo "Disk usage at ${DISK_USE_PCT}% — applying standard cleanup (images >7d)"
    IMAGE_AGE_FILTER="until=168h"
    AGGRESSIVE=false
fi
echo ""

# 1. Remove dangling images (images with <none> tag)
echo "Step 1: Removing dangling images..."
DANGLING_COUNT=$(docker images --filter "dangling=true" -q | wc -l)
if [ "$DANGLING_COUNT" -gt 0 ]; then
    echo "Found $DANGLING_COUNT dangling images"
    docker image prune -f
    echo "✓ Dangling images removed"
else
    echo "No dangling images found"
fi
echo ""

# 2. Remove unused images (not used by any container)
echo "Step 2: Removing unused images..."
echo "This will remove images that are not currently used by any container"
docker image prune -a -f --filter "$IMAGE_AGE_FILTER"
echo "✓ Unused images removed"
echo ""

# 3. Prune build cache
echo "Step 3: Pruning build cache..."
if [ "$AGGRESSIVE" = true ]; then
    # Aggressive: remove all build cache
    docker builder prune -a -f
else
    docker builder prune -f
fi
echo "✓ Build cache pruned"
echo ""

# 3b. Aggressive: also clean stopped containers and unused networks
if [ "$AGGRESSIVE" = true ]; then
    echo "Step 3b: Aggressive cleanup — removing stopped containers..."
    docker container prune -f
    echo "✓ Stopped containers removed"
    echo ""
fi

# 4. Skip network pruning to avoid removing external networks required by docker-compose
# Networks declared as "external: true" in docker-compose can appear unused when no containers
# are running, but they're still required. Manual network cleanup is safer.
echo "Step 4: Skipping network pruning"
echo "Note: Networks are preserved to avoid removing external networks required by docker-compose"
echo "If you need to clean up networks manually, use: docker network prune"
echo ""

# Show final disk usage
echo "=========================================="
echo "Final Docker disk usage:"
docker system df
echo ""

# Show final disk space
echo "Final disk space:"
df -h / | tail -1
echo ""

echo "=========================================="
echo "Cleanup complete!"
echo "=========================================="
echo ""
echo "Note: Volumes and containers were NOT touched."
echo "If you need more space, you can manually review and remove specific unused images."

# Write nightly report for daily meeting consumption
DISK_AFTER=$(df -h / | tail -1 | awk '{print $4}')
DISK_USE_AFTER=$(df / | tail -1 | awk '{print $5}' | tr -d '%')
PYTHONPATH="$(dirname "$0")" python3 -c "
from _nightly_report import write_nightly_report
write_nightly_report(
    job='docker-cleanup',
    status='warning' if ${DISK_USE_AFTER} >= 85 else 'ok',
    summary='Docker cleanup completed (${AGGRESSIVE:-false} mode). Removed dangling images, unused images, and build cache. Free disk: ${DISK_AFTER} (${DISK_USE_AFTER}% used).',
    details={
        'dangling_images_found': ${DANGLING_COUNT},
        'free_disk_after': '${DISK_AFTER}',
        'disk_use_pct_before': ${DISK_USE_PCT},
        'disk_use_pct_after': ${DISK_USE_AFTER},
        'aggressive_mode': '${AGGRESSIVE}' == 'true',
    },
)
"

