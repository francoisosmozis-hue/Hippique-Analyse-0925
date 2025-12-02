# ROI & Exotic Ticket Guardrails

## Thresholds that gate exotic tickets
- **Baseline EV and payout** – Every combiné evaluated by the simulation wrapper must clear an EV ratio of at least 0.40 and an expected payout of 10 € before any configurable thresholds are considered.【F:pipeline_run.py†L57-L272】【F:runner_chain.py†L320-L377】
- **ROI requirement** – The runner-chain CLI enforces a minimum global ROI of 20 % for the ticket pack, and the validation layer rejects any candidate that falls below the configured ROI floor.【F:runner_chain.py†L829-L834】【F:runner_chain.py†L360-L374】
- **Market overround** – Exotic templates are discarded upfront whenever the observed overround exceeds the adaptive ceiling. The default cap is 1.30, tightened automatically to 1.25 for flat handicaps (including large 14+ runner fields). The pipeline now computes this metric directly from the place odds (falling back to win odds when necessary) so that the guard reflects the actual bookmaker book.【F:pipeline_run.py†L225-L323】【F:pipeline_run.py†L1099-L1234】【F:runner_chain.py†L69-L227】

## Deterministic workflow & skip conditions
1. **Global pause flag** – When calibration health flags raise `PAUSE_EXOTIQUES`, the ticket builder stops after producing SP dutching bets and returns no exotic templates.【F:tickets_builder.py†L363-L372】【F:README.md†L520-L522】
2. **Calibration presence** – The validator aborts with `status="insufficient_data"` and reason `calibration_missing` if the payout calibration YAML is absent or unreachable.【F:runner_chain.py†L280-L294】
3. **Market overround guard** – Before simulation, the pipeline drops all combinés when the measured overround breaches the dynamic cap (1.30 baseline, 1.25 for flat handicaps), logging `overround_above_threshold` and skipping any further EV/ROI checks.【F:runner_chain.py†L69-L227】
4. **Simulation status** – Any wrapper response whose status is not `ok` (including `insufficient_data`) is rejected deterministically, propagating the `status_<reason>` tag to the guardrail output.【F:pipeline_run.py†L212-L279】【F:runner_chain.py†L320-L358】
5. **EV/ROI/payout filters** – Candidates that survive the status check must still satisfy the hard EV ≥ 40 %, ROI ≥ configured floor (≥ 20 %), payout ≥ 10 €, and Sharpe/pipeline thresholds; otherwise the validator records the precise `*_below_threshold` rejection reason.【F:pipeline_run.py†L212-L275】【F:runner_chain.py†L360-L379】

## SP dutching guardrails
- **Budget & ticket count** – The default configuration limits bankroll to 5 € per course, splits it 60 %/40 % between SP and combinés, and caps SP issuance to a single dutching ticket (so at most two slips overall).【F:config/gpi.yml†L1-L24】
- **Place coverage floor** – Dutching SP is activated only when the selected legs cover at least 120 % aggregate place probability (Σ p_place ≥ 1.20). Otherwise the guard blocks the slate with a `coverage_fail_SigmaP` note.【F:pipeline_run.py†L1159-L1234】
- **Kelly staking caps** – SP allocation uses the configured Kelly fraction and clamps each runner’s exposure to 60 % of the SP bankroll, ensuring no single leg breaches the per-horse cap while respecting rounding and minimum stake rules.【F:simulate_ev.py†L124-L195】
- **Expected gross tracking** – Post-course CSV tracking now records the number of tickets dispatched and the expected gross return in euros to simplify ROI reconciliation.【F:runner_chain.py†L497-L555】 

## Refreshing payout calibration
Run the script below with the historical post-race reports stored under `data/results/`, which is the expected input directory for calibration history files:

```bash
python recalibrate_payouts_pro.py --history data/results/*.json --out calibration/payout_calibration.yaml
```

This command ingests each JSON report, recomputes the moving average error, and rewrites `calibration/payout_calibration.yaml` with an updated `PAUSE_EXOTIQUES` flag when the 15 % error ceiling is exceeded.【F:README.md†L498-L522】
