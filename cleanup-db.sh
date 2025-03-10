#!/bin/bash

set -e

echo "===== OpenMates Database Cleanup ====="
echo "WARNING: This will delete all database data in the CMS database."
echo "This should be used when you encounter database version incompatibility issues."
echo ""
read -p "Are you sure you want to proceed? (y/N): " confirmation

if [ "$confirmation" != "y" ] && [ "$confirmation" != "Y" ]; then
  echo "Cleanup cancelled."
  exit 0
fi

echo "Stopping all containers..."
docker compose -f backend/core/core.docker-compose.yml down

echo "Removing database volumes..."
docker volume rm openmates-core_cms-data openmates-postgres-data 2>/dev/null || true

echo "Cleanup completed. You can now run start-server.sh to initialize a fresh database."
