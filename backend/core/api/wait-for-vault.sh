#!/bin/sh

echo "Waiting for Vault to be ready..."

# Maximum number of attempts (2s sleep each = 120s total)
MAX_ATTEMPTS=60
ATTEMPT=0

TOKEN_FILE="/vault-data/api.token"
SENTINEL_FILE="/vault-data/token.ready"

# ---------------------------------------------------------------------------
# Vault token handoff strategy
# ---------------------------------------------------------------------------
# vault-setup is a one-shot container (restart: on-failure). On a clean
# docker-compose-up it runs once, saves the API token to $TOKEN_FILE, writes
# a timestamp into $SENTINEL_FILE, and exits 0.
#
# When only the api container is rebuilt/restarted later (e.g. after a code
# change), vault-setup does NOT re-run — it already exited successfully and
# Docker will not restart it. The token and sentinel from the original boot
# are still on the shared persistent volume and are perfectly valid.
#
# Strategy:
#   1. If both the sentinel and the token file exist, the token is usable
#      regardless of when it was written — use it immediately.
#   2. If neither exists yet (first boot), wait for vault-setup to finish.
#   3. If the sentinel exists but the token file is missing, something went
#      wrong — wait briefly then fall back.
# ---------------------------------------------------------------------------

# Fast path: both files already exist from a previous (successful) boot.
# The token on the persistent volume is still valid — use it immediately
# without waiting for vault-setup to re-run (it won't).
if [ -f "$SENTINEL_FILE" ] && [ -f "$TOKEN_FILE" ]; then
    SENTINEL_TS=$(cat "$SENTINEL_FILE" 2>/dev/null | tr -d '[:space:]')
    export VAULT_TOKEN=$(cat "$TOKEN_FILE")
    FIRST_CHARS=$(echo "$VAULT_TOKEN" | cut -c 1-4)
    echo "Vault token ready (sentinel=$SENTINEL_TS). Token starts with: $FIRST_CHARS..."
    echo "Starting API server..."
    # SECURITY: Only trust X-Forwarded-For from Docker bridge network (172.16.0.0/12).
    # Never use '*' — any client could spoof their IP and bypass rate limits.
    exec uvicorn backend.core.api.main:app --host 0.0.0.0 --port ${REST_API_PORT:-8000} --proxy-headers --forwarded-allow-ips="172.16.0.0/12"
fi

# Slow path: first boot or broken state — wait for vault-setup to complete.
echo "Token or sentinel not found yet. Waiting for vault-setup to complete..."

while [ $ATTEMPT -lt $MAX_ATTEMPTS ]; do
    ATTEMPT=$((ATTEMPT+1))

    echo "Waiting for vault-setup to complete (attempt $ATTEMPT/$MAX_ATTEMPTS)..."

    if [ -f "$SENTINEL_FILE" ] && [ -f "$TOKEN_FILE" ]; then
        SENTINEL_TS=$(cat "$SENTINEL_FILE" 2>/dev/null | tr -d '[:space:]')
        export VAULT_TOKEN=$(cat "$TOKEN_FILE")
        FIRST_CHARS=$(echo "$VAULT_TOKEN" | cut -c 1-4)
        echo "vault-setup completed (sentinel=$SENTINEL_TS). Token starts with: $FIRST_CHARS..."
        break
    elif [ -f "$SENTINEL_FILE" ]; then
        echo "Sentinel exists (timestamp=$(cat "$SENTINEL_FILE" 2>/dev/null)) but token file is missing — vault-setup may have failed."
    else
        echo "Sentinel not yet written by vault-setup, waiting..."
    fi

    sleep 2
done

if [ $ATTEMPT -ge $MAX_ATTEMPTS ]; then
    echo "vault-setup did not complete within timeout."
    # Last-resort fallback: use whatever token is in the file, even if stale.
    # This keeps the API from being completely dead if vault-setup takes unusually long.
    if [ -f "$TOKEN_FILE" ]; then
        export VAULT_TOKEN=$(cat "$TOKEN_FILE")
        FIRST_CHARS=$(echo "$VAULT_TOKEN" | cut -c 1-4)
        echo "WARNING: Using token from file as fallback. Token starts with: $FIRST_CHARS..."
    elif [ -n "$VAULT_TOKEN" ]; then
        echo "WARNING: Using token from environment variable as fallback (not recommended)."
    else
        echo "ERROR: No Vault token available. API will not be able to access secrets."
        echo "Please ensure vault-setup has completed successfully."
    fi
fi

# Start the API server
echo "Starting API server..."
# SECURITY: Only trust X-Forwarded-For from Docker bridge network (172.16.0.0/12).
# Never use '*' — any client could spoof their IP and bypass rate limits.
exec uvicorn backend.core.api.main:app --host 0.0.0.0 --port ${REST_API_PORT:-8000} --proxy-headers --forwarded-allow-ips="172.16.0.0/12"
