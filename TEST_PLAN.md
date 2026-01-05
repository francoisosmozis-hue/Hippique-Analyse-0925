# Test Plan for Hippique Orchestrator

This document outlines the testing strategy for the Hippique Orchestrator project, covering unit, integration, and smoke tests.

## 1. Overview

The testing strategy is divided into three main pillars to ensure code quality, component reliability, and production stability.

1.  **Unit Tests:** Focused on individual modules and functions in isolation.
2.  **Integration Tests:** Focused on the service's API endpoints, verifying that components work together correctly.
3.  **Smoke Tests:** A minimal set of end-to-end checks to quickly validate a deployed environment.

## 2. Running Tests

### Prerequisites

Ensure all development dependencies are installed:
```bash
pip install -r requirements-dev.txt
```

### Running the Full Test Suite

To run all unit and integration tests and generate a coverage report, use the following command from the project root:

```bash
pytest --cov=hippique_orchestrator
```

### Running Specific Test Suites

- **Unit Tests for Scripts:**
  These tests validate the business logic within the `scripts/` directory.
  ```bash
  # Run all script tests
  pytest tests/scripts/

  # Run tests for a specific script
  pytest tests/scripts/test_simulate_wrapper_script.py
  pytest tests/scripts/test_update_excel_with_results_script.py
  ```

- **API Integration Tests:**
  These tests validate the FastAPI service endpoints.
  ```bash
  pytest tests/test_api_integration.py
  ```

## 3. Test Categories

### Unit Tests

- **Location:** `tests/`
- **Goal:** To verify that individual functions and classes behave as expected. Mocks and fixtures are used extensively to isolate components from external dependencies (like filesystems or cloud services).
- **Key Modules Covered:**
  - `hippique_orchestrator/scripts/simulate_wrapper.py`: Validates probability calculations, Monte Carlo simulations, and error handling.
  - `hippique_orchestrator/scripts/update_excel_with_results.py`: Validates the creation and updating of Excel report files.

### Integration Tests

- **Location:** `tests/test_api_integration.py`
- **Goal:** To verify that the API endpoints process requests correctly, interact with mocked services as expected, and return the correct data structures and status codes.
- **Framework:** Uses FastAPI's `TestClient`.
- **Key Endpoints Covered:**
  - `/health`: Ensures the service is running.
  - `/debug/config`: Verifies that the configuration is loaded.
  - `/api/pronostics`: Verifies the core data aggregation logic by mocking the data sources (`plan` and `firestore_client`).

### Smoke Tests

- **Location:** `scripts/smoke_prod.sh`
- **Goal:** To perform a quick, high-level check on a live, deployed environment (e.g., production or staging). This is not for detailed testing but to answer the question: "Is the service up and fundamentally working?"
- **Usage:**
  ```bash
  # Ensure you have an API key set in your environment
  export API_KEY="your-production-api-key"
  
  # Run the script against the production URL
  bash scripts/smoke_prod.sh https://your-service-url.com
  ```
- **Checks Performed:**
  1.  Hits the `/health` endpoint and confirms the status is "healthy".
  2.  Hits the `/api/pronostics` endpoint and confirms it returns a successful response (`"ok": true`) and a non-empty list of `pronostics`.