#!/bin/bash
#
# Smoke Test Script for Hippique Orchestrator
#
# Usage:
#   export APP_URL="https://your-app-url.a.run.app"
#   export HIPPIQUE_INTERNAL_API_KEY="your-secret-key" # Optional, for auth tests
#   bash scripts/smoke_prod.sh

set -e

# --- Configuration & Colors ---
GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# --- Check Prerequisites ---
if [ -z "$APP_URL" ]; then
    echo -e "${RED}ERROR: APP_URL environment variable is not set. Exiting.${NC}"
    exit 1
fi

echo "Running smoke tests against: $APP_URL"
echo "-----------------------------------------------------"

# --- Test Runner Function ---
# Args:
#   $1: Test description
#   $2: Command to execute
#   $3: Expected result (e.g., "200", "true", "403")
run_test() {
    local description="$1"
    local command="$2"
    local expected="$3"
    
    printf "🧪 Running test: %-50s" "$description"
    
    # Execute the command and capture its output
    local result
    result=$(eval "$command")
    
    if [ "$result" == "$expected" ]; then
        echo -e "[${GREEN}OK${NC}]"
    else
        echo -e "[${RED}FAIL${NC}]"
        echo -e "  └─ Expected: '$expected', but got: '$result'"
        exit 1
    fi
}

# --- Test Cases ---

# 1. Health Check
run_test "Health endpoint returns 200" \
         "curl -s -o /dev/null -w '%{http_code}' '$APP_URL/health'" \
         "200"

# 2. UI Check
run_test "UI page contains correct title" \
         "curl -sL '$APP_URL/pronostics' | grep -q '<title>Hippique Orchestrator - Pronostics' && echo 'true'" \
         "true"

# 3. Public API Check
# Requires jq to be installed
if ! command -v jq &> /dev/null; then
    echo "jq could not be found, skipping JSON validation test."
else
    run_test "Public API returns ok:true" \
             "curl -sL '$APP_URL/api/pronostics' | jq '.ok'" \
             "true"
fi

# 4. Schedule Endpoint (Auth Failure)
run_test "/schedule requires auth (403)" \
         "curl -s -o /dev/null -w '%{http_code}' -X POST '$APP_URL/schedule'" \
         "403"

# 5. Schedule Endpoint (Auth Success)
if [ -z "$HIPPIQUE_INTERNAL_API_KEY" ]; then
    echo "⏭️  Skipping /schedule auth success test: HIPPIQUE_INTERNAL_API_KEY is not set."
else
    # Use a dummy payload for the dry-run test
    run_test "/schedule with API key works (200)" \
             "curl -s -o /dev/null -w '%{http_code}' -X POST -H 'X-API-KEY: $HIPPIQUE_INTERNAL_API_KEY' -H 'Content-Type: application/json' --data '{\"dry_run\": true}' '$APP_URL/schedule'" \
             "200"
fi

echo "-----------------------------------------------------"
echo -e "${GREEN}✅ Smoke tests passed successfully.${NC}"
exit 0
