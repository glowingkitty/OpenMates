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
UNSEAL_KEY_FILE="/vault-data/unseal.key"
VAULT_ADDR="http://vault:8200"

# ---------------------------------------------------------------------------
# try_unseal — attempt to unseal Vault using the saved unseal key.
# ---------------------------------------------------------------------------
try_unseal() {
    if [ ! -f "$UNSEAL_KEY_FILE" ]; then
        return 1
    fi
    UNSEAL_KEY=$(cat "$UNSEAL_KEY_FILE" 2>/dev/null | tr -d '[:space:]')
    if [ -z "$UNSEAL_KEY" ]; then
        return 1
    fi
    echo "Attempting to unseal Vault..."
    UNSEAL_RESP=$(curl -s -X PUT "${VAULT_ADDR}/v1/sys/unseal" \
        -H "Content-Type: application/json" \
        -d "{\"key\": \"${UNSEAL_KEY}\"}" 2>/dev/null)
    if echo "$UNSEAL_RESP" | grep -q '"sealed":false'; then
        echo "Vault unsealed successfully."
        return 0
    fi
    return 1
}

# ---------------------------------------------------------------------------
# verify_vault_unsealed — wait until Vault is unsealed, auto-unseal if needed.
# ---------------------------------------------------------------------------
verify_vault_unsealed() {
    echo "Verifying Vault is unsealed..."
    HEALTH_ATTEMPTS=0
    MAX_HEALTH_ATTEMPTS=90
    UNSEAL_ATTEMPTED=0
    while [ $HEALTH_ATTEMPTS -lt $MAX_HEALTH_ATTEMPTS ]; do
        HEALTH_ATTEMPTS=$((HEALTH_ATTEMPTS+1))
        HEALTH_CODE=$(curl -s -o /dev/null -w "%{http_code}" "${VAULT_ADDR}/v1/sys/health" 2>/dev/null)
        if [ "$HEALTH_CODE" = "200" ]; then
            echo "Vault is unsealed and healthy."
            return 0
        elif [ "$HEALTH_CODE" = "503" ]; then
            if [ $UNSEAL_ATTEMPTED -eq 0 ]; then
                UNSEAL_ATTEMPTED=1
                try_unseal
            else
                echo "Vault is still sealed (attempt $HEALTH_ATTEMPTS/$MAX_HEALTH_ATTEMPTS). Waiting..."
            fi
        else
            echo "Vault not reachable (HTTP $HEALTH_CODE, attempt $HEALTH_ATTEMPTS/$MAX_HEALTH_ATTEMPTS)..."
        fi
        sleep 2
    done
    return 1
}

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

# Verify Vault is unsealed before starting
if ! verify_vault_unsealed; then
    echo "ERROR: Vault never became healthy. Cannot start uploads API."
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
