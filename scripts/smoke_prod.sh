#!/bin/bash
#
# Smoke Test Script for Hippique Orchestrator in Production
#
# This script performs basic health checks against the live production service.
# It verifies that:
#   - Key UI and API endpoints are up and returning the correct content type.
#   - Legacy routes correctly redirect.
#   - The protected /schedule endpoint enforces API key authentication.
#
# Pre-requisites:
#   - `curl` and `jq` must be installed.
#   - The `HIPPIQUE_INTERNAL_API_KEY` environment variable must be set to test
#     the authenticated endpoint.

# --- Configuration ---
set -e # Exit immediately if a command exits with a non-zero status.
TARGET_URL="https://hippique-orchestrator-1084663881709.europe-west1.run.app"
TODAY_DATE=$(date +%F)
FAIL_COUNT=0
OK_COUNT=0

# --- Helper Functions ---
log_check() {
    local message=$1
    echo -n "[..] $message"
}

log_ok() {
    local message=$1
    echo -e "\r[\033[0;32mOK\033[0m] $message"
    ((OK_COUNT++))
}

log_fail() {
    local message=$1
    echo -e "\r[\033[0;31mFAIL\033[0m] $message"
    ((FAIL_COUNT++))
}

# --- Pre-flight Checks ---
if ! command -v curl &> /dev/null; then
    echo "Error: curl is not installed." >&2
    exit 1
fi
if ! command -v jq &> /dev/null; then
    echo "Error: jq is not installed." >&2
    exit 1
fi

if [ -z "$HIPPIQUE_INTERNAL_API_KEY" ]; then
    echo -e "[\033[0;33mWARN\033[0m] HIPPIQUE_INTERNAL_API_KEY is not set. Skipping authenticated /schedule test."
fi

echo "--- Running Smoke Tests against: $TARGET_URL ---"

# --- Test Cases ---

# 1. Test UI Endpoint
log_check "GET /pronostics (UI)"
UI_RESPONSE=$(curl -s -o /dev/null -w "%{http_code}:%{content_type}" "$TARGET_URL/pronostics")
if [[ "$UI_RESPONSE" == "200:text/html"* ]]; then
    log_ok "GET /pronostics: 200 text/html"
else
    log_fail "GET /pronostics: Expected 200 text/html, got $UI_RESPONSE"
fi

# 2. Test API Endpoint
log_check "GET /api/pronostics (API)"
API_RESPONSE=$(curl -s -o /dev/null -w "%{http_code}:%{content_type}" "$TARGET_URL/api/pronostics?date=$TODAY_DATE")
if [[ "$API_RESPONSE" == "200:application/json"* ]]; then
    # Additionally check for a key field in the JSON
    API_BODY=$(curl -s "$TARGET_URL/api/pronostics?date=$TODAY_DATE")
    if echo "$API_BODY" | jq -e '.ok == true' > /dev/null; then
        log_ok "GET /api/pronostics: 200 application/json with 'ok:true'"
    else
        log_fail "GET /api/pronostics: 200 OK but JSON body is invalid or missing 'ok:true'"
    fi
else
    log_fail "GET /api/pronostics: Expected 200 application/json, got $API_RESPONSE"
fi

# 3. Test Legacy Redirects
log_check "GET /pronostics/ui (Legacy Redirect)"
LEGACY_UI_RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" -L "$TARGET_URL/pronostics/ui")
# Following redirects, the final code should be 200
if [[ "$LEGACY_UI_RESPONSE" == "200" ]]; then
    log_ok "GET /pronostics/ui: Redirects successfully"
else
    log_fail "GET /pronostics/ui: Expected redirect, final code was $LEGACY_UI_RESPONSE"
fi

# 4. Test /schedule without API key
log_check "POST /schedule (no key)"
NO_KEY_RESPONSE_CODE=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$TARGET_URL/schedule" \
    -H "Content-Type: application/json" \
    -d '{"dry_run": true}')
if [[ "$NO_KEY_RESPONSE_CODE" == "403" || "$NO_KEY_RESPONSE_CODE" == "401" ]]; then
    log_ok "POST /schedule (no key): $NO_KEY_RESPONSE_CODE Forbidden"
else
    log_fail "POST /schedule (no key): Expected 401/403, got $NO_KEY_RESPONSE_CODE"
fi

# 5. Test /schedule with API key (if set)
if [ -n "$HIPPIQUE_INTERNAL_API_KEY" ]; then
    log_check "POST /schedule (with key)"
    WITH_KEY_RESPONSE_CODE=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$TARGET_URL/schedule" \
        -H "Content-Type: application/json" \
        -H "X-API-KEY: $HIPPIQUE_INTERNAL_API_KEY" \
        -d '{"dry_run": true, "date": "'$TODAY_DATE'"}')
    
    if [[ "$WITH_KEY_RESPONSE_CODE" == "200" ]]; then
        log_ok "POST /schedule (with key): 200 OK"
    else
        log_fail "POST /schedule (with key): Expected 200, got $WITH_KEY_RESPONSE_CODE"
    fi
fi

# --- Summary ---
echo "--- Smoke Tests Complete ---"
if [ "$FAIL_COUNT" -gt 0 ]; then
    echo -e "\n\033[0;31mResult: $FAIL_COUNT failed, $OK_COUNT passed.\033[0m"
    exit 1
else
    echo -e "\n\033[0;32mResult: All $OK_COUNT smoke tests passed.\033[0m"
fi
