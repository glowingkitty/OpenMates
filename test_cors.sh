#!/bin/bash

# CORS Test Script for OpenMates API
# Tests both dev and production environments to compare CORS headers

set -e

DEV_API="https://api.dev.openmates.org"
PROD_API="https://api.openmates.org"
DEV_ORIGIN="https://app.dev.openmates.org"
PROD_ORIGIN="https://openmates.org"

echo "=========================================="
echo "CORS Configuration Test Script"
echo "=========================================="
echo ""

# Function to test OPTIONS preflight
test_options() {
    local api=$1
    local origin=$2
    local path=$3
    local env=$4
    
    echo "--- Testing OPTIONS preflight: $env ---"
    echo "URL: $api$path"
    echo "Origin: $origin"
    echo ""
    
    curl -v -X OPTIONS "$api$path" \
        -H "Origin: $origin" \
        -H "Access-Control-Request-Method: POST" \
        -H "Access-Control-Request-Headers: Content-Type" \
        2>&1 | grep -iE "(< HTTP|< Access-Control|origin)" || echo "No CORS headers found"
    
    echo ""
    echo "--- Full Response Headers ---"
    curl -s -D - -X OPTIONS "$api$path" \
        -H "Origin: $origin" \
        -H "Access-Control-Request-Method: POST" \
        -H "Access-Control-Request-Headers: Content-Type" \
        -o /dev/null
    
    echo ""
    echo "=========================================="
    echo ""
}

# Function to test actual request
test_actual() {
    local api=$1
    local origin=$2
    local path=$3
    local method=$4
    local env=$5
    
    echo "--- Testing $method request: $env ---"
    echo "URL: $api$path"
    echo "Origin: $origin"
    echo ""
    
    if [ "$method" = "GET" ]; then
        curl -v "$api$path" \
            -H "Origin: $origin" \
            2>&1 | grep -iE "(< HTTP|< Access-Control|origin)" || echo "No CORS headers found"
    else
        curl -v -X "$method" "$api$path" \
            -H "Origin: $origin" \
            -H "Content-Type: application/json" \
            -d '{}' \
            2>&1 | grep -iE "(< HTTP|< Access-Control|origin)" || echo "No CORS headers found"
    fi
    
    echo ""
    echo "--- Full Response Headers ---"
    if [ "$method" = "GET" ]; then
        curl -s -D - "$api$path" \
            -H "Origin: $origin" \
            -o /dev/null
    else
        curl -s -D - -X "$method" "$api$path" \
            -H "Origin: $origin" \
            -H "Content-Type: application/json" \
            -d '{}' \
            -o /dev/null
    fi
    
    echo ""
    echo "=========================================="
    echo ""
}

# Test endpoints
ENDPOINTS=(
    "/v1/auth/passkey/assertion/initiate"
    "/v1/settings/server-status"
    "/v1/auth/session"
)

echo "TESTING DEV ENVIRONMENT"
echo "=========================================="
echo ""

for endpoint in "${ENDPOINTS[@]}"; do
    echo "Testing endpoint: $endpoint"
    echo ""
    
    # Test OPTIONS preflight
    test_options "$DEV_API" "$DEV_ORIGIN" "$endpoint" "DEV"
    
    # Test actual GET request (for server-status)
    if [[ "$endpoint" == *"server-status"* ]]; then
        test_actual "$DEV_API" "$DEV_ORIGIN" "$endpoint" "GET" "DEV"
    fi
    
    sleep 1
done

echo ""
echo ""
echo "TESTING PRODUCTION ENVIRONMENT"
echo "=========================================="
echo ""

for endpoint in "${ENDPOINTS[@]}"; do
    echo "Testing endpoint: $endpoint"
    echo ""
    
    # Test OPTIONS preflight
    test_options "$PROD_API" "$PROD_ORIGIN" "$endpoint" "PROD"
    
    # Test actual GET request (for server-status)
    if [[ "$endpoint" == *"server-status"* ]]; then
        test_actual "$PROD_API" "$PROD_ORIGIN" "$endpoint" "GET" "PROD"
    fi
    
    sleep 1
done

echo ""
echo "Test completed!"
echo ""
echo "Key things to check:"
echo "1. OPTIONS requests should return Access-Control-Allow-Origin header"
echo "2. Actual requests should return Access-Control-Allow-Origin header"
echo "3. Headers should match the Origin header sent (not wildcard *)"
echo "4. Access-Control-Allow-Credentials should be 'true' for webapp requests"



















