#!/bin/sh

echo "Waiting for Vault to be ready..."

# Maximum number of attempts
MAX_ATTEMPTS=30
ATTEMPT=0

# Check for token file
while [ $ATTEMPT -lt $MAX_ATTEMPTS ]; do
    ATTEMPT=$((ATTEMPT+1))
    
    echo "Checking for token file (attempt $ATTEMPT/$MAX_ATTEMPTS)..."
    if [ -f "/vault-data/root.token" ]; then
        echo "Token file found at /vault-data/root.token"
        export VAULT_TOKEN=$(cat /vault-data/root.token)
        FIRST_CHARS=$(echo "$VAULT_TOKEN" | cut -c 1-4)
        echo "Token loaded from file. Token starts with: $FIRST_CHARS..."
        break
    elif [ -f "/vault-data/api.token" ]; then
        echo "Token file found at /vault-data/api.token"
        export VAULT_TOKEN=$(cat /vault-data/api.token)
        FIRST_CHARS=$(echo "$VAULT_TOKEN" | cut -c 1-4)
        echo "Token loaded from file. Token starts with: $FIRST_CHARS..."
        break
    else
        echo "No token file found yet, waiting..."
        ls -la /vault-data/ || echo "Cannot list /vault-data/ directory"
        sleep 2
    fi
done

if [ $ATTEMPT -ge $MAX_ATTEMPTS ]; then
    echo "Failed to find token file after $MAX_ATTEMPTS attempts"
    echo "Using token from environment variable instead"
fi

# Start the API server
echo "Starting API server..."
exec uvicorn main:app --host ${SERVER_HOST:-0.0.0.0} --port ${REST_API_PORT:-8000}
