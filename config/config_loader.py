#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Centralized configuration loader for the GPI v5.1 pipeline."""

import logging
import os
import re
from typing import Any, Callable, Dict, List, Sequence, Tuple, TypeVar

import yaml


logger = logging.getLogger(__name__)
T = TypeVar("T")

# ---------------------------------------------------------------------------
# Constants
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
}

_ENV_ALIASES: Dict[str, Tuple[str, ...]] = {
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

# ---------------------------------------------------------------------------
# Helper Functions
# ---------------------------------------------------------------------------


def _normalize_key(name: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "", name.upper())


def _build_config_alias_map() -> Dict[str, str]:
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
    resolved: Dict[str, object] = {}
    for key, value in raw_cfg.items():
        canonical = _resolve_config_key(key)
        if canonical:
            if canonical in resolved and canonical != key:
                continue
            resolved[canonical] = value
        else:
            resolved[key] = value
    return resolved


def _env_aliases(name: str) -> Tuple[str, ...]:
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
    raise ValueError(f"Cannot interpret {value!r} as boolean")


def _iter_candidates(name: str, aliases: Sequence[str] | None) -> List[str]:
    """Return the ordered list of environment variable names to inspect."""
    if not aliases:
        return [name]
    return [name, *aliases]


def get_env(
    name: str,
    default: T | None = None,
    *,
    cast: Callable[[str], T] = lambda x: x,  # type: ignore[assignment]
    required: bool = False,
    aliases: Sequence[str] | None = None,
) -> T:
    """Fetch an environment variable and coerce it to the desired type."""
    raw_value: str | None = None
    source = name
    for candidate in _iter_candidates(name, aliases):
        candidate_val = os.getenv(candidate)
        if candidate_val in (None, ""):
            continue
        raw_value = candidate_val
        source = candidate
        break

    if raw_value is None:
        if required:
            raise RuntimeError(f"Missing required environment variable '{name}'")
        logger.warning(
            "Environment variable %s not set; using default %r", name, default
        )
        return default  # type: ignore[return-value]

    try:
        value = cast(raw_value)
    except Exception as exc:
        raise RuntimeError(
            f"Invalid value for environment variable '{name}': {raw_value!r}"
        ) from exc

    if source != name:
        logger.info(
            "Environment variable %s=%r used as alias for %s", source, value, name
        )

    if default is not None and value != default:
        logger.info(
            "Environment variable %s=%r overrides default %r", source, value, default
        )
    return value


# ---------------------------------------------------------------------------
# Main Loader
# ---------------------------------------------------------------------------


def load_config(path: str) -> Dict[str, Any]:
    """Load, validate, and resolve configuration from a YAML file."""
    with open(path, "r", encoding="utf-8") as fh:
        raw_cfg = yaml.safe_load(fh) or {}

    cfg = _apply_aliases(raw_cfg)

    # Set defaults for missing optional keys
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
    cfg.setdefault("ROI_MIN_SP", 0.0)
    cfg.setdefault("ROI_MIN_GLOBAL", 0.0)
    cfg.setdefault("ROR_MAX", 0.01)
    cfg.setdefault("SHARPE_MIN", 0.0)
    cfg.setdefault("SNAPSHOTS", "H30,H5")
    cfg.setdefault("DRIFT_TOP_N", 5)
    cfg.setdefault("DRIFT_MIN_DELTA", 0.8)

    payout_default = cfg.get("EXOTIC_MIN_PAYOUT", cfg.get("MIN_PAYOUT_COMBOS"))
    if payout_default is None:
        payout_default = 10.0
    cfg["MIN_PAYOUT_COMBOS"] = payout_default
    cfg["EXOTIC_MIN_PAYOUT"] = payout_default

    # Override with environment variables
    cfg["SNAPSHOTS"] = get_env(
        "SNAPSHOTS", cfg.get("SNAPSHOTS"), aliases=_env_aliases("SNAPSHOTS")
    )
    cfg["DRIFT_TOP_N"] = get_env("DRIFT_TOP_N", cfg.get("DRIFT_TOP_N"), cast=int)
    cfg["DRIFT_MIN_DELTA"] = get_env(
        "DRIFT_MIN_DELTA", cfg.get("DRIFT_MIN_DELTA"), cast=float
    )
    cfg["BUDGET_TOTAL"] = get_env(
        "BUDGET_TOTAL",
        cfg.get("BUDGET_TOTAL"),
        cast=float,
        aliases=_env_aliases("BUDGET_TOTAL"),
    )
    cfg["SP_RATIO"] = get_env(
        "SP_RATIO", cfg.get("SP_RATIO"), cast=float, aliases=_env_aliases("SP_RATIO")
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
    cfg["EV_MIN_GLOBAL"] = get_env(
        "EV_MIN_GLOBAL", cfg.get("EV_MIN_GLOBAL"), cast=float
    )
    cfg["ROI_MIN_SP"] = get_env("ROI_MIN_SP", cfg.get("ROI_MIN_SP"), cast=float)
    cfg["ROI_MIN_GLOBAL"] = get_env(
        "ROI_MIN_GLOBAL", cfg.get("ROI_MIN_GLOBAL"), cast=float
    )
    cfg["ROR_MAX"] = get_env(
        "ROR_MAX", cfg.get("ROR_MAX"), cast=float, aliases=_env_aliases("ROR_MAX")
    )
    cfg["SHARPE_MIN"] = get_env("SHARPE_MIN", cfg.get("SHARPE_MIN"), cast=float)
    cfg["MAX_TICKETS_SP"] = get_env(
        "MAX_TICKETS_SP", cfg.get("MAX_TICKETS_SP"), cast=int
    )
    cfg["MIN_STAKE_SP"] = get_env("MIN_STAKE_SP", cfg.get("MIN_STAKE_SP"), cast=float)
    cfg["DRIFT_COEF"] = get_env("DRIFT_COEF", cfg.get("DRIFT_COEF"), cast=float)
    cfg["ROUND_TO_SP"] = get_env("ROUND_TO_SP", cfg.get("ROUND_TO_SP"), cast=float)
    cfg["JE_BONUS_COEF"] = get_env(
        "JE_BONUS_COEF", cfg.get("JE_BONUS_COEF"), cast=float
    )
    cfg["KELLY_FRACTION"] = get_env(
        "KELLY_FRACTION", cfg.get("KELLY_FRACTION"), cast=float
    )
    cfg["ALLOW_JE_NA"] = get_env("ALLOW_JE_NA", cfg.get("ALLOW_JE_NA"), cast=_as_bool)
    cfg["PAUSE_EXOTIQUES"] = get_env(
        "PAUSE_EXOTIQUES", cfg.get("PAUSE_EXOTIQUES"), cast=_as_bool
    )
    cfg["REQUIRE_DRIFT_LOG"] = get_env(
        "REQUIRE_DRIFT_LOG", cfg.get("REQUIRE_DRIFT_LOG"), cast=_as_bool
    )
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

    # Final validation
    missing = [k for k in REQ_KEYS if k not in cfg]
    if missing:
        raise RuntimeError(f"Config incomplète: clés manquantes {missing}")
    if float(cfg["SP_RATIO"]) + float(cfg["COMBO_RATIO"]) > 1.0:
        raise RuntimeError("SP_RATIO + COMBO_RATIO doit être <= 1.0")

    return cfg
