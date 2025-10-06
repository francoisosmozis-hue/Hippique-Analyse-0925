# Patch Notes

## Summary of fixes
- **Snapshot fetch hardening** – The lightweight wrapper now normalises reunion/course labels, falls back to HTML scraping and preserves canonical URLs so downstream consumers always receive consistent runner/market payloads. 【F:online_fetch_zeturf.py†L63-L131】
- **H-5 enrichment fail-safes** – The enrichment helper enforces fresh H-30/H-5 snapshots, normalises odds maps, retries artefact generation and records guard context before handing control back to the pipeline. 【F:analyse_courses_du_jour_enrichie.py†L445-L1048】
- **Adaptive overround computation** – Combo evaluation applies a dynamic overround cap that tightens on flat handicaps, filters high-overround markets and exposes context for logging. 【F:runner_chain.py†L69-L220】
- **SP EV guardrail** – When the allocated SP bankroll underperforms the configured EV floor the guard raises `sp_ev_below_min` and withholds straight tickets, preventing weak slates from shipping. 【F:runner_chain.py†L1080-L1112】
- **Calibration enforcement** – Combo simulation refuses to run without a payout calibration file, returning an explicit `calibration_missing` decision to keep exotic tickets disabled until curves are restored. 【F:runner_chain.py†L284-L306】
- **End-to-end smoke validation** – The pipeline smoke test exercises the CLI flow, asserts overround metrics and artefact generation, and matches drift diff parameters to the expected snapshot pair. 【F:tests/test_pipeline_smoke.py†L237-L317】

## Verification steps

### Smoke script
Run the end-to-end H-5 sanity check against the default Vincennes meeting (override the URL as needed):

```bash
./scripts/smoke_h5.sh [https://www.zeturf.fr/fr/meeting/DATE/HIPPODROME]
```

The script wipes `out_smoke_h5/`, launches `analyse_courses_du_jour_enrichie.py`, and verifies that `analysis_H5.json`, JE/chronos CSVs, per-horse and tracking reports, and the snapshot artefact are present before reporting success. 【F:scripts/smoke_h5.sh†L8-L88】

### Pytest targets
Targeted suites cover the guardrails introduced in this patch:

```bash
pytest tests/test_pipeline_smoke.py::test_smoke_run
pytest tests/test_runner_chain.py::test_compute_overround_cap_flat_handicap_string_partants
pytest tests/test_runner_chain.py::test_compute_overround_cap_flat_large_field
pytest tests/test_runner_chain.py::test_estimate_sp_ev_returns_none_when_insufficient
pytest tests/test_runner_chain_guard_combo_calibration.py::test_validate_exotics_requires_calibration
```

These tests validate end-to-end smoke behaviour, overround capping heuristics, SP EV gating and calibration enforcement respectively. 【F:tests/test_pipeline_smoke.py†L237-L317】【F:tests/test_runner_chain.py†L52-L115】【F:tests/test_runner_chain.py†L38-L45】【F:tests/test_runner_chain_guard_combo_calibration.py†L4-L24】
