#!/bin/bash

# Smoke Test Script for Hippique Orchestrator
#
# This script performs basic health checks against a deployed instance of the service.
#
# Prerequisites:
#   - `curl` and `jq` must be installed.
#   - The environment variable `PROD_URL` must be set to the base URL of the service.
#     (e.g., export PROD_URL="https://my-service-url.run.app")
#   - For the authenticated endpoint test, `HIPPIQUE_INTERNAL_API_KEY` must be set.

set -e  # Exit immediately if a command exits with a non-zero status.
set -o pipefail # Return the exit status of the last command in the pipe that failed.

# --- Helper Functions ---
print_info() {
    echo "INFO: $1"
}

print_success() {
    echo "  [OK] $1"
}

print_error() {
    echo "ERROR: $1" >&2
    exit 1
}

# --- Pre-flight Checks ---
if [ -z "$PROD_URL" ]; then
    print_error "PROD_URL environment variable is not set. Please set it to the service's base URL."
fi

# Remove trailing slash if present
PROD_URL=${PROD_URL%/}

# --- Tests ---

# 1. Test /health endpoint
print_info "1. Testing /health endpoint..."
health_response=$(curl -s -o /dev/null -w "%{http_code}" "${PROD_URL}/health")
if [ "$health_response" -eq 200 ]; then
    print_success "/health endpoint is healthy."
else
    print_error "/health endpoint returned status ${health_response}. Expected 200."
fi

# 2. Test /pronostics UI page
print_info "2. Testing /pronostics UI page..."
ui_response=$(curl -s -L -o /dev/null -w "%{http_code}" "${PROD_URL}/pronostics")
if [ "$ui_response" -eq 200 ]; then
    print_success "/pronostics UI page loads."
else
    print_error "/pronostics UI page returned status ${ui_response}. Expected 200."
fi

# 3. Test /api/pronostics endpoint
print_info "3. Testing /api/pronostics data endpoint..."
api_response_code=$(curl -s -o /dev/null -w "%{http_code}" "${PROD_URL}/api/pronostics")
if [ "$api_response_code" -eq 200 ]; then
    # Additionally check if the response is valid JSON with an "ok" key
    api_response_body=$(curl -s "${PROD_URL}/api/pronostics")
    if echo "$api_response_body" | jq -e '.ok == true' > /dev/null; then
        print_success "/api/pronostics returns data with 'ok: true'."
    else
        print_error "/api/pronostics did not return a valid JSON response with 'ok: true'."
    fi
else
    print_error "/api/pronostics returned status ${api_response_code}. Expected 200."
fi

# 4. Test /schedule endpoint (unauthenticated)
print_info "4. Testing /schedule endpoint without authentication..."
unauth_schedule_response=$(curl -s -o /dev/null -w "%{http_code}" -X POST -H "Content-Type: application/json" -d '{"dry_run": true}' "${PROD_URL}/schedule")
if [ "$unauth_schedule_response" -ge 400 ] && [ "$unauth_schedule_response" -lt 500 ]; then
    print_success "/schedule rejects request without API key (status: ${unauth_schedule_response})."
else
    print_error "/schedule returned status ${unauth_schedule_response} without API key. Expected 4xx."
fi

# 5. Test /schedule endpoint (authenticated)
print_info "5. Testing /schedule endpoint with authentication..."
if [ -z "$HIPPIQUE_INTERNAL_API_KEY" ]; then
    print_info "  -> SKIPPED: HIPPIQUE_INTERNAL_API_KEY is not set."
else
    auth_schedule_response=$(curl -s -o /dev/null -w "%{http_code}" -X POST \
        -H "Content-Type: application/json" \
        -H "X-API-KEY: ${HIPPIQUE_INTERNAL_API_KEY}" \
        -d '{"dry_run": true}' \
        "${PROD_URL}/schedule")
    
    if [ "$auth_schedule_response" -eq 200 ]; then
        print_success "/schedule accepts request with valid API key."
    else
        print_error "/schedule returned status ${auth_schedule_response} with a valid API key. Expected 200."
    fi
fi

echo ""
print_success "All smoke tests passed!"