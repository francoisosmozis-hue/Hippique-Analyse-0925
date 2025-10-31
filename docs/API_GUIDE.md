# Operations Guide

This document explains the operational aspects of the Hippique Orchestrator service.

## Endpoints

### `GET /__health`

*   **Purpose:** A public, unauthenticated endpoint to verify that the service is running and responsive.
*   **Response:** A JSON object indicating the service status, its current version, and the server timestamp.
    ```json
    {"ok":true,"version":"0.1.0","ts":"2025-10-25T10:00:00Z"}
    ```

### `POST /pipeline/run`

*   **Purpose:** The main entry point to trigger a pipeline run for a specific race. This endpoint is state-changing and should be called by a trusted scheduler or user.
*   **Payload:** A JSON object specifying the context for the run.
    ```json
    {
      "reunion": "R1",
      "course": "C3",
      "phase": "H5", // H30, H5, or RESULT
      "budget": 5.0
    }
    ```
*   **Action:** The service calls the `runner_chain.run_chain` function with the provided arguments. This executes the logic for the specified phase and generates artifacts (snapshots, analysis files).
*   **Response:** The endpoint returns a JSON object summarizing the outcome.
    ```json
    {
      "abstain": false,
      "tickets": [...],
      "roi_global_est": 0.23,
      "paths": { ... }
    }
    ```

### `GET /tickets`

*   **Purpose:** Provides a consolidated view of all betting decisions made for the current day.
*   **Action:** The service scans the `data/` directory, finds all `analysis_H5.json` files created on the current date, and aggregates them into a list.
*   **Response:** A JSON array where each object represents the analysis for a single race.

## Orchestration & Scheduling

The pipeline is designed to be executed in three distinct phases for each race. This requires an external scheduler (like Google Cloud Scheduler) to call the `/pipeline/run` endpoint at the appropriate times.

### Phase 1: H-30 (30 minutes before the race)

*   **Trigger:** `POST /pipeline/run` with `{"phase": "H30", ...}`.
*   **Action:** The orchestrator fetches a preliminary snapshot of the race data (runners, odds, etc.).
*   **Outcome:** A `snapshot_H30.json` file is created in the `data/R.C/` directory. No betting decisions are made.

### Phase 2: H-5 (5 minutes before the race)

*   **Trigger:** `POST /pipeline/run` with `{"phase": "H5", ...}`.
*   **Action:**
    1.  A final `snapshot_H5.json` is captured.
    2.  Enrichment scripts are run to gather Jockey/Trainer stats and chrono data.
    3.  **A hard block is in place: if enrichment data is missing, the pipeline abstains.**
    4.  The main `pipeline_run` logic is executed, applying all GPI v5.1 guardrails (overround, ROI, EV, budget, etc.).
*   **Outcome:** An `analysis_H5.json` file is created, containing the final decision (`abstain: true|false`) and any `tickets` to be played.

### Phase 3: RESULT (Post-race)

*   **Trigger:** `POST /pipeline/run` with `{"phase": "RESULT", ...}`.
*   **Action:** Scripts are run to fetch the official race results and update tracking spreadsheets.
*   **Outcome:** The betting performance can be analyzed. This phase is for data collection and does not generate bets.