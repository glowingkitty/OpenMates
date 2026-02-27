#!/bin/sh

echo "Waiting for Vault to be ready..."

# Maximum number of attempts (2s sleep each = 120s total)
MAX_ATTEMPTS=60
ATTEMPT=0

TOKEN_FILE="/vault-data/api.token"
SENTINEL_FILE="/vault-data/token.ready"

# Record this script's start time (Unix seconds).
# vault-setup writes the sentinel with its own timestamp after saving the token.
# We only accept a sentinel whose timestamp is >= our start time, which means
# vault-setup completed *this boot* — not a leftover sentinel from a previous run.
SCRIPT_START=$(date +%s)
echo "Script started at Unix time: $SCRIPT_START"

while [ $ATTEMPT -lt $MAX_ATTEMPTS ]; do
    ATTEMPT=$((ATTEMPT+1))

    echo "Waiting for vault-setup to complete this boot (attempt $ATTEMPT/$MAX_ATTEMPTS)..."

    if [ -f "$SENTINEL_FILE" ]; then
        SENTINEL_TS=$(cat "$SENTINEL_FILE" 2>/dev/null | tr -d '[:space:]')
        if [ -n "$SENTINEL_TS" ] && [ "$SENTINEL_TS" -ge "$SCRIPT_START" ] 2>/dev/null; then
            echo "vault-setup sentinel is fresh (sentinel=$SENTINEL_TS >= start=$SCRIPT_START)"
            if [ -f "$TOKEN_FILE" ]; then
                export VAULT_TOKEN=$(cat "$TOKEN_FILE")
                FIRST_CHARS=$(echo "$VAULT_TOKEN" | cut -c 1-4)
                echo "API token loaded from file. Token starts with: $FIRST_CHARS..."
                break
            else
                echo "ERROR: Sentinel exists but token file missing — vault-setup may have failed."
            fi
        else
            echo "Sentinel exists but is stale (sentinel=$SENTINEL_TS < start=$SCRIPT_START), waiting for this boot's token..."
        fi
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
        echo "WARNING: Using possibly-stale token from file as fallback. Token starts with: $FIRST_CHARS..."
    elif [ -n "$VAULT_TOKEN" ]; then
        echo "WARNING: Using token from environment variable as fallback (not recommended)."
    else
        echo "ERROR: No Vault token available. API will not be able to access secrets."
        echo "Please ensure vault-setup has completed successfully."
    fi
fi

# Start the API server
echo "Starting API server..."
exec uvicorn backend.core.api.main:app --host 0.0.0.0 --port ${REST_API_PORT:-8000} --proxy-headers --forwarded-allow-ips='*'
