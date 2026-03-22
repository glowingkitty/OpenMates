#!/bin/sh
#
# backend/upload/vault/wait-for-vault.sh
#
# Polls for the Vault API token written by vault-setup before starting uvicorn.
# Mirrors the pattern used in backend/core/api/wait-for-vault.sh.
#
# vault-setup writes /app/data/api.token; docker-compose mounts vault-setup-data
# at /vault-data in app-uploads, so the file appears at /vault-data/api.token.

echo "Waiting for Vault API token to be ready..."

MAX_ATTEMPTS=30
ATTEMPT=0
TOKEN_FILE="/vault-data/api.token"

while [ $ATTEMPT -lt $MAX_ATTEMPTS ]; do
    ATTEMPT=$((ATTEMPT + 1))
    echo "Checking for API token file (attempt $ATTEMPT/$MAX_ATTEMPTS)..."
    if [ -f "$TOKEN_FILE" ]; then
        echo "API token file found at $TOKEN_FILE"
        FIRST_CHARS=$(cut -c 1-4 < "$TOKEN_FILE")
        echo "API token loaded. Token starts with: $FIRST_CHARS..."
        break
    else
        echo "API token file not found yet, waiting..."
        ls -la /vault-data/ 2>/dev/null || echo "Cannot list /vault-data/ directory"
        sleep 2
    fi
done

if [ $ATTEMPT -ge $MAX_ATTEMPTS ]; then
    echo "ERROR: API token file not found after $MAX_ATTEMPTS attempts."
    echo "Ensure vault-setup completed successfully before starting app-uploads."
    exit 1
fi

# Start the uploads FastAPI app
echo "Starting uploads API server..."
exec uvicorn backend.upload.main:app \
    --host 0.0.0.0 \
    --port "${UPLOADS_APP_INTERNAL_PORT:-8000}" \
    --proxy-headers \
    --forwarded-allow-ips='*' \
    --no-use-colors
