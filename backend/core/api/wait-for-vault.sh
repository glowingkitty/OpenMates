#!/bin/sh

echo "Waiting for Vault to be ready..."

# Maximum number of attempts (2s sleep each = 120s total)
MAX_ATTEMPTS=60
ATTEMPT=0

TOKEN_FILE="/vault-data/api.token"
SENTINEL_FILE="/vault-data/token.ready"
UNSEAL_KEY_FILE="/vault-data/unseal.key"
VAULT_ADDR="http://vault:8200"

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
#      regardless of when it was written — use it after verifying Vault is unsealed.
#   2. If neither exists yet (first boot), wait for vault-setup to finish.
#   3. If the sentinel exists but the token file is missing, something went
#      wrong — wait briefly then fall back.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# try_unseal — attempt to unseal Vault using the saved unseal key.
# Called when Vault is sealed and vault-setup won't re-run (exit 0).
# ---------------------------------------------------------------------------
try_unseal() {
    if [ ! -f "$UNSEAL_KEY_FILE" ]; then
        echo "No unseal key found at $UNSEAL_KEY_FILE — cannot auto-unseal."
        return 1
    fi
    UNSEAL_KEY=$(cat "$UNSEAL_KEY_FILE" 2>/dev/null | tr -d '[:space:]')
    if [ -z "$UNSEAL_KEY" ]; then
        echo "Unseal key file is empty — cannot auto-unseal."
        return 1
    fi
    echo "Attempting to unseal Vault..."
    UNSEAL_RESP=$(curl -s -X PUT "${VAULT_ADDR}/v1/sys/unseal" \
        -H "Content-Type: application/json" \
        -d "{\"key\": \"${UNSEAL_KEY}\"}" 2>/dev/null)
    if echo "$UNSEAL_RESP" | grep -q '"sealed":false'; then
        echo "Vault unsealed successfully."
        return 0
    else
        echo "Unseal attempt did not succeed: $UNSEAL_RESP"
        return 1
    fi
}

# ---------------------------------------------------------------------------
# verify_vault_unsealed — wait until Vault is actually unsealed before
# starting the API. If sealed, attempts auto-unseal using the saved key.
# Prevents crash-loops when Vault restarts and comes back sealed while
# the token file still exists from a previous boot.
# ---------------------------------------------------------------------------
verify_vault_unsealed() {
    echo "Verifying Vault is unsealed..."
    HEALTH_ATTEMPTS=0
    MAX_HEALTH_ATTEMPTS=90  # 3 minutes (2s each)
    UNSEAL_ATTEMPTED=0
    while [ $HEALTH_ATTEMPTS -lt $MAX_HEALTH_ATTEMPTS ]; do
        HEALTH_ATTEMPTS=$((HEALTH_ATTEMPTS+1))
        HEALTH_CODE=$(curl -s -o /dev/null -w "%{http_code}" "${VAULT_ADDR}/v1/sys/health" 2>/dev/null)
        if [ "$HEALTH_CODE" = "200" ]; then
            echo "Vault is unsealed and healthy."
            return 0
        elif [ "$HEALTH_CODE" = "503" ]; then
            # Vault is sealed — try to unseal it (once)
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

    echo "ERROR: Vault is not healthy after $MAX_HEALTH_ATTEMPTS attempts (last HTTP status: $HEALTH_CODE)."
    return 1
}

# ---------------------------------------------------------------------------
# wait_for_cms — poll CMS (Directus) health endpoint until it responds 200.
# Prevents the API from starting before CMS is ready, which would cause
# DNS resolution failures and empty cache entries during container restarts.
# ---------------------------------------------------------------------------
wait_for_cms() {
    CMS_URL="${CMS_URL:-http://cms:8055}"
    CMS_MAX_ATTEMPTS=30  # 60 seconds (2s each)
    CMS_ATTEMPT=0

    echo "Waiting for CMS to be ready at ${CMS_URL}..."
    while [ $CMS_ATTEMPT -lt $CMS_MAX_ATTEMPTS ]; do
        CMS_ATTEMPT=$((CMS_ATTEMPT+1))
        CMS_CODE=$(curl -sf -o /dev/null -w "%{http_code}" "${CMS_URL}/server/health" 2>/dev/null)
        if [ "$CMS_CODE" = "200" ]; then
            echo "CMS is healthy (HTTP 200)."
            return 0
        fi
        echo "CMS not ready (HTTP $CMS_CODE, attempt $CMS_ATTEMPT/$CMS_MAX_ATTEMPTS)..."
        sleep 2
    done

    echo "WARNING: CMS not healthy after ${CMS_MAX_ATTEMPTS} attempts. Starting API anyway — requests will retry at runtime."
    return 0
}

# ---------------------------------------------------------------------------
# start_api — common function to start the uvicorn API server.
# ---------------------------------------------------------------------------
start_api() {
    wait_for_cms
    echo "Starting API server..."
    # SECURITY: Only trust X-Forwarded-For from Docker bridge network (172.16.0.0/12).
    # Never use '*' — any client could spoof their IP and bypass rate limits.
    exec uvicorn backend.core.api.main:app --host 0.0.0.0 --port ${REST_API_PORT:-8000} --proxy-headers --forwarded-allow-ips="172.16.0.0/12"
}

# Fast path: both files already exist from a previous (successful) boot.
# The token on the persistent volume is still valid — use it after verifying
# Vault is actually unsealed (not just that the file exists).
if [ -f "$SENTINEL_FILE" ] && [ -f "$TOKEN_FILE" ]; then
    SENTINEL_TS=$(cat "$SENTINEL_FILE" 2>/dev/null | tr -d '[:space:]')
    export VAULT_TOKEN=$(cat "$TOKEN_FILE")
    FIRST_CHARS=$(echo "$VAULT_TOKEN" | cut -c 1-4)
    echo "Vault token ready (sentinel=$SENTINEL_TS). Token starts with: $FIRST_CHARS..."

    if ! verify_vault_unsealed; then
        echo "ERROR: Vault never became healthy. Cannot start API."
        exit 1
    fi

    start_api
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

# Verify Vault is unsealed before starting (covers both slow path and fallback)
if ! verify_vault_unsealed; then
    echo "ERROR: Vault never became healthy. Cannot start API."
    exit 1
fi

# Start the API server
start_api
