#!/bin/bash
# scripts/smoke_prod.sh

# --- Configuration ---
SERVICE_URL="$1"
API_KEY="${HIPPIQUE_INTERNAL_API_KEY}" # Read from environment variable

# --- ANSI Colors for Output ---
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[0;33m'
NC='\033[0m' # No Color

# --- Helper Functions ---
function run_test {
    local name="$1"
    local command="$2"
    local expected_status="$3"
    local allow_other_status="${4:-false}" # New parameter for allowing other status codes

    echo -e "${YELLOW}--- Running Test: ${name} ---
${NC}"
    echo -e "Command: ${command}"

    # Execute command, capture status code and output
    HTTP_STATUS=$(eval "$command" | head -n 1 | awk '{print $2}')
    OUTPUT=$(eval "$command" | tail -n +2)

    if [[ "$HTTP_STATUS" == "$expected_status" ]]; then
        echo -e "${GREEN}SUCCESS: ${name} returned ${HTTP_STATUS} (expected ${expected_status}).${NC}"
        RESULT=0
    elif [[ "$allow_other_status" == "true" ]]; then
        echo -e "${GREEN}SUCCESS: ${name} returned ${HTTP_STATUS} (expected ${expected_status} or other allowed status).${NC}"
        RESULT=0
    else
        echo -e "${RED}FAILURE: ${name} returned ${HTTP_STATUS} (expected ${expected_status}).${NC}"
        echo -e "${RED}Output:${NC}\n${OUTPUT}"
        RESULT=1
    fi
    echo ""
    return $RESULT
}

# --- Main Logic ---

if [ -z "$SERVICE_URL" ]; then
    echo -e "${RED}Error: SERVICE_URL not provided.${NC}"
    echo "Usage: $0 <YOUR_CLOUD_RUN_SERVICE_URL>"
    exit 1
fi

if [ -z "$API_KEY" ]; then
    echo -e "${YELLOW}Warning: HIPPIQUE_INTERNAL_API_KEY is not set. Skipping authenticated tests.${NC}"
    SKIP_AUTH_TESTS=true
else
    SKIP_AUTH_TESTS=false
fi

echo -e "${GREEN}Starting Smoke Tests for ${SERVICE_URL}${NC}\n"

ALL_TESTS_PASSED=true

# 1. Test GET /pronostics (UI Frontend)
run_test "UI Frontend /pronostics" \
         "curl -s -o /dev/null -w '%{http_code} %{content_type}' '${SERVICE_URL}/pronostics'" \
         "200"
if [ $? -ne 0 ]; then ALL_TESTS_PASSED=false; fi

# 2. Test GET /api/pronostics (Main API)
run_test "API /api/pronostics" \
         "curl -s -w '%{http_code}\n' '${SERVICE_URL}/api/pronostics?date=$(date +%F)' | jq ." \
         "200"
if [ $? -ne 0 ]; then ALL_TESTS_PASSED=false; fi

# 3. Test POST /schedule without API key (Expected 403)
run_test "API /schedule (no API key)" \
         "curl -s -X POST -H 'Content-Type: application/json' -d '{\"dry_run\":true}' -w '%{http_code}\n' '${SERVICE_URL}/schedule'" \
         "403"
if [ $? -ne 0 ]; then ALL_TESTS_PASSED=false; fi

# 4. Test POST /schedule with valid API key (Expected 200)
if [ "$SKIP_AUTH_TESTS" = false ]; then
    run_test "API /schedule (with valid API key)" \
             "curl -s -X POST -H 'Content-Type: application/json' -H 'X-API-KEY: ${API_KEY}' -d '{\"dry_run\":true, \"date\":\"$(date +%F)\"}' -w '%{http_code}\n' '${SERVICE_URL}/schedule'" \
             "200"
    if [ $? -ne 0 ]; then ALL_TESTS_PASSED=false; fi
else
    echo -e "${YELLOW}Skipping authenticated /schedule test: HIPPIQUE_INTERNAL_API_KEY not set.${NC}\n"
fi

echo -e "${GREEN}Smoke Tests Complete.${NC}"
if [ "$ALL_TESTS_PASSED" = true ]; then
    echo -e "${GREEN}All critical smoke tests passed!${NC}"
    exit 0
else
    echo -e "${RED}Some smoke tests failed. Please check the logs above.${NC}"
    exit 1
fi