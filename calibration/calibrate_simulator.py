#!/usr/bin/env python3
"""Calibrate simulation probabilities using a Beta-Binomial model.

This script updates the win probability of each combination ("combiné")
based on past results.  The calibration file stores ``alpha`` and ``beta``
parameters of a Beta distribution along with the implied probability.  A
decay factor is applied before each new observation so that recent bets carry
more weight than older ones.

The results CSV is expected to contain at least two columns:
``combination`` (identifier of the combiné) and ``win`` (1 if the
combination succeeded, 0 otherwise).
"""
from __future__ import annotations

import argparse
import csv
import math
from collections import defaultdict
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path

import yaml

DEFAULT_HALF_LIFE = 60.0
DEFAULT_DECAY = 0.5 ** (1.0 / DEFAULT_HALF_LIFE)
METADATA_KEY = "__meta__"
_TIMESTAMP_FIELDS = ("updated_at", "timestamp", "ts", "date", "datetime")


def _half_life_from_decay(decay: float) -> float | None:
    if not 0.0 < decay < 1.0:
        return None
    return math.log(0.5) / math.log(decay)


def _decay_from_half_life(half_life: float) -> float:
    if half_life <= 0:
        raise ValueError("half-life must be positive")
    return 0.5 ** (1.0 / half_life)


def _coerce_decay(data: Mapping[str, object]) -> float | None:
    if "decay" in data:
        try:
            decay_val = float(data["decay"])  # type: ignore[assignment]
        except (TypeError, ValueError):
            raise ValueError("decay value in config must be numeric") from None
        return decay_val
    if "half_life" in data:
        try:
            half_life_val = float(data["half_life"])  # type: ignore[assignment]
        except (TypeError, ValueError):
            raise ValueError("half_life value in config must be numeric") from None
        return _decay_from_half_life(half_life_val)
    return None


def _extract_decay_from_config(config: Mapping[str, object]) -> float | None:
    """Return decay factor defined in ``config`` when available."""

    decay = _coerce_decay(config)
    if decay is not None:
        return decay

    for key in ("calibration", "probabilities", "simulator"):
        nested = config.get(key)
        if isinstance(nested, Mapping):
            decay = _coerce_decay(nested)
            if decay is not None:
                return decay
    return None


def _normalise_decay(decay: float) -> float:
    if not 0.0 < decay <= 1.0:
        raise ValueError("decay must be in the interval (0, 1]")
    return float(decay)


def _row_timestamp(row: Mapping[str, object]) -> str | None:
    for key in _TIMESTAMP_FIELDS:
        value = row.get(key)
        if value:
            return str(value)
    return None


