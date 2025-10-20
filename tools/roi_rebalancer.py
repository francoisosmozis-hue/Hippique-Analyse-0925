"""CLI to rebalance the daily bankroll using analysis artefacts."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable
from pathlib import Path

from hippique.analytics import compute_allocation_plan, load_analysis_reports


def _iter_inputs(inputs: Iterable[str]) -> list[Path]:
    paths: list[Path] = []
    for entry in inputs:
        path = Path(entry)
        if not path.exists():
            print(f"[WARN] skipping missing path: {path}", file=sys.stderr)
            continue
        paths.append(path)
    return paths


def _print_plan(plan) -> None:
    if not plan.allocations:
        print("No qualifying races met the EV/ROI guardrails.")
        return

    header = f"{'Race':<12}{'Stake (€)':>12}{'EV (€)':>12}{'ROI':>8}{'ROR':>8}"
    print(header)
    print("-" * len(header))
    for alloc in plan.allocations:
        print(
            f"{alloc.race.race_id:<12}"
            f"{alloc.recommended_stake:>12.2f}"
            f"{alloc.scaled_ev:>12.2f}"
            f"{alloc.scaled_roi:>8.2%}"
            f"{alloc.scaled_risk:>8.2%}"
        )
    print("-" * len(header))
    print(
        f"Bankroll: {plan.bankroll:.2f} €  |  "
        f"Expected return: {plan.expected_return:.2f} €  |  "
        f"Expected ROI: {plan.expected_roi:.2%}  |  "
        f"Aggregate ROR ≤ {plan.aggregate_risk:.2%} (union bound)"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="+", help="analysis.json files or directories")
    parser.add_argument("--bankroll", type=float, required=True, help="Daily bankroll to allocate")
    parser.add_argument(
        "--target-ror", type=float, default=0.05, help="Daily risk of ruin target (default 5%)"
    )
    parser.add_argument(
        "--min-roi", type=float, default=0.10, help="Minimum ROI to keep a race in the slate"
    )
    parser.add_argument(
        "--json-out", type=Path, help="Optional path to persist the allocation plan as JSON"
    )
    args = parser.parse_args(argv)

    inputs = _iter_inputs(args.inputs)
    if not inputs:
        print("No valid inputs provided.", file=sys.stderr)
        return 2

    reports = load_analysis_reports(inputs)
    plan = compute_allocation_plan(
        reports,
        bankroll=args.bankroll,
        target_ror=args.target_ror,
        min_roi=args.min_roi,
    )

    _print_plan(plan)

    if args.json_out:
        try:
            args.json_out.write_text(json.dumps(plan.as_dict(), indent=2), encoding="utf-8")
        except OSError as exc:  # pragma: no cover - filesystem errors
            print(f"[WARN] unable to write plan to {args.json_out}: {exc}", file=sys.stderr)

    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
