# ROI+ v5.1 Operational Notes

## Staking Rules
- Allocate a **5 € budget per course**, resetting for each meeting independently.
- Fire at most **one SP dutching ticket plus one combo** for any given course; additional opportunities beyond this two-ticket cap are skipped for that course.
- Distribute stakes via the configured **Kelly fractions**, while enforcing a **60 % exposure ceiling per runner**.

## EV / ROI Thresholds
- Only deploy combinations with **expected value (EV) ≥ +40 %** over stake.
- Ensure projected **ROI global remains ≥ +20 %** across the active batch.
- Require a **minimum projected payout of 10 €** for every submitted ticket.
- Reject tickets with forecast **SP above 60 %** to keep exposure aligned with the ROI+ v5.1 spec.

## Overround Gating
- Suppress generation when the **market overround exceeds 1.30** at any checkpoint.
- Log the blocked meeting and re-evaluate once the book returns below the gate.

## Data Fail-Safe Behavior
- If any mandatory feed (odds, runners, scratches, or calibration curves) is stale by more than **7 minutes**, halt the pipeline and alert Ops via the standard PagerDuty hook.
- Missing inputs trigger an **abstention propre**: no tickets are emitted until data integrity is restored, even if partial substitutes exist.

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
make run-h30 URL="https://..."
make run-h5 URL="https://..."
```
