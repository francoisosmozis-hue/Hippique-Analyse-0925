#!/bin/bash

# Exit immediately if a command exits with a non-zero status.
set -e

# Check for required environment variables
if [ -z "$PROD_URL" ]; then
    echo "Error: PROD_URL environment variable is not set."
    exit 1
fi

if [ -z "$HIPPIQUE_INTERNAL_API_KEY" ]; then
    echo "Error: HIPPIQUE_INTERNAL_API_KEY environment variable is not set."
    exit 1
fi

echo "### Running smoke tests on $PROD_URL ###"

# Test /pronostics endpoint
echo -n "Testing /pronostics... "
curl -s -f "$PROD_URL/pronostics" > /dev/null
echo "OK"

# Test /api/pronostics endpoint
echo -n "Testing /api/pronostics... "
curl -s -f "$PROD_URL/api/pronostics?date=$(date +%F)" | jq . > /dev/null
echo "OK"

# Test /schedule endpoint without API key (should fail)
echo -n "Testing /schedule without API key (expecting 403)... "
if curl -s -o /dev/null -w "%{http_code}" "$PROD_URL/schedule" -X POST | grep -q "403"; then
    echo "OK"
else
    echo "Failed! Expected 403, but got a different status code."
    exit 1
fi

# Test /schedule endpoint with API key (should succeed)
echo -n "Testing /schedule with API key... "
if curl -s -f -X POST -H "X-API-KEY: $HIPPIQUE_INTERNAL_API_KEY" "$PROD_URL/schedule" > /dev/null; then
    echo "OK"
else
    echo "Failed! The request with a valid API key failed."
    exit 1
fi

echo "### Smoke tests passed successfully! ###"