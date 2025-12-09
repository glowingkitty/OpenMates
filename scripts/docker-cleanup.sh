#!/bin/bash
# Docker Cleanup Script for OpenMates
# This script safely cleans up Docker resources without deleting volumes or containers
# It removes: dangling images, unused images, build cache, and unused networks

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
echo "Keeping images that are in use by running or stopped containers..."
docker image prune -a -f --filter "until=168h"  # Remove images older than 7 days that are unused
echo "✓ Unused images removed"
echo ""

# 3. Prune build cache
echo "Step 3: Pruning build cache..."
docker builder prune -f
echo "✓ Build cache pruned"
echo ""

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

