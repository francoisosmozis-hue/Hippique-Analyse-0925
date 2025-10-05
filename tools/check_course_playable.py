"""CLI helper to evaluate course guardrails using runner_chain logic."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

import runner_chain
from simulate_wrapper import PAYOUT_CALIBRATION_PATH


def build_parser() -> argparse.ArgumentParser:
    """Return an argument parser mirroring runner_chain guard parameters."""

    parser = argparse.ArgumentParser(
        description="Check whether a course is playable using runner guardrails",
    )
    parser.add_argument(
        "--dir",
        dest="course_dir",
        required=True,
        help="Directory containing je_stats.csv and chronos.csv (ex: data/R1C5)",
    )
    parser.add_argument(
        "--budget",
        type=float,
        default=5.0,
        help="Total bankroll dedicated to the course (default: 5)",
    )
    parser.add_argument(
        "--overround-max",
        dest="overround_max",
        type=float,
        default=1.30,
        help="Maximum accepted market overround for exotic tickets (default: 1.30)",
    )
    parser.add_argument(
        "--ev-min-exotic",
        dest="ev_min_exotic",
        type=float,
        default=0.40,
        help="Minimum EV ratio required for exotic tickets (default: 0.40)",
    )
    parser.add_argument(
        "--payout-min-exotic",
        dest="payout_min_exotic",
        type=float,
        default=10.0,
        help="Minimum expected payout required for exotic tickets (default: 10)",
    )
    parser.add_argument(
        "--ev-min-sp",
        dest="ev_min_sp",
        type=float,
        default=0.40,
        help="Minimum EV ratio required for SP dutching (default: 0.40)",
    )
    parser.add_argument(
        "--roi-min-global",
        dest="roi_min_global",
        type=float,
        default=0.20,
        help="Minimum ROI required for the global ticket pack (default: 0.20)",
    )
    parser.add_argument(
        "--kelly-frac",
        dest="kelly_frac",
        type=float,
        default=0.4,
        help="Kelly fraction applied to SP dutching (default: 0.4)",
    )
    parser.add_argument(
        "--calibration",
        default=str(PAYOUT_CALIBRATION_PATH),
        help="Path to payout_calibration.yaml used for combo validation",
    )
    return parser


def _format_reason_list(
    payload: Mapping[str, Any], guards: Mapping[str, Any]
) -> list[str]:
    reasons: list[str] = []
    payload_reasons = payload.get("reasons")
    if isinstance(payload_reasons, list):
        reasons.extend(str(reason) for reason in payload_reasons if reason)
    guard_reason = guards.get("reason")
    if guard_reason and str(guard_reason) not in reasons:
        reasons.append(str(guard_reason))
    return reasons


def _print_human_verdict(payload: Mapping[str, Any]) -> None:
    guards = payload.get("guards")
    if not isinstance(guards, Mapping):
        print("NON JOUABLE")
        print("  1. guards_missing")
        return

    jouable = bool(guards.get("jouable"))
    label = "JOUABLE" if jouable else "NON JOUABLE"
    print(label)

    reasons = _format_reason_list(payload, guards)
    if reasons:
        for idx, reason in enumerate(reasons, start=1):
            print(f"  {idx}. {reason}")
    elif not jouable:
        print("  1. unknown_reason")
    else:
        print("  Aucun blocage détecté")


def main(argv: Sequence[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    course_dir = Path(args.course_dir)
    calibration = str(args.calibration)

    # Keep runner_chain global guardrails aligned with the provided calibration.
    os.environ["CALIB_PATH"] = calibration

    runner_chain.CALIB_PATH = calibration

    payload = runner_chain._analyse_course(  # type: ignore[attr-defined]
        course_dir,
        budget=float(args.budget),
        overround_max=float(args.overround_max),
        ev_min_exotic=float(args.ev_min_exotic),
        payout_min_exotic=float(args.payout_min_exotic),
        ev_min_sp=float(args.ev_min_sp),
        roi_min_global=float(args.roi_min_global),
        kelly_frac=float(args.kelly_frac),
        calibration=calibration,
    )

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    _print_human_verdict(payload)


if __name__ == "__main__":
    main()
