#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Minimal pipeline for computing EV and exporting artefacts."""

import argparse
import copy
import datetime as dt
import json
import logging
import math
import os
import re
from functools import lru_cache, partial
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Mapping, Sequence, cast

from config.env_utils import get_env

logger = logging.getLogger(__name__)
LOG_LEVEL_ENV_VAR = "PIPELINE_LOG_LEVEL"
DEFAULT_OUTPUT_DIR = "out/hminus5"

EXOTIC_BASE_EV = 0.40
EXOTIC_BASE_PAYOUT = 10.0

def _maybe_load_dotenv() -> None:
    """Load environment variables from a .env file when available."""

    try:
        from dotenv import load_dotenv  # type: ignore
    except Exception:  # pragma: no cover - optional dependency
        return
    load_dotenv()


@lru_cache(maxsize=1)
def _load_simulate_ev() -> Dict[str, Callable[..., Any]]:
    """Import heavy simulation helpers lazily."""

    from simulate_ev import (
        allocate_dutching_sp,
        gate_ev,
        implied_prob,
        implied_probs,
        simulate_ev_batch,
    )

    return {
        "allocate_dutching_sp": allocate_dutching_sp,
        "gate_ev": gate_ev,
        "implied_prob": implied_prob,
        "implied_probs": implied_probs,
        "simulate_ev_batch": simulate_ev_batch,
    }


@lru_cache(maxsize=1)
def _load_p_true_helpers() -> Dict[str, Callable[..., Any]]:
    """Import calibration helpers lazily."""

    from calibration.p_true_model import (
        compute_runner_features,
        get_model_metadata,
        load_p_true_model,
        predict_probability,
    )

    return {
        "compute_runner_features": compute_runner_features,
        "get_model_metadata": get_model_metadata,
        "load_p_true_model": load_p_true_model,
        "predict_probability": predict_probability,
    }


def _resolve_output_dir() -> str:
    """Return the configured output directory, loading .env if required."""

    _maybe_load_dotenv()
    return os.getenv("OUTPUT_DIR", DEFAULT_OUTPUT_DIR)


