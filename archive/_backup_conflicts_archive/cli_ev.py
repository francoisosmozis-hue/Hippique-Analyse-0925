#!/usr/bin/env python3
from __future__ import annotations

import argparse
import inspect
import json
from pathlib import Path
from typing import Any

import yaml
from ev_calculator import compute_ev_roi

SIG = inspect.signature(compute_ev_roi)
DEFAULT_EV_THRESHOLD = SIG.parameters["ev_threshold"].default
DEFAULT_ROI_THRESHOLD = SIG.parameters["roi_threshold"].default
DEFAULT_KELLY_CAP = SIG.parameters["kelly_cap"].default


def load_tickets(path: Path) -> list[dict[str, Any]]:
    """Load ticket definitions from a JSON or YAML file."""

    with path.open() as handle:
        if path.suffix.lower() in {".yaml", ".yml"}:
            data = yaml.safe_load(handle)
        else:
            data = json.load(handle)

    if isinstance(data, dict) and "tickets" in data:
        tickets = data["tickets"]
    elif isinstance(data, list):
        tickets = data
    else:
        raise ValueError("Ticket file must contain a list or a 'tickets' key")
    if not isinstance(tickets, list):
        raise ValueError("Tickets must be a list of dictionaries")
    return tickets


def main() -> None:
    parser = argparse.ArgumentParser(description="Compute EV/ROI for betting tickets")
    parser.add_argument("--tickets", required=True, help="Path to tickets file (JSON or YAML)")
    parser.add_argument("--budget", type=float, required=True, help="Bankroll budget to use")
    parser.add_argument(
        "--ev-threshold",
        type=float,
        default=DEFAULT_EV_THRESHOLD,
        help="Minimum EV ratio to mark as green",
    )
    parser.add_argument(
        "--roi-threshold",
        type=float,
        default=DEFAULT_ROI_THRESHOLD,
        help="Minimum ROI to mark as green",
    )
    parser.add_argument(
        "--kelly-cap",
        type=float,
        default=DEFAULT_KELLY_CAP,
        help="Maximum fraction of Kelly stake to wager",
    )
    args = parser.parse_args()

    tickets = load_tickets(Path(args.tickets))
    result = compute_ev_roi(
        tickets,
        budget=args.budget,
        ev_threshold=args.ev_threshold,
        roi_threshold=args.roi_threshold,
        kelly_cap=args.kelly_cap,
    )

    ev = result["ev"]
    roi = result["roi"]
    risk = result["risk_of_ruin"]
    pastille = "\U0001f7e2" if result["green"] else "\U0001f534"

    print(f"EV: {ev:.2f}")
    print(f"ROI: {roi:.2%}")
    print(f"Risk of ruin: {risk:.2%}")
    print(f"Pastille: {pastille}")


if __name__ == "__main__":
    main()
