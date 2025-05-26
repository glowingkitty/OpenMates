#!/bin/sh

echo "Waiting for Vault to be ready..."

# Maximum number of attempts
MAX_ATTEMPTS=30
ATTEMPT=0

# Look only for the API token file - the API service should never use the root token
TOKEN_FILE="/vault-data/api.token"

# Check for token file
while [ $ATTEMPT -lt $MAX_ATTEMPTS ]; do
    ATTEMPT=$((ATTEMPT+1))
    
    echo "Checking for API token file (attempt $ATTEMPT/$MAX_ATTEMPTS)..."
    if [ -f "$TOKEN_FILE" ]; then
        echo "API token file found at $TOKEN_FILE"
        export VAULT_TOKEN=$(cat "$TOKEN_FILE")
        FIRST_CHARS=$(echo "$VAULT_TOKEN" | cut -c 1-4)
        echo "API token loaded from file. Token starts with: $FIRST_CHARS..."
        break
    else
        echo "API token file not found yet, waiting..."
        ls -la /vault-data/ || echo "Cannot list /vault-data/ directory"
        sleep 2
    fi
done

if [ $ATTEMPT -ge $MAX_ATTEMPTS ]; then
    echo "Failed to find API token file after $MAX_ATTEMPTS attempts"
    
    if [ -n "$VAULT_TOKEN" ]; then
        echo "Using token from environment variable instead (not recommended)"
    else
        echo "ERROR: No Vault token available. API will not be able to access secrets."
        echo "Please ensure vault-setup has completed successfully."
    fi
fi

# Start the API server
echo "Starting API server..."
exec uvicorn backend.core.api.main:app --host 0.0.0.0 --port ${REST_API_PORT:-8000} --proxy-headers --forwarded-allow-ips='*'