def __getattr__(name: str) -> Any:
    """Provide backward-compatible lazy access to heavy dependencies."""

    simulate_helpers = _load_simulate_ev()
    if name in simulate_helpers:
        return simulate_helpers[name]

    p_true_helpers = _load_p_true_helpers()
    if name in p_true_helpers:
        return p_true_helpers[name]

    if name in {"allow_combo", "apply_ticket_policy"}:
        from tickets_builder import allow_combo, apply_ticket_policy

        mapping: Dict[str, Any] = {
            "allow_combo": allow_combo,
            "apply_ticket_policy": apply_ticket_policy,
        }
        return mapping[name]

    if name in {"combos_allowed", "summarise_validation", "validate_inputs"}:
        from validator_ev import combos_allowed, summarise_validation, validate_inputs

        mapping: Dict[str, Any] = {
            "combos_allowed": combos_allowed,
            "summarise_validation": summarise_validation,
            "validate_inputs": validate_inputs,
        }
        return mapping[name]

    if name in {"append_csv_line", "append_json", "CSV_HEADER"}:
        from logging_io import append_csv_line, append_json, CSV_HEADER

        mapping: Dict[str, Any] = {
            "append_csv_line": append_csv_line,
            "append_json": append_json,
            "CSV_HEADER": CSV_HEADER,
        }
        return mapping[name]

    if name == "sw":
        import simulate_wrapper as sw_module

        return sw_module

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def configure_logging(level: str | int | None = None) -> None:
    """Configure root logging based on CLI or environment settings."""

    _maybe_load_dotenv()
    resolved = level if level is not None else os.getenv(LOG_LEVEL_ENV_VAR, "INFO")
    numeric_level: int | None
    invalid_level = False

    if isinstance(resolved, int):
        numeric_level = resolved
    else:
        resolved_str = str(resolved).upper()
        if resolved_str.isdigit():
            numeric_level = int(resolved_str)
        else:
            numeric_level = getattr(logging, resolved_str, None)
            if not isinstance(numeric_level, int):
                numeric_level = logging.INFO
                invalid_level = True

    logging.basicConfig(
        level=numeric_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    if invalid_level:
        logger.warning(
            "Invalid log level %r, defaulting to INFO", resolved
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

REQ_KEYS = [
    "BUDGET_TOTAL",
    "SP_RATIO",
    "COMBO_RATIO",
    "EV_MIN_SP",
    "EV_MIN_GLOBAL",
    "ROI_MIN_SP",
    "ROI_MIN_GLOBAL",
    "ROR_MAX",
    "SHARPE_MIN",
    "MAX_VOL_PAR_CHEVAL",
    "ALLOW_JE_NA",
    "PAUSE_EXOTIQUES",
    "OUTDIR_DEFAULT",
    "EXCEL_PATH",
    "CALIB_PATH",
    "MODEL",
    "REQUIRE_DRIFT_LOG",
    "REQUIRE_ODDS_WINDOWS",
    "MIN_PAYOUT_COMBOS",
    "MAX_TICKETS_SP",
    "MIN_STAKE_SP",
    "DRIFT_COEF",
    "ROUND_TO_SP",
    "JE_BONUS_COEF",
]


OPTIONAL_KEYS = {
    "CORRELATION_PENALTY",
    "DRIFT_MIN_DELTA",
    "DRIFT_TOP_N",
    "EXOTIC_MIN_PAYOUT",
    "KELLY_FRACTION",
    "MIN_PAYOUT_COMBOS",
    "SNAPSHOTS",
    "P_TRUE_MIN_SAMPLES",
}

STEAM_UP = 0.03
STEAM_DOWN = -0.03

MIN_SP_DEC_ODDS = 5.0
"""Minimum decimal odds allowed for Simple Placé tickets (4/1)."""

MIN_CP_SUM_DEC = 8.0
"""Minimum combined decimal odds allowed for Couplé Placé tickets (>6/1)."""

_ODDS_KEYS = (
    "cote_place",
    "odds_place",
    "odds",
    "cote",
    "odd",
    "decimal_odds",
    "odds_dec",
    "place_odds",
)

_SP_TYPES = {
    "SP",
    "SIMPLE_PLACE_DUTCHING",
    "DUTCHING_SP",
    "PLACE_DUTCHING",
}

_SP_LABELS = {"SP_DUTCHING_GPIV51"}

_CP_TYPES = {
    "COUPLE",
    "COUPLE_PLACE",
    "COUPLE PLACÉ",
    "COUPLÉ PLACÉ",
    "COUPLE PLACÉ",
    "COUPLÉ PLACE",
    "CP",
}


def _norm_float(value: Any) -> float | None:
    """Convert ``value`` to ``float`` returning ``None`` on failure."""

    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        number = float(text.replace(",", "."))
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _normalize_sequence(value: Any) -> list[Any]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return list(value)
    return []


def _extract_leg_ids(entry: Mapping[str, Any]) -> list[str]:
    candidates: list[str] = []
    for key in (
        "id",
        "code",
        "runner",
        "participant",
        "horse",
        "horse_id",
        "id_horse",
        "num",
        "number",
        "selection",
    ):
        value = entry.get(key)
        if value in (None, ""):
            continue
        candidates.append(str(value))
    return candidates


def _extract_entry_odds(entry: Mapping[str, Any]) -> float | None:
    for key in _ODDS_KEYS:
        if key in entry and entry[key] not in (None, ""):
            odds = _norm_float(entry[key])
            if odds is not None:
                return odds
    return None


def _build_runner_odds_lookup(
    runners: Iterable[Mapping[str, Any]],
    partants: Mapping[str, Any],
) -> dict[str, float]:
    """Return a lookup mapping runner identifiers to decimal odds."""

    lookup: dict[str, float] = {}

    def register(entry: Any) -> None:
        if not isinstance(entry, Mapping):
            return
        odds = _extract_entry_odds(entry)
        if odds is None:
            return
        for key in _extract_leg_ids(entry):
            if key and key not in lookup:
                lookup[key] = odds

    market = partants.get("market") if isinstance(partants, Mapping) else None
    market_horses = []
    if isinstance(market, Mapping):
        horses = market.get("horses")
        if isinstance(horses, Sequence):
            market_horses = horses

    runners_data = partants.get("runners") if isinstance(partants, Mapping) else None

    for collection in (market_horses, runners_data, runners):
        if not collection:
            continue
        for item in collection:
            register(item)

    return lookup


def _resolve_leg_odds(
    leg: Any,
    odds_lookup: Mapping[str, float],
    fallback_entries: Sequence[Mapping[str, Any]] | None = None,
) -> float | None:
    """Return decimal odds associated with ``leg`` using lookup/fallbacks."""

    if isinstance(leg, Mapping):
        odds = _extract_entry_odds(leg)
        if odds is not None:
            return odds
        for key in _extract_leg_ids(leg):
            odds = odds_lookup.get(key)
            if odds is not None:
                return odds
    else:
        text = str(leg).strip()
        if text:
            odds = odds_lookup.get(text)
            if odds is not None:
                return odds
            converted = _norm_float(text)
            if converted is not None and converted > 0:
                return converted

    if fallback_entries:
        for entry in fallback_entries:
            odds = _extract_entry_odds(entry)
            if odds is not None:
                return odds
    return None


def _extract_ticket_odds(
    ticket: Mapping[str, Any], odds_lookup: Mapping[str, float]
) -> float | None:
    odds = _extract_entry_odds(ticket)
    if odds is not None:
        return odds
    for key in _extract_leg_ids(ticket):
        odds = odds_lookup.get(key)
        if odds is not None:
            return odds
    return None


def _filter_sp_and_cp_tickets(
    sp_tickets: Sequence[Mapping[str, Any]],
    combo_tickets: Sequence[Mapping[str, Any]],
    runners: Sequence[Mapping[str, Any]],
    partants: Mapping[str, Any],
) -> tuple[list[dict], list[dict], list[str]]:
    """Apply SP/CP guardrails on ticket odds returning filtered copies."""

    odds_lookup = _build_runner_odds_lookup(runners, partants)
    notes: list[str] = []

    filtered_sp: list[dict] = []
    for ticket in sp_tickets:
        typ = str(ticket.get("type") or "").upper()
        label = str(ticket.get("label") or "").upper()
        if typ in _SP_TYPES or label in _SP_LABELS:
            legs_seq = _normalize_sequence(ticket.get("legs"))
            bets_seq = _normalize_sequence(ticket.get("bets"))
            legs_details_seq = _normalize_sequence(ticket.get("legs_details"))
            if legs_seq:
                kept_indices: list[int] = []
                for index, leg in enumerate(legs_seq):
                    fallback_entries: list[Mapping[str, Any]] = []
                    if index < len(legs_details_seq) and isinstance(legs_details_seq[index], Mapping):
                        fallback_entries.append(legs_details_seq[index])
                    if index < len(bets_seq) and isinstance(bets_seq[index], Mapping):
                        fallback_entries.append(bets_seq[index])
                    odds = _resolve_leg_odds(leg, odds_lookup, fallback_entries)
                    if odds is not None and odds >= MIN_SP_DEC_ODDS:
                        kept_indices.append(index)
                if kept_indices:
                    ticket_copy = dict(ticket)
                    if legs_seq:
                        ticket_copy["legs"] = [legs_seq[i] for i in kept_indices]
                    if bets_seq:
                        ticket_copy["bets"] = [
                            bets_seq[i]
                            for i in kept_indices
                            if i < len(bets_seq)
                        ]
                    if legs_details_seq:
                        ticket_copy["legs_details"] = [
                            legs_details_seq[i]
                            for i in kept_indices
                            if i < len(legs_details_seq)
                        ]
                    filtered_sp.append(ticket_copy)
                else:
                    notes.append("SP retiré: toutes les cotes < 4/1 (5.0 déc).")
                continue

            odds_value = _extract_ticket_odds(ticket, odds_lookup)
            if odds_value is None:
                notes.append("SP retiré: cotes manquantes (règle 4/1 non vérifiable).")
                continue
            if odds_value < MIN_SP_DEC_ODDS:
                notes.append("SP retiré: toutes les cotes < 4/1 (5.0 déc).")
                continue
        filtered_sp.append(dict(ticket))

    filtered_combo: list[dict] = []
    for ticket in combo_tickets:
        typ = str(ticket.get("type") or "").upper()
        label = str(ticket.get("label") or "").upper()
        if typ in _CP_TYPES or label in _CP_TYPES:
            legs_seq = _normalize_sequence(ticket.get("legs"))
            legs_details_seq = _normalize_sequence(ticket.get("legs_details"))
            if len(legs_seq) != 2:
                filtered_combo.append(dict(ticket))
                notes.append("Avertissement: CP non-binaire (≠2 jambes).")
                continue
            odds_values: list[float | None] = []
            for index, leg in enumerate(legs_seq):
                fallback_entries: list[Mapping[str, Any]] = []
                if index < len(legs_details_seq) and isinstance(legs_details_seq[index], Mapping):
                    fallback_entries.append(legs_details_seq[index])
                odds = _resolve_leg_odds(leg, odds_lookup, fallback_entries)
                odds_values.append(odds)
            if all(value is not None for value in odds_values):
                assert len(odds_values) == 2
                total = float(odds_values[0]) + float(odds_values[1])
                if total > MIN_CP_SUM_DEC:
                    filtered_combo.append(dict(ticket))
                else:
                    notes.append(
                        (
                            "CP retiré: somme des cotes décimales "
                            f"{float(odds_values[0]):.2f}+{float(odds_values[1]):.2f} ≤ 8.00 (règle > 6/1 cumulés)."
                        )
                    )
            else:
                notes.append("CP retiré: cotes manquantes (règle >6/1 non vérifiable).")
            continue
        filtered_combo.append(dict(ticket))

    return filtered_sp, filtered_combo, notes


def drift_points(odds_h30: float | None, odds_h5: float | None) -> float:
    """Return the change in implied probability between H-30 and H-5."""

    implied_prob = cast(
        Callable[[float | None], float], _load_simulate_ev()["implied_prob"]
    )
    return implied_prob(odds_h5) - implied_prob(odds_h30)


def market_drift_signal(
    odds_h30: float | None,
    odds_h5: float | None,
    *,
    is_favorite: bool,
) -> int:
    """Return a market drift score based on probability delta thresholds."""

    delta = drift_points(odds_h30, odds_h5)
    if delta >= STEAM_UP:
        return 2
    if is_favorite and delta <= STEAM_DOWN:
        return -2
    return 0

_ENV_ALIASES: dict[str, tuple[str, ...]] = {
    "BUDGET_TOTAL": ("TOTAL_BUDGET", "BUDGET", "BUDGET_TOTAL_EUR", "TOTAL_BUDGET_EUR"),
    "SP_RATIO": ("SP_BUDGET_RATIO", "SIMPLE_RATIO", "SINGLES_RATIO", "SIMPLE_SHARE"),
    "COMBO_RATIO": ("COMBO_BUDGET_RATIO", "COMBO_SHARE", "COMBINED_RATIO"),
    "MAX_VOL_PAR_CHEVAL": (
        "MAX_VOL_PER_HORSE",
        "MAX_VOL_PER_CHEVAL",
        "MAX_STAKE_PER_HORSE",
        "MAX_STAKE_PAR_CHEVAL",
    ),
    "MIN_PAYOUT_COMBOS": ("EXOTIC_MIN_PAYOUT",),
    "CORRELATION_PENALTY": ("correlation_penalty",),
    "ROR_MAX": ("ROR_MAX_TARGET",),
}

_TRUE_VALUES = {"1", "true", "t", "yes", "y", "on"}
_FALSE_VALUES = {"0", "false", "f", "no", "n", "off"}


def _normalize_key(name: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "", name.upper())


def _build_config_alias_map() -> dict[str, str]:
    alias_map = {_normalize_key(key): key for key in set(REQ_KEYS) | OPTIONAL_KEYS}
    for canonical, aliases in _ENV_ALIASES.items():
        for alias in aliases:
            alias_map[_normalize_key(alias)] = canonical
    alias_map[_normalize_key("EXOTIC_MIN_PAYOUT")] = "EXOTIC_MIN_PAYOUT"
    return alias_map


_CONFIG_KEY_MAP = _build_config_alias_map()


def _resolve_config_key(name: str) -> str | None:
    return _CONFIG_KEY_MAP.get(_normalize_key(name))


def _apply_aliases(raw_cfg: dict) -> dict:
    resolved: dict[str, object] = {}
    for key, value in raw_cfg.items():
        canonical = _resolve_config_key(key)
        if canonical:
            if canonical in resolved and canonical != key:
                continue
            resolved[canonical] = value
        else:
            resolved[key] = value
    return resolved


def _env_aliases(name: str) -> tuple[str, ...]:
    return tuple(_ENV_ALIASES.get(name, ()))


def _as_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in _TRUE_VALUES:
            return True
        if normalized in _FALSE_VALUES:
            return False
    raise ValueError(f"Cannot interpret {value!r} as boolean")  # pragma: no cover - defensive


METRIC_KEYS = {
    "kelly_stake",
    "ev",
    "roi",
    "variance",
    "clv",
    "stake",
    "max_stake",
    "optimized_stake",
    "expected_payout",
    "optimized_expected_payout",
    "sharpe",
    "optimized_sharpe",
}


def summarize_sp_tickets(sp_tickets: list[dict]) -> tuple[float, float, float]:
    """Return EV, ROI and total stake for SP tickets using updated metrics."""

    total_stake = sum(float(t.get("stake", 0.0)) for t in sp_tickets)
    ev_sp = sum(float(t.get("ev", t.get("ev_ticket", 0.0))) for t in sp_tickets)
    roi_sp = ev_sp / total_stake if total_stake > 0 else 0.0
    return ev_sp, roi_sp, total_stake


def simulate_with_metrics(
    tickets: list[dict],
    bankroll: float,
    *,
    kelly_cap: float | None = None,
) -> dict:
    """Run :func:`simulate_ev_batch` on a copy and merge metrics into ``tickets``."""

    if not tickets:
        return {"ev": 0.0, "roi": 0.0}

    simulate_ev_batch_fn = cast(
        Callable[..., dict], _load_simulate_ev()["simulate_ev_batch"]
    )
    sim_input = [copy.deepcopy(t) for t in tickets]
    if kelly_cap is None:
        stats = simulate_ev_batch_fn(sim_input, bankroll=bankroll)
    else:
        stats = simulate_ev_batch_fn(
            sim_input, bankroll=bankroll, kelly_cap=kelly_cap
        )
    for original, simulated in zip(tickets, sim_input):
        for key in METRIC_KEYS:
            if key in simulated:
                original[key] = simulated[key]
    return stats


def _scale_ticket_metrics(ticket: dict, factor: float) -> None:
    """Scale stake-dependent metrics of ``ticket`` in-place."""

    if not math.isfinite(factor):
        return

    for key in ("stake", "kelly_stake", "max_stake", "optimized_stake", "ev", "ev_ticket"):
        if key in ticket and ticket.get(key) is not None:
            ticket[key] = float(ticket[key]) * factor

    if "variance" in ticket and ticket.get("variance") is not None:
        ticket["variance"] = float(ticket["variance"]) * factor * factor


def _normalize_ticket_stakes(
    tickets: list[dict],
    *,
    round_step: float,
    min_stake: float,
) -> bool:
    """Ensure stakes respect ``round_step``/``min_stake``; return True when changed."""

    if not tickets:
        return False

    try:
        step = float(round_step)
    except (TypeError, ValueError):  # pragma: no cover - defensive
        step = 0.0
    if not math.isfinite(step) or step < 0.0:
        step = 0.0

    try:
        floor = float(min_stake)
    except (TypeError, ValueError):  # pragma: no cover - defensive
        floor = 0.0
    if not math.isfinite(floor) or floor < 0.0:
        floor = 0.0

    changed = False
    sanitized: list[dict] = []
    epsilon = 1e-12 if step <= 0 else step * 1e-6

    for ticket in tickets:
        try:
            stake_raw = float(ticket.get("stake", 0.0))
        except (TypeError, ValueError):
            stake_raw = 0.0

        if not math.isfinite(stake_raw) or stake_raw <= 0.0:
            changed = True
            continue

        new_stake = stake_raw
        if step > 0.0:
            new_stake = math.floor((stake_raw + epsilon) / step) * step

        if new_stake < floor - 1e-12 or new_stake <= 0.0:
            changed = True
            continue

        ratio = new_stake / stake_raw if stake_raw else 0.0
        if not math.isfinite(ratio) or ratio <= 0.0:
            changed = True
            continue

        if abs(ratio - 1.0) > 1e-9:
            _scale_ticket_metrics(ticket, ratio)
            ticket["stake"] = float(new_stake)
            changed = True
        else:
            ticket["stake"] = float(new_stake)

        sanitized.append(ticket)

    if len(sanitized) != len(tickets):
        changed = True

    tickets[:] = sanitized
    return changed


def _compute_scale_factor(
    ev: float,
    variance: float,
    target: float,
    bankroll: float,
) -> float | None:
    """Return the multiplicative factor required to reach ``target`` risk."""

    if bankroll <= 0 or ev <= 0 or variance <= 0 or not (0.0 < target < 1.0):
        return None

    ln_target = math.log(target)
    if not math.isfinite(ln_target) or ln_target >= 0.0:
        return None

    denominator = variance * ln_target
    if denominator == 0.0:
        return None

    factor = (-2.0 * ev * bankroll) / denominator
    if not math.isfinite(factor) or factor <= 0.0:
        return None

    return min(1.0, factor)


def _resolve_effective_cap(info: dict | None, cfg: dict) -> float:
    """Return the effective Kelly cap extracted from ``info`` or defaults."""

    cap_default = float(cfg.get("MAX_VOL_PAR_CHEVAL", 0.60))
    if not isinstance(info, dict):
        return cap_default

    for key in ("effective_cap", "max_vol_par_cheval", "initial_cap"):
        value = info.get(key)
        if isinstance(value, (int, float)) and value > 0:
            return float(value)

    return cap_default


def _summarize_optimization(
    tickets: list[dict],
    bankroll: float,
    kelly_cap: float,
) -> dict | None:
    """Return a normalized summary of the optimization run for ``tickets``."""

    if not tickets or bankroll <= 0:
        return None

    pack = [copy.deepcopy(t) for t in tickets]
    simulate_ev_batch_fn = cast(
        Callable[..., dict], _load_simulate_ev()["simulate_ev_batch"]
    )
    stats_opt = simulate_ev_batch_fn(
        pack,
        bankroll=bankroll,
        kelly_cap=kelly_cap,
        optimize=True,
    )

    if not isinstance(stats_opt, dict):
        return None

    optimized_stakes = [float(x) for x in stats_opt.get("optimized_stakes", [])]
    metrics_before = stats_opt.get("ticket_metrics_individual") or []
    stake_before_val = sum(float(m.get("stake", 0.0)) for m in metrics_before)
    if stake_before_val <= 0:
        stake_before_val = sum(float(t.get("stake", 0.0)) for t in tickets)
    stake_before = float(stake_before_val)
    stake_after_val = sum(optimized_stakes) if optimized_stakes else stake_before
    stake_after = float(stake_after_val)

    applied = False
    if optimized_stakes and metrics_before:
        for opt, metrics in zip(optimized_stakes, metrics_before):
            if abs(opt - float(metrics.get("stake", 0.0))) > 1e-6:
                applied = True
                break

    summary: dict[str, object] = {
        "applied": applied,
        "ev_before": float(stats_opt.get("ev_individual", stats_opt.get("ev", 0.0))),
        "ev_after": float(stats_opt.get("ev", stats_opt.get("ev_individual", 0.0))),
        "roi_before": float(
            stats_opt.get("roi_individual", stats_opt.get("roi", 0.0))
        ),
        "roi_after": float(stats_opt.get("roi", stats_opt.get("roi_individual", 0.0))),
        "stake_before": stake_before,
        "stake_after": stake_after,
        "risk_after": float(stats_opt.get("risk_of_ruin", 0.0)),
        "green": bool(stats_opt.get("green", False)),
    }

    if optimized_stakes:
        summary["optimized_stakes"] = optimized_stakes

    failure_reasons = stats_opt.get("failure_reasons")
    if failure_reasons:
        summary["failure_reasons"] = list(failure_reasons)

    return summary


def enforce_ror_threshold(
    cfg: dict,
    runners: list[dict],
    combo_tickets: list[dict],
    bankroll: float,
    *,
    max_iterations: int = 48,
) -> tuple[list[dict], dict, dict]:
    """Return SP tickets and EV metrics after enforcing the ROR threshold."""

    try:
        max_iterations = max(1, int(max_iterations))
    except (TypeError, ValueError):
        max_iterations = 1

    allocate_dutching_sp_fn = cast(
        Callable[[dict, list[dict]], tuple[list[dict], Any]],
        _load_simulate_ev()["allocate_dutching_sp"],
    )

    def _log_variance_drift(stats: dict, context: str) -> None:
        naive = stats.get("variance_naive")
        variance = stats.get("variance")
        if naive is None or variance is None:
            return
        try:
            naive_f = float(naive)
            variance_f = float(variance)
        except (TypeError, ValueError):
            return
        drift = variance_f - naive_f
        if abs(drift) <= 1e-9:
            return
        if math.isfinite(naive_f) and abs(naive_f) > 1e-12:
            pct = (drift / naive_f) * 100.0
            pct_str = f"{pct:.2f}%"
        else:
            pct_str = "inf%" if drift > 0 else "-inf%"
        logger.info(
            "Covariance adjustment (%s): naive=%.6f adjusted=%.6f drift=%.6f (%s)",
            context,
            naive_f,
            variance_f,
            drift,
            pct_str,
        )
        
    cfg_iter = dict(cfg)
    target = float(cfg_iter.get("ROR_MAX", 0.0))
    cap = float(cfg_iter.get("MAX_VOL_PAR_CHEVAL", 0.60))
    try:
        round_step = float(cfg_iter.get("ROUND_TO_SP", 0.0))
    except (TypeError, ValueError):  # pragma: no cover - defensive
        round_step = 0.0
    try:
        min_stake = float(cfg_iter.get("MIN_STAKE_SP", 0.0))
    except (TypeError, ValueError):  # pragma: no cover - defensive
        min_stake = 0.0

    sp_tickets, _ = allocate_dutching_sp_fn(cfg_iter, runners)
    sp_tickets.sort(key=lambda t: t.get("ev_ticket", 0.0), reverse=True)
    try:
        max_count = int(cfg_iter.get("MAX_TICKETS_SP", len(sp_tickets)))
    except (TypeError, ValueError):
        max_count = len(sp_tickets)
    if max_count >= 0:
        sp_tickets = sp_tickets[:max_count]

    _normalize_ticket_stakes(sp_tickets, round_step=round_step, min_stake=min_stake)
    _normalize_ticket_stakes(combo_tickets, round_step=round_step, min_stake=min_stake)
    pack = sp_tickets + combo_tickets
    if not pack:
        stats_ev = {"ev": 0.0, "roi": 0.0, "risk_of_ruin": 0.0, "variance": 0.0}
        info = {
            "applied": False,
            "initial_ror": 0.0,
            "final_ror": 0.0,
            "target": target,
            "scale_factor": 1.0,
            "initial_ev": 0.0,
            "final_ev": 0.0,
            "initial_variance": 0.0,
            "final_variance": 0.0,
            "initial_total_stake": 0.0,
            "final_total_stake": 0.0,
        }
        return sp_tickets, stats_ev, info

    stats_ev = simulate_with_metrics(pack, bankroll=bankroll, kelly_cap=cap)
    _log_variance_drift(stats_ev, "initial")

    initial_risk = float(stats_ev.get("risk_of_ruin", 0.0))
    initial_ev = float(stats_ev.get("ev", 0.0))
    initial_variance = float(stats_ev.get("variance", 0.0))
    initial_total_stake = sum(float(t.get("stake", 0.0)) for t in pack)

    reduction_applied = False
    scale_factor_total = 1.0
    stats_current = stats_ev
    effective_cap = cap

    iterations = 0
    if initial_risk > target and bankroll > 0:
        while iterations < max_iterations:
            current_risk = float(stats_current.get("risk_of_ruin", 0.0))
            if current_risk <= target + 1e-9:
                break

            factor = _compute_scale_factor(
                float(stats_current.get("ev", 0.0)),
                float(stats_current.get("variance", 0.0)),
                target,
                bankroll,
            )
            if factor is None or factor >= 1.0 - 1e-9:
                break
        
            reduction_applied = True
            scale_factor_total *= factor
            effective_cap = cap * scale_factor_total
            for ticket in pack:
                _scale_ticket_metrics(ticket, factor)

            _normalize_ticket_stakes(sp_tickets, round_step=round_step, min_stake=min_stake)
            _normalize_ticket_stakes(combo_tickets, round_step=round_step, min_stake=min_stake)
            pack = sp_tickets + combo_tickets
            if not pack:
                stats_current = {"ev": 0.0, "roi": 0.0, "risk_of_ruin": 0.0, "variance": 0.0}
                break

            stats_current = simulate_with_metrics(
                pack,
                bankroll=bankroll,
                kelly_cap=effective_cap,
            )
            _log_variance_drift(stats_current, f"iteration {iterations + 1}")

            iterations += 1
            if factor <= 1e-6:
                break

        stats_ev = stats_current

    final_risk = float(stats_ev.get("risk_of_ruin", initial_risk))
    final_ev = float(stats_ev.get("ev", initial_ev))
    final_variance = float(stats_ev.get("variance", initial_variance))
    pack = sp_tickets + combo_tickets
    final_total_stake = sum(float(t.get("stake", 0.0)) for t in pack)
    scale_factor_effective = scale_factor_total
    if initial_total_stake > 0.0:
        computed_scale = final_total_stake / initial_total_stake
        if math.isfinite(computed_scale) and computed_scale >= 0.0:
            scale_factor_effective = computed_scale

    info = {
        "applied": reduction_applied,        
        "initial_ror": float(initial_risk),
        "final_ror": float(final_risk),
        "target": target,
        "scale_factor": scale_factor_effective,
        "initial_ev": initial_ev,
        "final_ev": final_ev,
        "initial_variance": initial_variance,
        "final_variance": final_variance,
        "initial_total_stake": initial_total_stake,
        "final_total_stake": final_total_stake,
        "initial_cap": cap,
        "effective_cap": effective_cap,
        "iterations": iterations,
    }

    return sp_tickets, stats_ev, info


def load_yaml(path: str) -> dict:
    import yaml

    _maybe_load_dotenv()

    with open(path, "r", encoding="utf-8") as fh:
        raw_cfg = yaml.safe_load(fh) or {}

    cfg = _apply_aliases(raw_cfg)

    cfg.setdefault("ALLOW_JE_NA", False)
    cfg.setdefault("PAUSE_EXOTIQUES", False)
    cfg.setdefault("MAX_VOL_PAR_CHEVAL", 0.60)
    cfg.setdefault("REQUIRE_DRIFT_LOG", True)
    cfg.setdefault("REQUIRE_ODDS_WINDOWS", [30, 5])
    cfg.setdefault("MAX_TICKETS_SP", 2)
    cfg.setdefault("DRIFT_COEF", 0.05)
    cfg.setdefault("JE_BONUS_COEF", 0.001)
    cfg.setdefault("KELLY_FRACTION", 0.5)
    cfg.setdefault("MIN_STAKE_SP", 0.1)
    cfg.setdefault("ROUND_TO_SP", 0.10)
    cfg.setdefault("ROI_MIN_SP", 0.10)
    cfg.setdefault("ROI_MIN_GLOBAL", 0.25)
    cfg.setdefault("ROR_MAX", 0.01)
    cfg.setdefault("SHARPE_MIN", 0.5)
    cfg.setdefault("SNAPSHOTS", "H30,H5")
    cfg.setdefault("DRIFT_TOP_N", 5)
    cfg.setdefault("DRIFT_MIN_DELTA", 0.8)
    cfg.setdefault("P_TRUE_MIN_SAMPLES", 0)
    
    payout_default = cfg.get("EXOTIC_MIN_PAYOUT", cfg.get("MIN_PAYOUT_COMBOS"))
    if payout_default is None:
        payout_default = 12.0
    cfg["MIN_PAYOUT_COMBOS"] = payout_default
    cfg["EXOTIC_MIN_PAYOUT"] = payout_default

    cfg["SNAPSHOTS"] = get_env("SNAPSHOTS", cfg.get("SNAPSHOTS"), aliases=_env_aliases("SNAPSHOTS"))
    cfg["DRIFT_TOP_N"] = get_env(
        "DRIFT_TOP_N",
        cfg.get("DRIFT_TOP_N"),
        cast=int,
    )
    cfg["DRIFT_MIN_DELTA"] = get_env(
        "DRIFT_MIN_DELTA",
        cfg.get("DRIFT_MIN_DELTA"),
        cast=float,
    )
    cfg["P_TRUE_MIN_SAMPLES"] = get_env(
        "P_TRUE_MIN_SAMPLES",
        cfg.get("P_TRUE_MIN_SAMPLES"),
        cast=float,
    )
    cfg["BUDGET_TOTAL"] = get_env(
        "BUDGET_TOTAL",
        cfg.get("BUDGET_TOTAL"),
        cast=float,
        aliases=_env_aliases("BUDGET_TOTAL"),
    )
    cfg["SP_RATIO"] = get_env(
        "SP_RATIO",
        cfg.get("SP_RATIO"),
        cast=float,
        aliases=_env_aliases("SP_RATIO"),
    )
    cfg["COMBO_RATIO"] = get_env(
        "COMBO_RATIO",
        cfg.get("COMBO_RATIO"),
        cast=float,
        aliases=_env_aliases("COMBO_RATIO"),
    )
    cfg["MAX_VOL_PAR_CHEVAL"] = get_env(
        "MAX_VOL_PAR_CHEVAL",
        cfg.get("MAX_VOL_PAR_CHEVAL"),
        cast=float,
        aliases=_env_aliases("MAX_VOL_PAR_CHEVAL"),
    )  
    cfg["EV_MIN_SP"] = get_env("EV_MIN_SP", cfg.get("EV_MIN_SP"), cast=float)
    cfg["EV_MIN_GLOBAL"] = get_env("EV_MIN_GLOBAL", cfg.get("EV_MIN_GLOBAL"), cast=float)
    cfg["ROI_MIN_SP"] = get_env("ROI_MIN_SP", cfg.get("ROI_MIN_SP"), cast=float)
    cfg["ROI_MIN_GLOBAL"] = get_env("ROI_MIN_GLOBAL", cfg.get("ROI_MIN_GLOBAL"), cast=float)
    cfg["ROR_MAX"] = get_env(
        "ROR_MAX",
        cfg.get("ROR_MAX"),
        cast=float,
        aliases=_env_aliases("ROR_MAX"),
    )
    cfg["SHARPE_MIN"] = get_env("SHARPE_MIN", cfg.get("SHARPE_MIN"), cast=float)
    cfg["MAX_TICKETS_SP"] = get_env("MAX_TICKETS_SP", cfg.get("MAX_TICKETS_SP"), cast=int)
    cfg["MIN_STAKE_SP"] = get_env("MIN_STAKE_SP", cfg.get("MIN_STAKE_SP"), cast=float)
    cfg["DRIFT_COEF"] = get_env("DRIFT_COEF", cfg.get("DRIFT_COEF"), cast=float)
    cfg["ROUND_TO_SP"] = get_env("ROUND_TO_SP", cfg.get("ROUND_TO_SP"), cast=float)
    cfg["JE_BONUS_COEF"] = get_env("JE_BONUS_COEF", cfg.get("JE_BONUS_COEF"), cast=float)
    cfg["KELLY_FRACTION"] = get_env("KELLY_FRACTION", cfg.get("KELLY_FRACTION"), cast=float)
    cfg["ALLOW_JE_NA"] = get_env("ALLOW_JE_NA", cfg.get("ALLOW_JE_NA"), cast=_as_bool)
    cfg["PAUSE_EXOTIQUES"] = get_env("PAUSE_EXOTIQUES", cfg.get("PAUSE_EXOTIQUES"), cast=_as_bool)
    cfg["REQUIRE_DRIFT_LOG"] = get_env("REQUIRE_DRIFT_LOG", cfg.get("REQUIRE_DRIFT_LOG"), cast=_as_bool)
    cfg["MIN_PAYOUT_COMBOS"] = get_env(
        "MIN_PAYOUT_COMBOS",
        cfg.get("MIN_PAYOUT_COMBOS"),
        cast=float,
        aliases=_env_aliases("MIN_PAYOUT_COMBOS"),
    )
    cfg["EXOTIC_MIN_PAYOUT"] = cfg["MIN_PAYOUT_COMBOS"]

    corr_default = cfg.get("CORRELATION_PENALTY", 0.85)
    cfg["CORRELATION_PENALTY"] = get_env(
        "CORRELATION_PENALTY",
        corr_default,
        cast=float,
        aliases=_env_aliases("CORRELATION_PENALTY"),
    )
    
    missing = [k for k in REQ_KEYS if k not in cfg]
    if missing:
        raise RuntimeError(f"Config incomplète: clés manquantes {missing}")
    if float(cfg["SP_RATIO"]) + float(cfg["COMBO_RATIO"]) > 1.0:
        raise RuntimeError("SP_RATIO + COMBO_RATIO doit être <= 1.0")
    return cfg


def load_json(path: str):    
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def save_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def save_text(path: Path, txt: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(txt, encoding="utf-8")


def _coerce_odds(value) -> float:
    try:
        odds = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(odds):
        return 0.0
    return max(odds, 0.0)


def _coerce_probability(value) -> float:
    try:
        prob = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(prob):
        return 0.0
    return max(prob, 0.0)


def _normalize_probability_map(prob_map: dict[str, float], ids: list[str]) -> dict[str, float]:
    sanitized = {cid: _coerce_probability(prob_map.get(cid, 0.0)) for cid in ids}
    total = sum(sanitized.values())
    if total <= 0:
        return {cid: 0.0 for cid in ids}
    return {cid: value / total for cid, value in sanitized.items()}


def _implied_from_odds_map(odds_map: dict[str, float]) -> dict[str, float]:
    if not odds_map:
        return {}
    ids = list(odds_map.keys())
    values = [_coerce_odds(odds_map[cid]) for cid in ids]
    implied_probs_fn = cast(
        Callable[[list[float]], list[float]], _load_simulate_ev()["implied_probs"]
    )
    probs = implied_probs_fn(values)
    implied = {}
    for cid, odds, prob in zip(ids, values, probs):
        implied[cid] = prob if odds > 0 else 0.0
    for cid in ids:
        implied.setdefault(cid, 0.0)
    return implied


def _snapshot_odds_and_probs(snapshot) -> tuple[dict[str, float], dict[str, float]]:
    odds_map: dict[str, float] = {}
    implied: dict[str, float] = {}

    if isinstance(snapshot, dict):
        raw_odds = None
        for key in ("odds", "odds_map", "cotes"):
            raw_odds = snapshot.get(key)
            if isinstance(raw_odds, dict):
                break
        if isinstance(raw_odds, dict):
            for cid, value in raw_odds.items():
                odds_map[str(cid)] = _coerce_odds(value)
        runners = snapshot.get("runners")
        if isinstance(runners, list):
            for runner in runners:
                if not isinstance(runner, dict):
                    continue
                cid = runner.get("id")
                if cid is None:
                    continue
                cid_str = str(cid)
                odds_map[cid_str] = _coerce_odds(runner.get("odds"))
                if "p_imp" in runner:
                    implied[cid_str] = _coerce_probability(runner.get("p_imp"))
                elif "p_implied" in runner:
                    implied[cid_str] = _coerce_probability(runner.get("p_implied"))
        if not odds_map:
            for cid, value in snapshot.items():
                if isinstance(value, (dict, list)):
                    continue
                try:
                    odds = float(value)
                except (TypeError, ValueError):
                    continue
                if not math.isfinite(odds):
                    continue
                odds_map[str(cid)] = max(odds, 0.0)
        raw_probs = None
        for key in ("p_imp", "implied_probabilities", "implied", "probabilities"):
            candidate = snapshot.get(key)
            if isinstance(candidate, dict):
                raw_probs = candidate
                break
        if isinstance(raw_probs, dict):
            for cid, value in raw_probs.items():
                implied[str(cid)] = _coerce_probability(value)
    elif isinstance(snapshot, list):
        for runner in snapshot:
            if not isinstance(runner, dict):
                continue
            cid = runner.get("id")
            if cid is None:
                continue
            cid_str = str(cid)
            odds_map[cid_str] = _coerce_odds(runner.get("odds"))
            if "p_imp" in runner:
                implied[cid_str] = _coerce_probability(runner.get("p_imp"))
            elif "p_implied" in runner:
                implied[cid_str] = _coerce_probability(runner.get("p_implied"))

    ids = list(odds_map.keys())
    if not ids:
        return {}, {}

    if implied:
        implied = _normalize_probability_map(implied, ids)
    else:
        implied = _implied_from_odds_map({cid: odds_map[cid] for cid in ids})

    # Ensure odds_map includes sanitized floats aligned with ids order
    odds_map = {cid: _coerce_odds(odds_map[cid]) for cid in ids}
    implied = {cid: implied.get(cid, 0.0) for cid in ids}
    return odds_map, implied


def _as_recent_form_flag(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return float(value) != 0.0
    if isinstance(value, str):
        normalized = value.strip().lower()
        if not normalized:
            return False
        return normalized in {"1", "true", "yes", "y", "oui", "o", "vrai", "top3", "top 3"}
    return False


def compute_drift_dict(
    h30: dict,
    h5: dict,
    id2name: dict,
    *,
    top_n: int | None = None,
    min_delta: float = 0.0,
) -> dict:
    """Compute odds drift between two snapshots.

    Parameters
    ----------
    h30, h5 : dict
        Mapping of ``id`` -> cote at H-30 and H-5 respectively.
    id2name : dict
        Mapping ``id`` -> human readable name.
    top_n : int, optional
        Number of top steams/drifts to retain on each side.
    min_delta : float
        Minimum absolute odds variation required to be kept.

    Returns
    -------
    dict
        A dictionary containing the per-runner drift as well as lists of
        identifiers missing from either snapshot.
    """

    diff = []
    for cid in set(h30) & set(h5):
        delta = float(h5[cid]) - float(h30[cid])
        if abs(delta) < float(min_delta):
            continue
        diff.append(
            {
                "id": cid,
                "name": id2name.get(cid, cid),
                "cote_h30": float(h30[cid]),
                "cote_h5": float(h5[cid]),
                "delta": delta,
            }
        )
    diff.sort(key=lambda r: r["delta"])
    if top_n is not None:
        neg = [r for r in diff if r["delta"] < 0][: int(top_n)]
        pos = [r for r in reversed(diff) if r["delta"] > 0][: int(top_n)]
        diff = sorted(neg + pos, key=lambda r: r["delta"])
    for rank, row in enumerate(diff, start=1):
        row["rank_delta"] = rank
        
    missing_h30 = sorted(set(h5) - set(h30))
    missing_h5 = sorted(set(h30) - set(h5))

    return {"drift": diff, "missing_h30": missing_h30, "missing_h5": missing_h5}


def _heuristic_p_true(cfg, partants, odds_h5, odds_h30, stats_je) -> dict:
    weights = {}
    for p in partants:
        cid = str(p["id"])
        if cid not in odds_h5:
            continue
        o5 = float(odds_h5[cid])
        base = 1.0 / o5
        je = stats_je.get(cid, {})
        bonus = (je.get("j_win", 0) + je.get("e_win", 0)) * float(cfg["JE_BONUS_COEF"])
        drift = o5 - float(odds_h30.get(cid, o5))
        coef = float(cfg.get("DRIFT_COEF", 0.05))
        weight = base * (1.0 + bonus) * (1.0 - coef * drift)
        weights[cid] = max(weight, 0.0)
    total = sum(weights.values()) or 1.0
    return {cid: w / total for cid, w in weights.items()}


def _coerce_positive_count(value) -> float | None:
    if isinstance(value, (int, float)):
        if not math.isfinite(value) or value < 0:
            return None
        return float(value)
    if isinstance(value, str):
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(parsed) or parsed < 0:
            return None
        return float(parsed)
    return None


def build_p_true(cfg, partants, odds_h5, odds_h30, stats_je) -> dict:
    helpers = _load_p_true_helpers()
    load_model = cast(Callable[[], Any], helpers["load_p_true_model"])
    get_metadata = cast(Callable[[Any], dict], helpers["get_model_metadata"])
    compute_features = cast(
        Callable[[float, float | None, dict | None], Any],
        helpers["compute_runner_features"],
    )
    predict_prob = cast(Callable[[Any, Any], float], helpers["predict_probability"])

    model = None
    try:
        model = load_model()
    except Exception as exc:  # pragma: no cover - corrupted file
        logger.warning("Impossible de charger le modèle p_true: %s", exc)
        model = None

    if model is not None:
        min_samples = float(cfg.get("P_TRUE_MIN_SAMPLES", 0) or 0)
        if min_samples > 0:
            metadata = get_metadata(model)
            sample_count = _coerce_positive_count(metadata.get("n_samples"))
            race_count = _coerce_positive_count(metadata.get("n_races"))
            too_few_samples = sample_count is None or sample_count < min_samples
            too_few_races = race_count is None or race_count < min_samples
            if too_few_samples or too_few_races:
                logger.warning(
                    "Calibration p_true ignorée: n_samples=%s n_races=%s (seuil=%s)",
                    "n/a" if sample_count is None else sample_count,
                    "n/a" if race_count is None else race_count,
                    min_samples,
                )
                return _heuristic_p_true(cfg, partants, odds_h5, odds_h30, stats_je)

        probs = {}
        for p in partants:
            cid = str(p.get("id"))
            if cid not in odds_h5:
                continue
            try:
                features = compute_features(
                    float(odds_h5[cid]),
                    float(odds_h30.get(cid, odds_h5[cid])) if odds_h30 else None,
                    stats_je.get(cid) if stats_je else None,
                )
            except (ValueError, TypeError):
                continue
            prob = predict_prob(model, features)
            probs[cid] = prob

        total = sum(probs.values())
        if total > 0:
            return {cid: prob / total for cid, prob in probs.items()}
        logger.info("Calibration p_true indisponible, retour à l'heuristique")

    return _heuristic_p_true(cfg, partants, odds_h5, odds_h30, stats_je)


def export(
    outdir: Path,
    meta: dict,
    tickets: list,
    ev_sp: float,
    ev_global: float,
    roi_sp: float,
    roi_global: float,
    risk_of_ruin: float,
    clv_moyen: float,
    variance: float,
    combined_payout: float,
    p_true: dict,
    drift: dict,
    cfg: dict,
    *,
    stake_reduction_applied: bool = False,
    stake_reduction_details: dict | None = None,
    optimization_details: dict | None = None,
) -> None:
    save_json(
        outdir / "p_finale.json",
        {
            "meta": meta,
            "p_true": p_true,
            "tickets": tickets,
            "ev": {
                "sp": ev_sp,
                "global": ev_global,
                "roi_sp": roi_sp,
                "roi_global": roi_global,
                "risk_of_ruin": risk_of_ruin,
                "clv_moyen": clv_moyen,
                "variance": variance,
                "combined_expected_payout": combined_payout,
                "stake_reduction_applied": bool(stake_reduction_applied),
                "stake_reduction": {
                    "applied": bool(stake_reduction_applied),
                    "scale_factor": (
                        stake_reduction_details.get("scale_factor")
                        if stake_reduction_details
                        else None
                    ),
                    "target": (
                        stake_reduction_details.get("target")
                        if stake_reduction_details
                        else None
                    ),
                    "initial_cap": (
                        stake_reduction_details.get("initial_cap")
                        if stake_reduction_details
                        else None
                    ),
                    "effective_cap": (
                        stake_reduction_details.get("effective_cap")
                        if stake_reduction_details
                        else None
                    ),
                    "iterations": (
                        stake_reduction_details.get("iterations")
                        if stake_reduction_details
                        else None
                    ),
                    "initial": (
                        stake_reduction_details.get("initial")
                        if stake_reduction_details
                        else {}
                    ),
                    "final": (
                        stake_reduction_details.get("final")
                        if stake_reduction_details
                        else {}
                    ),
                },
                "optimization": optimization_details,
            },
        },
    )
    drift_out = dict(drift)
    drift_out["params"] = {
        "snapshots": cfg.get("SNAPSHOTS"),
        "top_n": cfg.get("DRIFT_TOP_N"),
        "min_delta": cfg.get("DRIFT_MIN_DELTA"),
    }
    save_json(outdir / "diff_drift.json", drift_out)
    total = sum(t.get("stake", 0) for t in tickets)
    ligne = (
        f'{meta.get("rc", "R?C?")};{meta.get("hippodrome", "")};'
        f'{meta.get("date", "")};{meta.get("discipline", "")};'
        f'{total:.2f};{ev_global:.4f};{cfg.get("MODEL", "")}'
    )
    save_text(
        outdir / "ligne.csv",
        "R/C;hippodrome;date;discipline;mises;EV_globale;model\n" + ligne + "\n",
    )
    cmd = (
        f'python update_excel_with_results.py '
        f'--excel "{cfg.get("EXCEL_PATH")}" '
        f'--arrivee "{outdir / "arrivee_officielle.json"}" '
        f'--tickets "{outdir / "p_finale.json"}"\n'
    )
    save_text(outdir / "cmd_update_excel.txt", cmd)

# ---------------------------------------------------------------------------
# Analyse helper
# ---------------------------------------------------------------------------


def cmd_analyse(args: argparse.Namespace) -> None:
    import simulate_wrapper as sw
    from logging_io import CSV_HEADER, append_csv_line, append_json
    from tickets_builder import allow_combo, apply_ticket_policy
    from validator_ev import (
        combos_allowed as combos_ev_gate,
        summarise_validation,
        validate_inputs,
    )

    cfg = load_yaml(args.gpi)
    output_dir = _resolve_output_dir()
    cfg["OUTDIR_DEFAULT"] = output_dir
    print(f"[pipeline] Export local only → {output_dir}")
    if args.budget is not None:
        cfg["BUDGET_TOTAL"] = args.budget
    if args.ev_global is not None:
        cfg["EV_MIN_GLOBAL"] = args.ev_global
    if args.roi_global is not None:
        cfg["ROI_MIN_GLOBAL"] = args.roi_global
    if args.max_vol is not None:
        cfg["MAX_VOL_PAR_CHEVAL"] = args.max_vol
    if args.min_payout is not None:
        cfg["MIN_PAYOUT_COMBOS"] = args.min_payout
    if args.allow_je_na:
        cfg["ALLOW_JE_NA"] = True

    # Exotic thresholds / heuristics overrides
    if args.ev_min_exotic is not None:
        ev_min_exotic = float(args.ev_min_exotic)
    else:
        ev_min_exotic = float(
            cfg.get("EV_MIN_EXOTIC", cfg.get("EV_MIN_COMBO", EXOTIC_BASE_EV))
        )
    ev_min_exotic = max(ev_min_exotic, EXOTIC_BASE_EV)
    cfg["EV_MIN_EXOTIC"] = ev_min_exotic

    if args.payout_min_exotic is not None:
        payout_min_exotic = float(args.payout_min_exotic)
    else:
        payout_min_exotic = float(
            cfg.get(
                "PAYOUT_MIN_EXOTIC",
                cfg.get(
                    "EXOTIC_MIN_PAYOUT",
                    cfg.get("MIN_PAYOUT_COMBOS", EXOTIC_BASE_PAYOUT),
                ),
            )
        )
    payout_min_exotic = max(payout_min_exotic, EXOTIC_BASE_PAYOUT)
    cfg["PAYOUT_MIN_EXOTIC"] = payout_min_exotic

    allow_heuristic = bool(args.allow_heuristic)

    sim_helpers = _load_simulate_ev()
    allocate_dutching_sp_fn = cast(
        Callable[[dict, list[dict]], tuple[list[dict], Any]],
        sim_helpers["allocate_dutching_sp"],
    )
    gate_ev_fn = cast(Callable[..., dict], sim_helpers["gate_ev"])

    sw.set_correlation_penalty(cfg.get("CORRELATION_PENALTY"))

    outdir = Path(args.outdir or cfg["OUTDIR_DEFAULT"])

    raw_h30 = load_json(args.h30)
    odds_h30, p_imp_h30 = _snapshot_odds_and_probs(raw_h30)
    raw_h5 = load_json(args.h5)
    odds_h5, p_imp_h5 = _snapshot_odds_and_probs(raw_h5)
    stats_je = load_json(args.stats_je)
    partants_data = load_json(args.partants)

    partants = partants_data.get("runners", [])
    id2name = partants_data.get(
        "id2name", {str(p["id"]): p.get("name", str(p["id"])) for p in partants}
    )
    rc = partants_data.get("rc", "R?C?")
    if "C" in rc:
        reunion_part, course_part = rc.split("C", 1)
        reunion = reunion_part
        course = f"C{course_part}"
    else:
        reunion = rc
        course = ""
    meta = {
        "rc": rc,
        "reunion": reunion,
        "course": course,
        "hippodrome": partants_data.get("hippodrome", ""),
        "date": partants_data.get("date", dt.date.today().isoformat()),
        "discipline": partants_data.get("discipline", ""),
        "model": cfg.get("MODEL", ""),
        "snapshots": cfg.get("SNAPSHOTS"),
        "drift_top_n": cfg.get("DRIFT_TOP_N"),
        "drift_min_delta": cfg.get("DRIFT_MIN_DELTA"),
    }

    if not isinstance(stats_je, dict):
        stats_je = {}
    if "coverage" not in stats_je:
        runner_ids = {
            str(p.get("id"))
            for p in partants
            if p.get("id") is not None
        }
        stats_ids = {
            str(cid)
            for cid, payload in stats_je.items()
            if cid != "coverage" and isinstance(payload, dict)
        }
        total = len(runner_ids)
        matched = len(runner_ids & stats_ids)
        stats_je["coverage"] = round(100.0 * matched / total, 2) if total else 0.0

    # Validation
    validate_inputs_call = partial(validate_inputs, cfg, partants, odds_h5, stats_je)
    validation_summary = summarise_validation(validate_inputs_call)
    meta["validation"] = dict(validation_summary)
    if not validation_summary["ok"]:
        logger.error("Validation failed: %s", validation_summary["reason"])
        validate_inputs_call()

    # Drift & p_true
    if args.diff:
        drift = load_json(args.diff)
    else:
        drift = compute_drift_dict(
            odds_h30,
            odds_h5,
            id2name,
            top_n=int(cfg.get("DRIFT_TOP_N", 0)),
            min_delta=float(cfg.get("DRIFT_MIN_DELTA", 0.0)),
        )
    p_true = build_p_true(cfg, partants, odds_h5, odds_h30, stats_je)

    # Tickets allocation
    favorite_ids: set[str] = set()
    if odds_h5:
        try:
            odds_pairs = [
                (str(cid), float(val))
                for cid, val in odds_h5.items()
                if val not in (None, "")
            ]
            odds_pairs = [pair for pair in odds_pairs if pair[1] > 0.0]
        except (TypeError, ValueError):
            odds_pairs = []
        if odds_pairs:
            min_odds = min(price for _, price in odds_pairs)
            tolerance = 1e-6
            favorite_ids = {
                cid for cid, price in odds_pairs if price <= min_odds + tolerance
            }

    runners = []
    for p in partants:
        cid = str(p["id"])
        if cid in odds_h5 and cid in p_true:
            p_imp5 = _coerce_probability(p_imp_h5.get(cid, 0.0)) if p_imp_h5 else 0.0
            p_imp30 = _coerce_probability(p_imp_h30.get(cid, 0.0)) if p_imp_h30 else 0.0
            if p_imp30 <= 0.0:
                p_imp30 = p_imp5
            odds_current = float(odds_h5[cid])
            prev_raw = odds_h30.get(cid) if odds_h30 else None
            try:
                odds_prev = float(prev_raw) if prev_raw not in (None, "") else None
            except (TypeError, ValueError):
                odds_prev = None
            if odds_prev is None:
                odds_prev = odds_current
            prob_delta = drift_points(odds_prev, odds_current)
            drift_score = market_drift_signal(
                odds_prev,
                odds_current,
                is_favorite=cid in favorite_ids,
            )
            raw_drift_odds = odds_current - odds_prev
            raw_stats = stats_je.get(cid) if isinstance(stats_je, dict) else None
            je_stats = raw_stats if isinstance(raw_stats, dict) else {}
            runner = {
                "id": cid,
                "name": p.get("name", cid),
                "odds": odds_current,
                "p": float(p_true[cid]),
                "p_imp_h5": p_imp5,
                "p_imp_h30": p_imp30,
                "drift_prob_delta": prob_delta,
                "drift_odds_delta": raw_drift_odds,
                "market_signal": drift_score,
                "drift_score": prob_delta,
                "last2_top3": _as_recent_form_flag(je_stats.get("last2_top3")),
                "is_favorite": cid in favorite_ids,
            }
            runners.append(runner)

    sp_tickets, combo_templates, _combo_info = apply_ticket_policy(
        cfg,
        runners,
        combo_candidates=None,
        combos_source=partants_data,
        ev_threshold=ev_min_exotic,
        payout_threshold=payout_min_exotic,
        allow_heuristic=allow_heuristic,
    )

    ev_sp = 0.0
    total_stake_sp = 0.0
    roi_sp = 0.0

    combo_budget = float(cfg.get("BUDGET_TOTAL", 0.0)) * float(cfg.get("COMBO_RATIO", 0.0))
    
    combo_info = {
        "notes": list(_combo_info.get("notes", [])) if isinstance(_combo_info, Mapping) else [],
        "flags": {},
    }
    if isinstance(_combo_info, Mapping):
        flags_raw = _combo_info.get("flags")
        if isinstance(flags_raw, Mapping):
            combo_info["flags"] = {k: copy.deepcopy(v) for k, v in flags_raw.items()}
        decision_raw = _combo_info.get("decision")
        if isinstance(decision_raw, str):
            combo_info["decision"] = decision_raw

    combo_flags = combo_info.setdefault("flags", {})
    reasons_map = combo_flags.setdefault("reasons", {})
    reasons_list = reasons_map.setdefault("combo", [])

    combo_info["thresholds"] = {
        "ev_min": ev_min_exotic,
        "payout_min": payout_min_exotic,
        "allow_heuristic": allow_heuristic,
        "ev_accept_min": EXOTIC_BASE_EV,
        "payout_accept_min": EXOTIC_BASE_PAYOUT,
    }

    filtered_templates: list[dict] = []
    filter_reasons: list[str] = []
    for template in combo_templates:
        bankroll_for_eval = combo_budget if combo_budget > 0 else float(template.get("stake", 0.0))
        if bankroll_for_eval <= 0:
            bankroll_for_eval = 1.0
        stats = sw.evaluate_combo([
            template,
        ], bankroll_for_eval, allow_heuristic=False)
        status = str(stats.get("status") or "").lower()
        ev_ratio = float(stats.get("ev_ratio", 0.0))
        payout_expected = float(stats.get("payout_expected", 0.0))
        roi_val = float(stats.get("roi", 0.0))
        sharpe_val = float(stats.get("sharpe", 0.0))

        template_copy = dict(template)
        template_copy["ev_check"] = {
            "ev_ratio": ev_ratio,
            "roi": roi_val,
            "payout_expected": payout_expected,
            "sharpe": sharpe_val,
        }

        if status != "ok":
            filter_reasons.append(f"status_{status or 'unknown'}")
            continue
        if ev_ratio < EXOTIC_BASE_EV:
            filter_reasons.append("ev_ratio_below_accept_threshold")
            if ev_ratio < ev_min_exotic:
                filter_reasons.append("ev_ratio_below_pipeline_threshold")
            continue
        if payout_expected < EXOTIC_BASE_PAYOUT:
            filter_reasons.append("payout_expected_below_accept_threshold")
            if payout_expected < payout_min_exotic:
                filter_reasons.append("payout_below_pipeline_threshold")
            continue
        if ev_ratio < ev_min_exotic:
            filter_reasons.append("ev_ratio_below_pipeline_threshold")
            continue
        if payout_expected < payout_min_exotic:
            filter_reasons.append("payout_below_pipeline_threshold")
            continue

        filtered_templates.append(template_copy)

    if filter_reasons:
        for reason in filter_reasons:
            if reason not in reasons_list:
                reasons_list.append(reason)

    if filtered_templates:
        combo_templates = filtered_templates
        combo_info.setdefault("decision", "accept")
    else:
        combo_templates = []
        decision_reason = ",".join(dict.fromkeys(filter_reasons)) if filter_reasons else "no_candidate"
        combo_info["decision"] = f"reject:{decision_reason}"

    combo_tickets: list[dict] = []
    if combo_templates and combo_budget > 0:
        weights = [max(float(t.get("stake", 0.0)), 0.0) for t in combo_templates]
        total_weight = sum(weights)
        if total_weight <= 0:
            weights = [1.0] * len(combo_templates)
            total_weight = float(len(combo_templates))
        for template, weight in zip(combo_templates, weights):
            ticket = dict(template)
            ticket["stake"] = combo_budget * (weight / total_weight)
            combo_tickets.append(ticket)

    sp_tickets, combo_tickets, guard_notes = _filter_sp_and_cp_tickets(
        sp_tickets,
        combo_tickets,
        runners,
        partants_data,
    )
    if guard_notes:
        notes_bucket = meta.setdefault("notes", [])
        if isinstance(notes_bucket, list):
            for note in guard_notes:
                if note not in notes_bucket:
                    notes_bucket.append(note)
        else:
            meta["notes"] = list(guard_notes)
        for note in guard_notes:
            if note not in combo_info["notes"]:
                combo_info["notes"].append(note)

    bankroll = float(cfg.get("BUDGET_TOTAL", 0.0))
    
    def log_reduction(info: dict) -> None:
        logger.warning(
            (
                "Risk of ruin %.2f%% > %.2f%%: réduction globale s=%.3f "
                "(mise %.2f→%.2f, variance %.2f→%.2f, cap %.2f→%.2f, "
                "risque final %.2f%%, %d itérations)"
            ),
            info.get("initial_ror", 0.0) * 100.0,
            info.get("target", 0.0) * 100.0,
            info.get("scale_factor", 1.0),
            info.get("initial_total_stake", 0.0),
            info.get("final_total_stake", 0.0),
            info.get("initial_variance", 0.0),
            info.get("final_variance", 0.0),
            info.get("initial_cap", 0.0),
            info.get("effective_cap", 0.0),
            info.get("final_ror", 0.0) * 100.0,
            int(info.get("iterations", 0)),
        )

    def adjust_pack(cfg_local: dict, combos_local: list[dict]) -> tuple[list[dict], dict, dict]:
        sp_adj, stats_local, info_local = enforce_ror_threshold(
            cfg_local,
            runners,
            combos_local,
            bankroll=bankroll,
        )
        if info_local.get("applied"):
            log_reduction(info_local)
        return sp_adj, stats_local, info_local

    sp_tickets, stats_ev, reduction_info = adjust_pack(cfg, combo_tickets)
    last_reduction_info = reduction_info

    ev_sp, roi_sp, total_stake_sp = summarize_sp_tickets(sp_tickets)
    ev_global = float(stats_ev.get("ev", 0.0))
    roi_global = float(stats_ev.get("roi", 0.0))
    combined_payout = float(stats_ev.get("combined_expected_payout", 0.0))
    risk_of_ruin = float(stats_ev.get("risk_of_ruin", 0.0))
    ev_over_std = float(stats_ev.get("ev_over_std", 0.0))

    proposed_pack = sp_tickets + combo_tickets

    homogeneous_field = bool(
        cfg.get("HOMOGENEOUS_FIELD")
        or cfg.get("homogeneous_field")
        or stats_ev.get("homogeneous_field", False)
    )

    flags = gate_ev_fn(
        cfg,
        ev_sp,
        ev_global,
        roi_sp,
        roi_global,
        combined_payout,
        risk_of_ruin,
        ev_over_std,
        homogeneous_field=homogeneous_field,
    )

    combo_ok = bool(combo_tickets) and flags.get("sp") and flags.get("combo")
    if combo_ok:
        strict_ev = max(ev_min_exotic, float(cfg.get("EV_MIN_GLOBAL", 0.0)))
        strict_payout = max(payout_min_exotic, float(cfg.get("MIN_PAYOUT_COMBOS", 0.0)))
        combo_ok = combos_ev_gate(
            ev_global,
            combined_payout,
            min_ev=strict_ev,
            min_payout=strict_payout,
        )
    if combo_ok:
        combo_ok = allow_combo(ev_global, roi_global, combined_payout)
    if combo_ok:
        combo_ok = allow_combo(
            ev_global,
            roi_global,
            combined_payout,
            cfg=cfg,
        )
        if combo_ok is False and combo_tickets:
            flags.setdefault("reasons", {}).setdefault("combo", []).append("ALLOW_COMBO")

    final_combo_tickets = combo_tickets if combo_ok else []

    combo_budget_reassign = bool(combo_tickets) and not final_combo_tickets
    no_combo_available = (
        not combo_tickets
        and flags.get("sp")
        and not flags.get("combo")
        and float(cfg.get("COMBO_RATIO", 0.0)) > 0.0
    )

    if not flags.get("sp"):
        sp_tickets = []
        final_combo_tickets = []
        ev_sp = 0.0
        roi_sp = 0.0
        stats_ev = {"ev": 0.0, "roi": 0.0}
        ev_global = 0.0
        roi_global = 0.0
        combined_payout = 0.0
        risk_of_ruin = 0.0
        ev_over_std = 0.0
        total_stake_sp = 0.0
        last_reduction_info = {
            "applied": False,
            "scale_factor": 1.0,
            "initial_ror": 0.0,
            "final_ror": 0.0,
            "target": float(cfg.get("ROR_MAX", 0.0)),
            "initial_ev": 0.0,
            "final_ev": 0.0,
            "initial_variance": 0.0,
            "final_variance": 0.0,
            "initial_total_stake": 0.0,
            "final_total_stake": 0.0,
        }
    elif combo_budget_reassign or no_combo_available:
        cfg_sp = dict(cfg)
        cfg_sp["SP_RATIO"] = float(cfg.get("SP_RATIO", 0.0)) + float(cfg.get("COMBO_RATIO", 0.0))
        cfg_sp["COMBO_RATIO"] = 0.0
        sp_tickets, _ = allocate_dutching_sp_fn(cfg_sp, runners)
        sp_tickets, stats_ev, reduction_info = adjust_pack(cfg_sp, [])
        last_reduction_info = reduction_info
        ev_sp, roi_sp, total_stake_sp = summarize_sp_tickets(sp_tickets)
        ev_global = float(stats_ev.get("ev", 0.0))
        roi_global = float(stats_ev.get("roi", 0.0))
        combined_payout = float(stats_ev.get("combined_expected_payout", 0.0))
        risk_of_ruin = float(stats_ev.get("risk_of_ruin", 0.0))
        ev_over_std = float(stats_ev.get("ev_over_std", 0.0))        
        flags = gate_ev_fn(
            cfg_sp,
            ev_sp,
            ev_global,
            roi_sp,
            roi_global,
            combined_payout,
            risk_of_ruin,
            ev_over_std,
        )
    elif proposed_pack != sp_tickets + final_combo_tickets:
        final_pack = sp_tickets + final_combo_tickets
        current_cap = _resolve_effective_cap(last_reduction_info, cfg)
        stats_ev = simulate_with_metrics(
            final_pack,
            bankroll=bankroll,
            kelly_cap=current_cap,
        )
        ev_sp, roi_sp, total_stake_sp = summarize_sp_tickets(sp_tickets)
        ev_global = float(stats_ev.get("ev", 0.0))
        roi_global = float(stats_ev.get("roi", 0.0))
        combined_payout = float(stats_ev.get("combined_expected_payout", 0.0))
        risk_of_ruin = float(stats_ev.get("risk_of_ruin", 0.0))
        ev_over_std = float(stats_ev.get("ev_over_std", 0.0))

    
    step_export = cfg.get("ROUND_TO_SP", 0.0)
    min_stake_export = cfg.get("MIN_STAKE_SP", 0.0)
    sp_changed = _normalize_ticket_stakes(
        sp_tickets,
        round_step=step_export,
        min_stake=min_stake_export,
    )
    combo_changed = _normalize_ticket_stakes(
        final_combo_tickets,
        round_step=step_export,
        min_stake=min_stake_export,
    )

    tickets = sp_tickets + final_combo_tickets

    if sp_changed or combo_changed:
        current_cap = _resolve_effective_cap(last_reduction_info, cfg)
        stats_ev = simulate_with_metrics(
            tickets,
            bankroll=bankroll,
            kelly_cap=current_cap,
        )
        ev_sp, roi_sp, total_stake_sp = summarize_sp_tickets(sp_tickets)
        ev_global = float(stats_ev.get("ev", 0.0))
        roi_global = float(stats_ev.get("roi", 0.0))
        combined_payout = float(stats_ev.get("combined_expected_payout", 0.0))
        risk_of_ruin = float(stats_ev.get("risk_of_ruin", 0.0))
        ev_over_std = float(stats_ev.get("ev_over_std", 0.0))
        if isinstance(last_reduction_info, dict):
            updated_info = dict(last_reduction_info)
            updated_info["final_total_stake"] = sum(
                float(t.get("stake", 0.0)) for t in tickets
            )
            updated_info["final_ev"] = ev_global
            updated_info["final_variance"] = float(stats_ev.get("variance", 0.0))
            updated_info["final_ror"] = risk_of_ruin
            if (
                updated_info.get("initial_total_stake")
                and updated_info["final_total_stake"] >= 0.0
            ):
                try:
                    updated_info["scale_factor"] = (
                        updated_info["final_total_stake"]
                        / float(updated_info.get("initial_total_stake", 1.0))
                    )
                except (TypeError, ValueError, ZeroDivisionError):  # pragma: no cover
                    pass
            last_reduction_info = updated_info

    final_combo_present = bool(final_combo_tickets)
    existing_decision = combo_info.get("decision")
    extra_reasons: list[str] = []
    if final_combo_present:
        combo_info["decision"] = "accept"
    else:
        if combo_tickets and existing_decision == "accept":
            extra_reasons.extend(flags.get("reasons", {}).get("combo", []))
            if not flags.get("sp", False):
                extra_reasons.append("sp_block")
            if combo_budget_reassign:
                extra_reasons.append("combo_budget_reassign")
            if no_combo_available:
                extra_reasons.append("no_combo_available")
            if not extra_reasons:
                extra_reasons.append("combo_removed_post_gate")
            combo_info["decision"] = \
                f"reject:{','.join(dict.fromkeys(extra_reasons))}"
        elif not combo_tickets and "decision" not in combo_info:
            combo_info["decision"] = "reject:no_candidate"

    for reason in extra_reasons:
        if reason not in reasons_list:
            reasons_list.append(reason)
    combo_flags["combo"] = final_combo_present

    meta["exotics"] = {
        "decision": combo_info.get("decision"),
        "notes": list(combo_info.get("notes", [])),
        "flags": copy.deepcopy(combo_info.get("flags", {})),
        "thresholds": dict(combo_info.get("thresholds", {})),
        "available": final_combo_present,
    }
    
    if flags.get("reasons", {}).get("sp"):
        logger.warning(
            "Blocage SP dû aux seuils: %s",
            ", ".join(flags["reasons"]["sp"]),
        )
    if flags.get("reasons", {}).get("combo"):
        combo_reasons = ", ".join(flags["reasons"]["combo"])
        message = f"Blocage combinés dû aux seuils: {combo_reasons}"
        logger.warning(message)
        print(message)
    if not flags.get("sp", False):
        tickets = []
        ev_sp = ev_global = 0.0
        roi_sp = roi_global = 0.0

    risk_of_ruin = float(stats_ev.get("risk_of_ruin", 0.0)) if tickets else 0.0
    clv_moyen = float(stats_ev.get("clv", 0.0)) if tickets else 0.0
    combined_payout = float(stats_ev.get("combined_expected_payout", 0.0)) if tickets else 0.0
    variance_total = float(stats_ev.get("variance", 0.0)) if tickets else 0.0

    optimization_summary = None
    if tickets:
        effective_cap = _resolve_effective_cap(last_reduction_info, cfg)
        optimization_summary = _summarize_optimization(
            tickets,
            bankroll=bankroll,
            kelly_cap=effective_cap,
        )

    # Hard budget stop
    total_stake = sum(t.get("stake", 0) for t in tickets)
    if total_stake > float(cfg.get("BUDGET_TOTAL", 0.0)) + 1e-6:
        raise RuntimeError("Budget dépassé")

    course_id = meta.get("rc", "")
    append_csv_line(
        "modele_suivi_courses_hippiques_clean.csv",
        {
            "reunion": meta.get("reunion", ""),
            "course": meta.get("course", ""),
            "hippodrome": meta.get("hippodrome", ""),
            "date": meta.get("date", ""),
            "discipline": meta.get("discipline", ""),
            "partants": len(partants),
            "nb_tickets": len(tickets),
            "total_stake": total_stake,
            "total_optimized_stake": (
                optimization_summary.get("stake_after")
                if optimization_summary
                else total_stake
            ),
            "ev_sp": ev_sp,
            "ev_global": ev_global,
            "roi_sp": roi_sp,
            "roi_global": roi_global,
            "risk_of_ruin": risk_of_ruin,
            "clv_moyen": clv_moyen,
            "model": cfg.get("MODEL", ""),
        },
        CSV_HEADER,
    )
    append_json(
        f"journaux/{course_id}_pre.json",
        {
            "tickets": tickets,
            "ev": {"sp": ev_sp, "global": ev_global},
            "exotics": meta.get("exotics", {}),
        },
    )


    outdir.mkdir(parents=True, exist_ok=True)
    stake_reduction_info = last_reduction_info or {}
    stake_reduction_flag = bool(stake_reduction_info.get("applied"))
    stake_reduction_details = {
        "scale_factor": stake_reduction_info.get("scale_factor", 1.0),
        "target": stake_reduction_info.get("target"),
        "initial_cap": stake_reduction_info.get("initial_cap"),
        "effective_cap": stake_reduction_info.get("effective_cap"),
        "iterations": stake_reduction_info.get("iterations"),
        "initial": {
            "risk_of_ruin": stake_reduction_info.get("initial_ror"),
            "ev": stake_reduction_info.get("initial_ev"),
            "variance": stake_reduction_info.get("initial_variance"),
            "total_stake": stake_reduction_info.get("initial_total_stake"),
        },
        "final": {
            "risk_of_ruin": stake_reduction_info.get("final_ror"),
            "ev": stake_reduction_info.get("final_ev"),
            "variance": stake_reduction_info.get("final_variance"),
            "total_stake": stake_reduction_info.get("final_total_stake"),
        },
    }    
    export(
        outdir,
        meta,
        tickets,
        ev_sp,
        ev_global,
        roi_sp,
        roi_global,
        risk_of_ruin,
        clv_moyen,
        variance_total,
        combined_payout,
        p_true,
        drift,
        cfg,
        stake_reduction_applied=stake_reduction_flag,
        stake_reduction_details=stake_reduction_details,
        optimization_details=optimization_summary,
    )
    logger.info("OK: analyse exportée dans %s", outdir)


def cmd_snapshot(args: argparse.Namespace) -> None:
    """Write a race-specific snapshot file."""

    base = Path(args.outdir)
    src = base / f"{args.when}.json"
    data = load_json(str(src))
    rc = f"{args.meeting}{args.race}"
    dest = base / f"{rc}-{args.when}.json"
    save_json(dest, data)
    logger.info("Snapshot écrit: %s", dest)


def main() -> None:
    parser = argparse.ArgumentParser(description="GPI v5.1 pipeline")
    parser.add_argument(
        "--log-level",
        default=None,
        help=(
            "Logging level (DEBUG, INFO, WARNING, ERROR). "
            f"Can also be set via {LOG_LEVEL_ENV_VAR}."
        ),
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    snap = sub.add_parser("snapshot", help="Renommer un snapshot h30/h5")
    snap.add_argument("--when", choices=["h30", "h5"], required=True)
    snap.add_argument("--meeting", required=True)
    snap.add_argument("--race", required=True)
    snap.add_argument("--outdir", required=True)
    snap.set_defaults(func=cmd_snapshot)

    ana = sub.add_parser("analyse", help="Analyser une course")
    ana.add_argument("--h30", required=True)
    ana.add_argument("--h5", required=True)
    ana.add_argument("--stats-je", required=True)
    ana.add_argument("--partants", required=True)
    ana.add_argument("--gpi", required=True)
    ana.add_argument("--outdir", default=None)
    ana.add_argument("--diff", default=None)
    ana.add_argument("--budget", type=float)
    ana.add_argument("--ev-global", dest="ev_global", type=float)
    ana.add_argument("--roi-global", dest="roi_global", type=float)
    ana.add_argument("--max-vol", dest="max_vol", type=float)
    ana.add_argument("--min-payout", dest="min_payout", type=float)
    ana.add_argument("--ev-min-exotic", dest="ev_min_exotic", type=float, default=None)
    ana.add_argument(
        "--payout-min-exotic", dest="payout_min_exotic", type=float, default=None
    )
    ana.add_argument(
        "--allow-heuristic", dest="allow_heuristic", action="store_true"
    )
    ana.add_argument("--allow-je-na", dest="allow_je_na", action="store_true")
    ana.set_defaults(func=cmd_analyse)

    args = parser.parse_args()
    
    configure_logging(args.log_level)
    
    args.func(args)


if __name__ == "__main__":
    main()
