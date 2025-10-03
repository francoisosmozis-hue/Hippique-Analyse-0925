# ROI+ v5.1 Operational Notes

## Staking Rules
- Daily bankroll is capped at **5 €**.
- Maximum of **two tickets per meeting**; any additional opportunities are skipped.
- Split stakes evenly across active tickets unless a scenario-specific allocation is defined in the run configuration.

## EV / ROI Thresholds
- Only deploy tickets with **expected value (EV) ≥ 1.05** and **projected ROI ≥ 8 %** after accounting for commission.
- Flag tickets with EV between 1.02 and 1.05 for manual review; do not auto-submit unless an operator overrides the gate.

## Overround Gating
- Market overround must be **≤ 112 %** at H-30 and **≤ 108 %** at H-5.
- If overround breaches the ceiling, suppress ticket generation and log the meeting for monitoring.

## Data Fail-Safe Behavior
- If any mandatory feed (odds, runners, scratches, or calibration curves) is stale by more than **7 minutes**, halt the pipeline and alert Ops via the standard PagerDuty hook.
- On partial failures (e.g., missing sectional times), downgrade confidence and require manual approval before transmission.

## Calibration Requirements
- Maintain calibration files under `calibration/` with timestamps no older than **72 hours**.
- Run the calibration suite after any odds-provider change or when drift exceeds **±3 %** on the EV back-test window.

## H-30 / H-5 Routine
- **H-30**: Execute the pre-race sweep, validate data freshness, apply overround gate, and stage qualifying tickets for review.
- **H-5**: Recompute EV/ROI using live odds, rerun gates, and submit approved tickets.
- Log all decisions with meeting ID, ticket ID, EV, ROI, and overround snapshot for auditability.

## HOW TO RUN
```
make venv
make test
make run-h30 ARGS="--meeting <meeting_id> --date <YYYY-MM-DD>"
make run-h5 ARGS="--meeting <meeting_id> --date <YYYY-MM-DD>"
```