def update_probabilities(
    results_file: str, calibration_file: str, *, decay: float | None = None
) -> dict[str, float]:
    """Update calibrated probabilities using a Beta-Binomial model.

    Parameters
    ----------
    results_file:
        Path to a CSV file containing historical results.  It must provide the
        columns ``combination`` and ``win`` (1 or 0).
    calibration_file:
        Path to a YAML file where calibration parameters will be stored.
    decay:
        Optional exponential decay applied to ``alpha`` and ``beta`` before
        each observation.  When ``None`` the value stored in the calibration
        metadata is reused; otherwise a default equivalent to a ~60 bet
        half-life is applied.
    Returns
    -------
    dict
        Mapping of combination identifiers to their updated probability.
    """
    # Load existing calibration parameters if available
    calib_path = Path(calibration_file)

    if calib_path.exists():
        with calib_path.open("r", encoding="utf-8") as fh:
            existing = yaml.safe_load(fh) or {}
    else:
        existing = {}

    metadata = existing.get(METADATA_KEY)
    if decay is None and isinstance(metadata, Mapping):
        stored_decay = metadata.get("decay")
        if stored_decay is not None:
            try:
                decay = float(stored_decay)  # type: ignore[assignment]
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"Invalid decay value in calibration metadata: {stored_decay!r}"
                ) from exc
    if decay is None:
        decay = DEFAULT_DECAY
    decay = _normalise_decay(decay)
    params: dict[str, dict[str, float]] = defaultdict(
        lambda: {"alpha": 1.0, "beta": 1.0}
    )
    extras: dict[str, dict[str, object]] = defaultdict(dict)
    for key, val in existing.items():
        if key == METADATA_KEY:
            continue
        if not isinstance(val, Mapping):
            continue
        alpha = float(val.get("alpha", 1.0))
        beta = float(val.get("beta", 1.0))
        params[key] = {"alpha": alpha, "beta": beta}
        extras[key].update(
            {
                str(extra_key): val[extra_key]
                for extra_key in val
                if extra_key not in {"alpha", "beta", "p"}
            }
        )

    # Incorporate new results
    with open(results_file, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        if "combination" not in reader.fieldnames or "win" not in reader.fieldnames:
            raise ValueError("CSV must contain 'combination' and 'win' columns")
        for row in reader:
            combo = row["combination"]
            win = int(row["win"])
            p = params[combo]
            p["alpha"] *= decay
            p["beta"] *= decay
            if win:
                p["alpha"] += 1.0
            else:
                p["beta"] += 1.0

            extras_combo = extras[combo]
            timestamp = _row_timestamp(row)
            if timestamp is None:
                timestamp = datetime.now(timezone.utc).isoformat()
            extras_combo["updated_at"] = timestamp
            extras_combo["weight"] = p["alpha"] + p["beta"]

    # Compute posterior probabilities and write back to YAML
    out_data: dict[str, dict[str, float]] = {}
    for combo, p in params.items():
        alpha, beta = p["alpha"], p["beta"]
        prob = alpha / (alpha + beta)
        entry = {"alpha": alpha, "beta": beta, "p": prob, "weight": alpha + beta}
        extra_fields = extras.get(combo)
        if extra_fields:
            for extra_key, extra_value in extra_fields.items():
                if extra_value is None:
                    continue
                if extra_key == "weight":
                    continue
                entry[str(extra_key)] = extra_value
        out_data[combo] = entry

    now_iso = datetime.now(timezone.utc).isoformat()
    if isinstance(metadata, Mapping):
        meta_out = dict(metadata)
    else:
        meta_out = {}
    meta_out.update({"decay": decay, "generated_at": now_iso})
    half_life = _half_life_from_decay(decay)
    if half_life is not None:
        meta_out["half_life"] = half_life
    elif "half_life" in meta_out:
        del meta_out["half_life"]
    out_data[METADATA_KEY] = meta_out

    calib_path.parent.mkdir(parents=True, exist_ok=True)
    with calib_path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(out_data, fh, sort_keys=True)

    return {k: v["p"] for k, v in out_data.items() if k != METADATA_KEY}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Calibrate simulator probabilities")
    parser.add_argument(
        "--results",
        required=True,
        help="CSV file containing past results",
    )
    parser.add_argument(
        "--calibration",
        default="calibration/probabilities.yaml",
        help="YAML file to store calibration parameters",
    )
    parser.add_argument(
        "--config",
        help="Optional YAML file providing a decay factor (keys: 'decay' or 'half_life')",
    )
    parser.add_argument(
        "--decay",
        type=float,
        help=(
            "Decay factor applied before each observation (default corresponds to a "
            "half-life of approximately 60 bets)."
        ),
    )
    return parser.parse_args()


def main() -> None:  # pragma: no cover - CLI entry point
    args = _parse_args()
    decay = args.decay
    if decay is None and args.config:
        cfg_path = Path(args.config)
        if cfg_path.exists():
            with cfg_path.open("r", encoding="utf-8") as fh:
                config_data = yaml.safe_load(fh) or {}
            if isinstance(config_data, Mapping):
                decay = _extract_decay_from_config(config_data)
            else:
                raise ValueError("Configuration file must contain a YAML mapping")
        else:
            raise FileNotFoundError(f"Config file not found: {cfg_path}")
    update_probabilities(args.results, args.calibration, decay=decay)


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    main()
