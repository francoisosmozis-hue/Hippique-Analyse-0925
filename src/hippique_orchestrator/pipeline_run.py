#!/usr/bin/env python3
"""
pipeline_run.py — GPI v5.1 (cap 5 €)
Chaîne de décision complète (EV + budget + Kelly cap 60 %) intégrée.

Objectif
--------
Fournir un pipeline autonome (ou branchable depuis runner_chain.py) pour :
- charger les snapshots H-30 et H-5 d'une course (dossier data/R?C?),
- convertir les cotes en probabilités implicites (normalisées, overround),
- détecter les drifts H-30 → H-5,
- scorer les partants (forme/cotes/option J/E),
- construire des tickets selon GPI v5.1 :
  • Ticket 1 : Dutching Simple Placé (2–3 chevaux, cotes 2.5–7, Kelly fractionné cap 60 %)
  • Ticket 2 (optionnel) : un combiné (CPL/TRIO/ZE4) si EV ≥ +40 % ET payout attendu > 10 €
- respecter le budget total par course = 5 € (plafond dur), ratio cible 60/40.

Notes
-----
- Le module tente d'utiliser les helpers du dépôt (simulate_ev, module_dutching_pmu, validator_ev) si disponibles.
- Des fallbacks internes existent pour rester exécutable sans autres modules.
- Exporte un `run_pipeline(course_dir: str, budget: float=5.0)` utilisable par runner_chain.py.
- CLI inclus : `python pipeline_run.py --dir data/R1C2`.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import re
import statistics as stats
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import logging_io

try:  # pragma: no cover - optional dependency
    import yaml
except Exception:  # pragma: no cover - yaml may be unavailable in slim envs
    yaml = None  # type: ignore

from hippique.utils.dutching import (
    diversify_guard,
    equal_profit_stakes,
    require_mid_odds,
)
from hippique.utils.probabilities import expected_value_simple, no_vig_probs

# ===================== Imports optionnels (helpers du dépôt) =====================
try:
    from simulate_ev import simulate_couple_place_ev, simulate_trio_ev  # type: ignore
except Exception:  # fallbacks plus bas
    simulate_couple_place_ev = None
    simulate_trio_ev = None

try:
    from module_dutching_pmu import kelly_fractional_dutching  # type: ignore
except Exception:
    kelly_fractional_dutching = None

try:
    from validator_ev import estimate_expected_payout  # type: ignore
except Exception:
    estimate_expected_payout = None

# =============================== Helpers génériques =============================
PLACE_FEE: float = 0.14


def load_yaml(path: str | Path) -> dict[str, Any]:
    """Safely load a YAML file, returning an empty dict when unavailable."""

    p = Path(path)
    if not p.exists() or not p.is_file():
        return {}
    if yaml is None:
        return {}
    with p.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _overround_from_odds_win(odds: Iterable[float]) -> float:
    """Compute the overround as the sum of inverse win odds."""

    total = 0.0
    for value in odds or []:
        try:
            odd = float(value)
        except (TypeError, ValueError):
            continue
        if odd <= 0.0:
            continue
        total += 1.0 / odd
    return total


def _ensure_place_odds(win_odds: Iterable[float], factor: float = 0.33) -> list[float]:
    """Derive basic place odds from win odds via a linear heuristic."""

    place_odds: list[float] = []
    for value in win_odds or []:
        try:
            odd = float(value)
        except (TypeError, ValueError):
            place_odds.append(1.0)
            continue
        if odd <= 1.0:
            place_odds.append(1.0)
            continue
        place_odds.append(1.0 + (odd - 1.0) * float(factor))
    return place_odds


def _filter_sp_and_cp_tickets(sp_tickets, combo_tickets, *_args, **_kwargs):
    """Identity filter used in legacy pipeline tests."""

    return list(sp_tickets), list(combo_tickets), []


def _summarize_optimization(*_args: object, **_kwargs: object) -> None:
    """Compatibility stub used by historical tests."""

    return None


def compute_drift_dict(
    h30: Mapping[str, float] | None,
    h5: Mapping[str, float] | None,
) -> dict[str, float]:
    """Compute relative drift between H-30 and H-5 odds for each runner."""

    drift: dict[str, float] = {}
    if not h30 or not h5:
        return drift
    for runner_id, odds_30 in h30.items():
        try:
            base = float(odds_30)
            latest_raw = h5.get(runner_id)
            latest = float(latest_raw) if latest_raw is not None else None
        except (TypeError, ValueError):
            continue
        if not latest or base <= 0:
            continue
        drift[runner_id] = (latest / base) - 1.0
    return drift


def enforce_ror_threshold(
    ror_daily: float | None,
    base_kelly: float = 0.50,
    min_kelly: float = 0.33,
    max_ror: float = 0.01,
) -> float:
    """Adjust Kelly fraction when the estimated risk of ruin exceeds threshold."""

    if ror_daily is None:
        return base_kelly
    try:
        ror = float(ror_daily)
    except (TypeError, ValueError):
        return base_kelly
    if ror <= max_ror:
        return base_kelly
    return max(min_kelly, base_kelly * 0.66)


def build_p_true(win_odds: Iterable[float]) -> dict[int, float]:
    """Derive a naive no-vig probability distribution from win odds."""

    normalized: dict[int, float] = {}
    inv_odds: list[float] = []
    for value in win_odds or []:
        try:
            odd = float(value)
        except (TypeError, ValueError):
            continue
        if odd <= 1.0:
            continue
        inv_odds.append(1.0 / odd)
    total = sum(inv_odds)
    if total <= 0.0:
        return normalized
    for idx, inv in enumerate(inv_odds):
        normalized[idx] = inv / total
    return normalized


def _normalize_decimal(value: Any) -> float | None:
    """Return a decimal odds value as float when possible."""

    if isinstance(value, str):
        value = value.replace(",", ".")
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number <= 0.0:
        return None
    return number


def _estimate_overround_win(runners: Sequence[Mapping[str, Any]]) -> float | None:
    """Compute the win overround for ``runners`` when coverage is sufficient."""

    odds: list[float] = []
    for runner in runners or []:
        if not isinstance(runner, Mapping):
            continue
        candidate = (
            runner.get("odds")
            or runner.get("odds_win")
            or runner.get("win_odds")
            or runner.get("cote")
        )
        value = _normalize_decimal(candidate)
        if value is not None:
            odds.append(value)
    if not odds:
        return None
    return sum(1.0 / odd for odd in odds)


def _estimate_overround_place(runners: Sequence[Mapping[str, Any]]) -> float | None:
    """Compute the place overround, falling back to win odds when needed."""

    totals = 0.0
    count = 0
    for runner in runners or []:
        if not isinstance(runner, Mapping):
            continue
        candidate = runner.get("odds_place") or runner.get("place_odds")
        value = _normalize_decimal(candidate)
        if value is None:
            value = _normalize_decimal(
                runner.get("odds")
                or runner.get("odds_win")
                or runner.get("win_odds")
                or runner.get("cote")
            )
        if value is None:
            continue
        totals += 1.0 / value
        count += 1
    if count == 0:
        return None
    return totals


_SLOT_RE = re.compile(r"(\d+)")


def _parse_slots_hint(value: Any, default: int = 3) -> int:
    """Extract the number of paying places from textual hints."""

    if isinstance(value, int):
        return value if value > 0 else default
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        match = _SLOT_RE.search(value)
        if match:
            try:
                return int(match.group(1))
            except ValueError:
                return default
    return default


@lru_cache(maxsize=1)
def _load_simulate_ev():
    """Lazy loader returning the simulate_ev module."""

    import simulate_ev  # type: ignore

    return simulate_ev

def _build_market(
    runners: Sequence[Mapping[str, Any]],
    slots_hint: Any | None = None,
) -> dict[str, Any]:
    """Return market metrics including win/place overround when possible."""

    runners_seq = list(runners or [])
    total = len(runners_seq)
    win_odds = []
    for runner in runners_seq:
        if not isinstance(runner, Mapping):
            continue
        value = _normalize_decimal(
            runner.get("odds")
            or runner.get("odds_win")
            or runner.get("win_odds")
            or runner.get("cote")
        )
        if value is not None:
            win_odds.append(value)

    coverage_ratio = (len(win_odds) / total) if total else 0.0
    coverage_ok = coverage_ratio >= 0.6 if total else False

    overround_win = _estimate_overround_win(runners_seq) if coverage_ok else None
    overround_place = _estimate_overround_place(runners_seq)

    market: dict[str, Any] = {
        "runner_count_total": total,
        "runner_count_with_win_odds": len(win_odds),
        "win_coverage_ratio": round(coverage_ratio, 4) if total else 0.0,
        "win_coverage_sufficient": coverage_ok,
        "slots_place": _parse_slots_hint(slots_hint, default=3),
    }

    if overround_win is not None:
        market["overround_win"] = overround_win
        market["overround"] = overround_win

    if overround_place is not None:
        market["overround_place"] = overround_place
        market.setdefault("overround", overround_place)

    return market

# =============================== Structures de données ==========================
@dataclass
class Horse:
    num: str
    name: str | None
    odds_h30: float | None
    odds_h5: float | None
    p_impl_h30: float | None
    p_impl_h5: float | None
    p_score: float | None  # prob mix/blend finale (après normalisation)
    drift: float | None    # variation de cote (h5 - h30)
    ecurie: str | None = None
    driver: str | None = None
    chrono_last: float | None = None

@dataclass
class Ticket:
    kind: str  # 'SP_DUTCHING' | 'CP' | 'TRIO' | 'ZE4'
    legs: list[dict[str, Any]]
    stake: float
    exp_value: float | None
    exp_payout: float | None

@dataclass
class Report:
    course_dir: str
    n_partants: int
    overround_h30: float | None
    overround_h5: float | None
    favorite: str | None
    tickets: list[Ticket]
    budget_total: float
    budget_sp: float
    budget_combo: float
    abstention: str | None = None

# =============================== Utilitaires ====================================


def _load_gpi_cfg(path: Path | str = "config/gpi.yml") -> dict[str, Any]:
    if yaml is None:
        return {}
    config_path = Path(path)
    if not config_path.exists():
        return {}
    with config_path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        return {}
    return data


_GPI_CFG: dict[str, Any] = _load_gpi_cfg()


ARTIFACTS_DIR = Path("artifacts")
METRICS_PATH = ARTIFACTS_DIR / "metrics.json"
PER_HORSE_REPORT_PATH = ARTIFACTS_DIR / "per_horse_report.csv"
CMD_UPDATE_EXCEL_PATH = ARTIFACTS_DIR / "cmd_update_excel.txt"


def _cfg_section(name: str) -> dict[str, Any]:
    section = _GPI_CFG.get(name, {}) if isinstance(_GPI_CFG, dict) else {}
    return section if isinstance(section, dict) else {}


# =============================== Constantes GPI v5.1 ============================
BUDGET_DEFAULT = float(
    _cfg_section("bankroll").get("stake_cap_per_race", _GPI_CFG.get("BUDGET_TOTAL", 5.0))
)
MAX_TICKETS = 2
RATIO_SP = float(
    _cfg_section("bankroll").get("split_sp", _GPI_CFG.get("SP_RATIO", 0.60))
)
KELLY_CAP = float(
    _cfg_section("kelly").get("single_leg_cap", _GPI_CFG.get("MAX_VOL_PAR_CHEVAL", 0.60))
)
EV_COMBO_MIN = float(
    _cfg_section("ev").get("min_ev_combo", _GPI_CFG.get("EV_MIN_GLOBAL", 0.40))
)
PAYOUT_MIN = float(
    _cfg_section("ev").get("min_expected_payout_combo", _GPI_CFG.get("MIN_PAYOUT_COMBOS", 10.0))
)
SP_MIN_ODDS = 2.5
SP_MAX_ODDS = 7.0


def _overround(odds_list: list[float]) -> float:
    return sum(1.0 / float(o) for o in odds_list if o)


def compute_overround_cap(*_args: object, **_kwargs: object) -> float:
    """Return the default overround cap from configuration."""

    bands = _cfg_section("overround_bands")
    return float(bands.get("default_low_vol_max", 1.25))


def _pick_overround_cap(discipline: str, n_partants: int) -> float:
    bands = _cfg_section("overround_bands")
    if discipline.lower().startswith("trot") and n_partants <= 9:
        return float(bands.get("trot_small_field_max", 1.25))
    if discipline.lower().startswith("plat") and n_partants >= 14:
        return float(bands.get("plat_handicap_14p_max", 1.25))
    return float(bands.get("default_low_vol_max", 1.25))


def _kelly_fraction_guard(ror_daily: float) -> float:
    kelly_cfg = _cfg_section("kelly")
    base = float(kelly_cfg.get("base_fraction", 0.5))
    ror_cap = float(kelly_cfg.get("ror_daily_max", 0.01))
    if ror_daily <= ror_cap:
        return base
    min_fraction = float(kelly_cfg.get("min_fraction", base))
    return max(min_fraction, base * 0.66)


def _estimate_ror_daily(returns: list[float], bankroll: float) -> float:
    if not returns or bankroll <= 0:
        return 0.0
    try:
        variance = stats.pvariance(returns)
    except Exception:
        return 0.0
    threshold = 0.01 * bankroll
    return 0.01 if math.sqrt(variance) > threshold else 0.0


def _clv_median_ok(clv_series: list[float], gate: float) -> bool:
    if not clv_series:
        return False
    try:
        return stats.median(clv_series) > gate
    except Exception:
        return False


def _extract_float(meta: Mapping[str, Any], keys: Sequence[str], default: float = 0.0) -> float:
    for key in keys:
        value = meta.get(key)
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return default


def _per_horse_rows_from_market(sp_odds: Sequence[float], sp_meta: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not sp_odds:
        return rows
    probs = list(no_vig_probs(list(sp_odds))) if sp_odds else []
    for idx, odds in enumerate(sp_odds):
        meta = sp_meta[idx] if idx < len(sp_meta) else {}
        runner_num = meta.get("num") or meta.get("horse") or meta.get("runner") or str(idx + 1)
        rows.append(
            {
                "num": str(runner_num),
                "odds_win": float(odds) if odds else None,
                "p_no_vig": probs[idx] if idx < len(probs) else None,
                "j_rate": _extract_float(meta, ("j_rate", "driver_rate", "jockey_rate"), 0.0),
                "e_rate": _extract_float(meta, ("e_rate", "ecurie_rate", "stable_rate"), 0.0),
            }
        )
    return rows


def _per_horse_rows_from_horses(horses: Sequence[Horse]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not horses:
        return rows
    odds = []
    for horse in horses:
        odds_value = horse.odds_h5 or horse.odds_h30
        odds.append(float(odds_value) if odds_value else None)
    probs, _ = _implied_probs_from_odds(odds)
    for horse, prob, odds_value in zip(horses, probs, odds, strict=False):
        rows.append(
            {
                "num": horse.num,
                "odds_win": odds_value,
                "p_no_vig": prob,
                "j_rate": 0.0,
                "e_rate": 0.0,
            }
        )
    return rows


def _default_excel_cmd(race_id: str) -> str:
    return (
        "python update_excel_with_results.py --race "
        f"'{race_id}' --excel modele_suivi_courses_hippiques.xlsx"
    )


def _write_artifacts(
    metrics: Mapping[str, Any],
    per_horse_rows: Sequence[Mapping[str, Any]],
    race_id: str,
) -> None:
    ARTIFACTS_DIR.mkdir(exist_ok=True)

    payload = {
        "overround": metrics.get("overround"),
        "clv_median_30": metrics.get("clv_median_30"),
        "kelly_fraction": metrics.get("kelly_fraction"),
    }
    with METRICS_PATH.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)

    with PER_HORSE_REPORT_PATH.open("w", encoding="utf-8", newline="") as handle:
        fieldnames = ["num", "odds_win", "p_no_vig", "j_rate", "e_rate"]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in per_horse_rows:
            sanitized = {}
            for key in fieldnames:
                value = row.get(key, "")
                sanitized[key] = "" if value is None else value
            writer.writerow(sanitized)

    with CMD_UPDATE_EXCEL_PATH.open("w", encoding="utf-8") as handle:
        handle.write(_default_excel_cmd(race_id) + "\n")


def build_tickets_roi_first(
    market: dict[str, Any],
    budget: float,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """ROI-first ticket constructor used by the fast-path tooling.

    Parameters
    ----------
    market:
        Dictionary describing the SP market. Expected keys are ``sp_odds``
        (list of decimal odds) and ``sp_meta`` (list of metadata dictionaries).
    budget:
        Total bankroll available for the race.
    meta:
        Optional dictionary containing contextual metrics such as
        ``discipline`` (str), ``n_partants`` (int), ``bankroll`` (float),
        ``todays_returns`` (list[float]) or calibration stats.

    Returns
    -------
    dict
        ``{"tickets": [...], "abstention": <str|None>}``
    """

    meta = dict(meta or {})
    cfg_bankroll = _cfg_section("bankroll")
    stake_cap = float(cfg_bankroll.get("stake_cap_per_race", budget))
    budget = min(budget, stake_cap)
    split_sp = float(cfg_bankroll.get("split_sp", 0.6))
    split_combo = float(cfg_bankroll.get("split_combos", 0.4))
    stake_sp = round(budget * split_sp, 2)
    stake_combo = round(budget * split_combo, 2)

    discipline = str(meta.get("discipline", ""))
    n_partants = int(meta.get("n_partants", len(market.get("sp_odds", []))))
    sp_odds_raw = [float(o) for o in market.get("sp_odds", []) if o]

    overround_cap = None
    overround_value = None
    if sp_odds_raw:
        overround_cap = _pick_overround_cap(discipline, n_partants)
        overround_value = _overround(sp_odds_raw)

    clv_cfg = _cfg_section("clv")
    clv_series = list(market.get("clv_rolling") or meta.get("clv_rolling") or [])
    allow_exotics = _clv_median_ok(
        clv_series,
        float(clv_cfg.get("median_gate_exotics", 0.0)),
    )

    bankroll = float(meta.get("bankroll", stake_cap))
    todays_returns = list(meta.get("todays_returns", []))
    ror_daily = _estimate_ror_daily(todays_returns, bankroll)
    kelly_fraction = _kelly_fraction_guard(ror_daily)

    tickets: list[dict[str, Any]] = []
    abstention: str | None = None

    sp_meta = market.get("sp_meta") or []
    per_horse_rows = _per_horse_rows_from_market(sp_odds_raw, sp_meta)

    if sp_odds_raw and overround_cap is not None and overround_value is not None:
        if overround_value > overround_cap:
            abstention = f"OVERROUND>{overround_cap:.2f}"
        elif not sp_meta:
            abstention = "MISSING_SP_META"
        elif not diversify_guard(sp_meta):
            abstention = "DIVERSIFICATION_FAIL"
        elif not require_mid_odds(sp_meta):
            abstention = "NO_MID_ODDS"
        else:
            stake_sp_actual = max(0.0, round(stake_sp * kelly_fraction, 2))
            if stake_sp_actual > 0:
                stakes = equal_profit_stakes(sp_odds_raw, stake_sp_actual)
                leg_cap = float(_cfg_section("kelly").get("single_leg_cap", 0.6))
                cap_amount = stake_sp_actual * leg_cap
                stakes = [min(st, cap_amount) for st in stakes]
                total = sum(stakes) or 1.0
                if total > stake_sp_actual and total > 0:
                    factor = stake_sp_actual / total
                    stakes = [st * factor for st in stakes]

                model_probs_raw = market.get("model_probs")
                if isinstance(model_probs_raw, list) and len(model_probs_raw) == len(sp_odds_raw):
                    probs = [max(0.0, float(p)) for p in model_probs_raw]
                else:
                    probs = list(no_vig_probs(sp_odds_raw))
                evs = [
                    expected_value_simple(prob, odds, stake)
                    for prob, odds, stake in zip(probs, sp_odds_raw, stakes, strict=False)
                ]
                ev_sp = float(sum(evs))

                ev_cfg = _cfg_section("ev")
                min_ev_sp = float(ev_cfg.get("min_ev_sp_pct_budget", 0.0)) * stake_sp
                if ev_sp < min_ev_sp:
                    abstention = "EV_SP_TOO_LOW"
                else:
                    legs_payload = []
                    for meta_leg, odds, stake, prob, ev_leg in zip(sp_meta, sp_odds_raw, stakes, probs, evs, strict=False):
                        leg_payload = dict(meta_leg)
                        leg_payload.update(
                            {
                                "odds": odds,
                                "stake": round(stake, 2),
                                "prob": prob,
                                "ev": ev_leg,
                                "kelly_fraction": kelly_fraction,
                            }
                        )
                        legs_payload.append(leg_payload)

                    tickets.append(
                        {
                            "type": "SP_DUTCH",
                            "legs": legs_payload,
                            "stake": round(sum(stakes), 2),
                            "ev": ev_sp,
                        }
                    )

    ev_cfg = _cfg_section("ev")
    min_combo_payout = float(ev_cfg.get("min_expected_payout_combo", 0.0))
    if abstention is None and allow_exotics and stake_combo > 0:
        calibration = meta.get("calibration", {})
        calib_cfg = _cfg_section("calibration")
        has_calibration = (
            calibration.get("samples", 0) >= int(calib_cfg.get("min_samples", 0))
            and calibration.get("ci95_width", 1.0) <= float(calib_cfg.get("max_ci95_width", 1.0))
            and calibration.get("abs_err", 1.0) <= float(calib_cfg.get("max_abs_error_pct", 1.0))
            and calibration.get("age_days", 999) <= int(calib_cfg.get("stale_days", 999))
        )
        expected_payout = float(market.get("expected_payout_combo", 0.0))
        if has_calibration and expected_payout >= min_combo_payout:
            tickets.append(
                {
                    "type": "COMBO_AUTO",
                    "stake": round(stake_combo, 2),
                    "expected_payout": expected_payout,
                    "note": "gated by CLV&calibration",
                }
            )

    metrics_payload = {
        "overround": overround_value,
        "clv_median_30": stats.median(clv_series) if clv_series else None,
        "kelly_fraction": kelly_fraction,
    }
    _write_artifacts(metrics_payload, per_horse_rows, str(meta.get("race_id", "R?C?")))

    return {"tickets": tickets, "abstention": None}

def _load_latest(path: Path, pattern: str) -> Path | None:
    files = sorted(path.glob(pattern), key=lambda p: p.stat().st_mtime)
    return files[-1] if files else None


def _safe_float(x: Any) -> float | None:
    if x is None:
        return None
    try:
        return float(str(x).replace(",", "."))
    except Exception:
        return None


def _read_snapshot_json(p: Path) -> dict[str, Any]:
    with p.open("r", encoding="utf-8", errors="replace") as f:
        return json.load(f)


def _collect_runners(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    # Tente plusieurs clés communes aux snapshots du dépôt
    for key in ("runners", "participants", "partants", "horses"):
        if isinstance(snapshot.get(key), list):
            return list(snapshot[key])
    # fallback si structure non standard
    return []


def _extract_odds(rec: dict[str, Any]) -> float | None:
    for k in ("odds", "cote", "odds_sp", "odds_place", "cote_place"):
        v = _safe_float(rec.get(k))
        if v is not None and v > 0:
            return v
    return None


def _implied_probs_from_odds(odds: list[float | None]) -> tuple[list[float | None], float | None]:
    """Retourne (probs_normalisées, overround)
    - ignore None
    - si aucune cote valide, renvoie ([None…], None)
    """
    inv = [1.0/o for o in odds if isinstance(o, (float, int)) and o and o > 0]
    if not inv:
        return [None]*len(odds), None
    s = sum(inv)
    probs = []
    for o in odds:
        if o and o > 0:
            probs.append((1.0/o)/s)
        else:
            probs.append(None)
    # overround: somme brute des 1/odds
    return probs, s


def _blend(a: float | None, b: float | None, w_b: float = 0.6) -> float | None:
    if a is None and b is None:
        return None
    if a is None:
        return b
    if b is None:
        return a
    w_a = 1.0 - w_b
    return max(0.0, w_a*a + w_b*b)

# ========================= Chargement course & features =========================

def load_course(course_dir: str) -> tuple[list[Horse], dict[str, Any]]:
    d = Path(course_dir)
    if not d.exists():
        raise FileNotFoundError(f"Dossier inexistant: {course_dir}")

    p_h30 = _load_latest(d, "*_H-30.json") or d.joinpath("snapshot_H30.json")
    p_h5  = _load_latest(d, "*_H-5.json") or d.joinpath("snapshot_H5.json")

    snap_h30 = _read_snapshot_json(p_h30) if p_h30 and p_h30.exists() else {}
    snap_h5  = _read_snapshot_json(p_h5)  if p_h5 and p_h5.exists()  else {}

    run_h30 = _collect_runners(snap_h30)
    run_h5  = _collect_runners(snap_h5)

    # Map par dossard
    idx30: dict[str, dict[str, Any]] = {str(r.get("num") or r.get("horse") or r.get("dossard") or r.get("id")): r for r in run_h30}
    idx5:  dict[str, dict[str, Any]] = {str(r.get("num") or r.get("horse") or r.get("dossard") or r.get("id")): r for r in run_h5}
    all_nums = sorted(set(idx30.keys()) | set(idx5.keys()), key=lambda x: (len(x), x))

    # Cotes & probs
    odds30 = []
    odds5 = []
    for num in all_nums:
        odds30.append(_extract_odds(idx30.get(num, {})))
        odds5.append(_extract_odds(idx5.get(num, {})))

    probs30, over30 = _implied_probs_from_odds(odds30)
    probs5, over5 = _implied_probs_from_odds(odds5)

    horses: list[Horse] = []
    for i, num in enumerate(all_nums):
        rec5 = idx5.get(num, {})
        rec30 = idx30.get(num, {})
        name = rec5.get("name") or rec30.get("name")
        o30 = odds30[i]
        o5 = odds5[i]
        p30 = probs30[i]
        p5 = probs5[i]
        blend = _blend(p30, p5, 0.6)
        drift = None
        if o30 is not None and o5 is not None:
            drift = o5 - o30  # >0: drift défavorable (cote qui monte)
        ecurie = rec5.get("ecurie") or rec30.get("ecurie") or rec5.get("stable") or rec30.get("stable")
        driver = (
            rec5.get("driver")
            or rec30.get("driver")
            or rec5.get("jockey")
            or rec30.get("jockey")
            or rec5.get("driver_name")
            or rec30.get("driver_name")
        )
        chrono_last = _safe_float(
            rec5.get("chrono_last")
            or rec5.get("chrono_reference")
            or rec5.get("chrono")
            or rec30.get("chrono_last")
            or rec30.get("chrono_reference")
        )

        horses.append(
            Horse(
                num=str(num),
                name=name,
                odds_h30=o30,
                odds_h5=o5,
                p_impl_h30=p30,
                p_impl_h5=p5,
                p_score=blend,
                drift=drift,
                ecurie=str(ecurie) if ecurie else None,
                driver=str(driver) if driver else None,
                chrono_last=chrono_last,
            )
        )

    discipline = (
        snap_h5.get("discipline")
        or snap_h5.get("race", {}).get("discipline")
        or snap_h30.get("discipline")
        or snap_h30.get("race", {}).get("discipline")
        or ""
    )

    clv_series = []
    clv_source = snap_h5.get("clv_rolling") or snap_h5.get("clv_last")
    if isinstance(clv_source, list):
        clv_series = [float(x) for x in clv_source if isinstance(x, (float, int))]

    meta = {
        "n_partants": len(horses),
        "overround_h30": over30,
        "overround_h5": over5,
        "snapshot_h30": str(p_h30) if p_h30 and p_h30.exists() else None,
        "snapshot_h5": str(p_h5) if p_h5 and p_h5.exists() else None,
        "course_dir": str(d),
        "discipline": str(discipline),
        "clv_rolling": clv_series,
    }
    return horses, meta

# =============================== Sélection SP ===================================

def _select_sp_candidates(horses: list[Horse]) -> list[Horse]:
    """Filtre SP (2.5–7.0) et priorité aux meilleurs p_score.
    Inclut au moins un cheval de cote moyenne (4–7) si possible (règle 18/07).
    """
    pool = [h for h in horses if h.odds_h5 and SP_MIN_ODDS <= h.odds_h5 <= SP_MAX_ODDS and (h.p_score or 0) > 0]
    pool.sort(key=lambda h: (-(h.p_score or 0), h.odds_h5))
    top = pool[:3]
    if len(top) >= 2:
        # Forcer présence d'une cote moyenne (4–7) si absente
        if not any(4.0 <= (h.odds_h5 or 0) <= 7.0 for h in top):
            mid = next((h for h in pool if 4.0 <= (h.odds_h5 or 0) <= 7.0), None)
            if mid and mid not in top:
                top[-1] = mid
    return top[:3]


def _kelly_fraction(p: float, b: float) -> float:
    # Kelly classique f* = (bp - q) / b  où b = odds-1 (gagnant). En placé on reste indicatif.
    q = 1.0 - p
    return max(0.0, (b * p - q) / max(b, 1e-9))


def _allocate_kelly_capped(stakes_total: float, picks: list[Horse], fraction: float = 0.5) -> list[float]:
    """Répartition Kelly fractionné avec cap à 60% par cheval, normalisée pour somme=stakes_total."""
    if not picks:
        return []
    raw = []
    for h in picks:
        p = max(1e-6, h.p_score or 0.0)
        o = max(1.01, (h.odds_h5 or h.odds_h30 or 3.0))
        b = max(0.01, o - 1.0)
        f = _kelly_fraction(p, b)
        raw.append(max(0.0, f * fraction))
    # normaliser
    s = sum(raw) or 1.0
    alloc = [x / s for x in raw]
    # cap 60 % par cheval puis renormaliser
    alloc = [min(x, KELLY_CAP) for x in alloc]
    s = sum(alloc) or 1.0
    alloc = [x / s for x in alloc]
    return [stakes_total * x for x in alloc]

# =============================== EV des combinés ================================

def _simulate_cp_ev(legs: list[Horse]) -> tuple[float | None, float | None]:
    if simulate_couple_place_ev is not None:
        try:
            ev, payout = simulate_couple_place_ev([
                {"num": h.num, "p": h.p_score, "odds": h.odds_h5} for h in legs
            ])
            return ev, payout
        except Exception:
            pass
    # Fallback très conservateur
    if len(legs) < 2:
        return None, None
    p12 = (legs[0].p_score or 0) * (legs[1].p_score or 0)
    exp_payout = 12.0  # hypothèse prudente
    exp_cost = 1.0
    ev = (p12 * exp_payout - exp_cost) / exp_cost
    return ev, exp_payout


def _simulate_trio_ev(legs: list[Horse]) -> tuple[float | None, float | None]:
    if simulate_trio_ev is not None:
        try:
            ev, payout = simulate_trio_ev([
                {"num": h.num, "p": h.p_score, "odds": h.odds_h5} for h in legs
            ])
            return ev, payout
        except Exception:
            pass
    # Fallback très conservateur
    if len(legs) < 3:
        return None, None
    p123 = (legs[0].p_score or 0) * (legs[1].p_score or 0) * (legs[2].p_score or 0)
    exp_payout = 50.0  # Trio seuil utile
    exp_cost = 1.0
    ev = (p123 * exp_payout - exp_cost) / exp_cost
    return ev, exp_payout

# =============================== Construction tickets ===========================

def _build_tickets_from_horses(
    horses: list[Horse],
    budget: float = BUDGET_DEFAULT,
    meta: dict[str, Any] | None = None,
) -> list[Ticket]:
    tickets: list[Ticket] = []

    # Ticket 1 — SP Dutching
    budget_sp = round(budget * RATIO_SP, 2)
    sp_candidates = _select_sp_candidates(horses)
    if len(sp_candidates) >= 2:
        if kelly_fractional_dutching is not None:
            try:
                allocs = kelly_fractional_dutching(
                    probs=[max(1e-6, h.p_score or 0.0) for h in sp_candidates],
                    odds=[max(1.01, (h.odds_h5 or h.odds_h30 or 3.0)) for h in sp_candidates],
                    budget=budget_sp,
                    cap=KELLY_CAP,
                    fraction=0.5,
                )
            except Exception:
                allocs = _allocate_kelly_capped(budget_sp, sp_candidates, 0.5)
        else:
            allocs = _allocate_kelly_capped(budget_sp, sp_candidates, 0.5)

        legs = []
        for h, stake in zip(sp_candidates, allocs, strict=False):
            legs.append({"horse": h.num, "odds": h.odds_h5, "p": h.p_score, "stake": round(stake, 2)})
        tickets.append(Ticket(kind="SP_DUTCHING", legs=legs, stake=round(sum(allocs), 2), exp_value=None, exp_payout=None))

    # Ticket 2 — un seul combiné si EV ≥ +40 % et payout > 10 €
    budget_combo = round(budget - (tickets[0].stake if tickets else 0.0), 2)
    budget_combo = max(0.0, budget_combo)

    if budget_combo >= 0.5 and len(tickets) < MAX_TICKETS:
        # Essayer d'abord un CP value (2 chevaux les plus réguliers/p_score)
        ranked = [h for h in horses if (h.p_score or 0) > 0]
        ranked.sort(key=lambda h: (-(h.p_score or 0), h.odds_h5 or 99))

        cp_legs = ranked[:2]
        trio_legs = ranked[:3]

        best_combo: Ticket | None = None

        # CP
        if len(cp_legs) == 2:
            ev, payout = _simulate_cp_ev(cp_legs)
            if ev is not None and payout is not None and ev >= EV_COMBO_MIN and payout >= PAYOUT_MIN:
                stake = min( round(budget_combo, 2), 2.0)  # garder un coût modéré
                best_combo = Ticket(kind="CP", legs=[{"horse": h.num, "p": h.p_score, "odds": h.odds_h5} for h in cp_legs],
                                    stake=stake, exp_value=ev, exp_payout=payout)

        # TRIO (si CP pas assez value)
        if best_combo is None and len(trio_legs) == 3:
            ev, payout = _simulate_trio_ev(trio_legs)
            if ev is not None and payout is not None and ev >= EV_COMBO_MIN and payout >= PAYOUT_MIN:
                stake = min(round(budget_combo, 2), 2.0)
                best_combo = Ticket(kind="TRIO", legs=[{"horse": h.num, "p": h.p_score, "odds": h.odds_h5} for h in trio_legs],
                                    stake=stake, exp_value=ev, exp_payout=payout)

        if best_combo is not None:
            tickets.append(best_combo)

    # Ne pas dépasser le budget
    spent = sum(t.stake for t in tickets)
    if spent > budget:
        scale = budget / max(spent, 1e-9)
        for t in tickets:
            t.stake = round(t.stake * scale, 2)
            for leg in t.legs:
                if isinstance(leg.get("stake"), (int, float)):
                    leg["stake"] = round(leg["stake"] * scale, 2)

    metrics_payload = {
        "overround": (meta or {}).get("overround_h5"),
        "clv_median_30": None,
        "kelly_fraction": _cfg_section("kelly").get("base_fraction", 0.5),
    }
    clv_series = list((meta or {}).get("clv_rolling") or [])
    if clv_series:
        try:
            metrics_payload["clv_median_30"] = stats.median(clv_series)
        except Exception:
            metrics_payload["clv_median_30"] = None
    _write_artifacts(
        metrics_payload,
        _per_horse_rows_from_horses(horses),
        str((meta or {}).get("race_id", (meta or {}).get("course_dir", "R?C?"))),
    )

    return tickets


def build_tickets(
    payload: dict[str, Any] | list[Horse],
    budget: float = BUDGET_DEFAULT,
    meta: dict[str, Any] | None = None,
):
    """Dispatch helper supporting both market dicts and horse lists."""

    if isinstance(payload, dict):
        return build_tickets_roi_first(payload, budget, meta or {})
    if isinstance(payload, list):
        if not payload or isinstance(payload[0], Horse):
            return _build_tickets_from_horses(payload, budget, meta)
        raise TypeError("Expected Horse instances in list payload")
    raise TypeError("Unsupported payload type for build_tickets")

# =============================== Pipeline principal =============================

def _run_pipeline_course_dir(course_dir: str, budget: float = BUDGET_DEFAULT) -> dict[str, Any]:
    horses, meta = load_course(course_dir)

    # Favori par p_score
    favorite = None
    if horses:
        best = max(horses, key=lambda h: (h.p_score or 0.0))
        favorite = best.num if (best.p_score or 0) > 0 else None

    tickets = _build_tickets_from_horses(horses, budget, meta)

    budget_sp = 0.0
    budget_combo = 0.0
    if tickets:
        for t in tickets:
            if t.kind == "SP_DUTCHING":
                budget_sp += t.stake
            else:
                budget_combo += t.stake

    report = Report(
        course_dir=str(course_dir),
        n_partants=meta.get("n_partants", len(horses)),
        overround_h30=meta.get("overround_h30"),
        overround_h5=meta.get("overround_h5"),
        favorite=favorite,
        tickets=tickets,
        budget_total=float(budget),
        budget_sp=round(budget_sp, 2),
        budget_combo=round(budget_combo, 2),
    )

    # Sortie JSON compatible runner_chain.py (clé 'reporting')
    out = {
        "reporting": {
            "course_dir": report.course_dir,
            "n_partants": report.n_partants,
            "overround_h30": report.overround_h30,
            "overround_h5": report.overround_h5,
            "favorite": report.favorite,
            "tickets": [asdict(t) for t in report.tickets],
            "budget": {
                "total": report.budget_total,
                "sp": report.budget_sp,
                "combo": report.budget_combo,
            },
        }
    }
    return out

def _run_pipeline_from_inputs(**kwargs: Any) -> dict[str, Any]:
    """Lightweight pipeline used in unit tests with explicit input paths."""

    partants_path = kwargs.get("partants")
    outdir = kwargs.get("outdir")
    outdir_path = Path(outdir) if outdir else Path(partants_path or ".").parent / "out"
    outdir_path.mkdir(parents=True, exist_ok=True)

    partants_data: dict[str, Any] = {}
    if partants_path:
        try:
            partants_data = json.loads(Path(partants_path).read_text(encoding="utf-8"))
        except Exception:
            partants_data = {}

    runners = partants_data.get("runners") or []
    market_info = partants_data.get("market") or {}
    slots_hint = market_info.get("slots_place") or market_info.get("places")
    market_metrics = _build_market(runners, slots_hint)
    overround_value = market_metrics.get("overround")

    cap = compute_overround_cap()
    metrics: dict[str, Any] = {
        "status": "ok",
        "overround": overround_value,
        "tickets": {"total": 0, "sp": 0, "combo": 0},
    }
    abstention_reasons: list[str] = []
    combo_meta: dict[str, Any] = {"decision": "skip", "notes": []}

    if (overround_value is not None) and (cap is not None) and (overround_value > cap):
        metrics["status"] = "abstain"
        combo_meta = {
            "decision": "reject:overround_above_threshold",
            "notes": ["overround_above_threshold"],
        }
        abstention_reasons.append("overround_above_threshold")
        tickets_payload: list[dict[str, Any]] = []
    else:
        tickets_payload = []

    if abstention_reasons:
        metrics["abstention_reasons"] = abstention_reasons
    metrics["combo"] = combo_meta

    try:
        logging_io.append_json(outdir_path / "metrics.json", {"metrics": metrics})
    except Exception:
        pass

    p_finale_payload = {
        "tickets": tickets_payload,
        "meta": {"market": {"overround": overround_value}},
    }
    (outdir_path / "p_finale.json").write_text(
        json.dumps(p_finale_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    return {"metrics": metrics, "outdir": str(outdir_path)}


def run_pipeline(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """Dispatch between course_dir and explicit-path execution modes."""

    if args and not kwargs:
        return _run_pipeline_course_dir(*args)
    if kwargs:
        return _run_pipeline_from_inputs(**kwargs)
    raise TypeError("run_pipeline requires either positional or keyword inputs")


# =================================== CLI ========================================

def _guess_course_dir(args: argparse.Namespace) -> str | None:
    if args.dir:
        return args.dir
    # Petits helpers si on passe R/C/date
    if args.reunion and args.course:
        rc = f"{args.reunion}{args.course}"
        candidate = Path("data").glob(f"{rc}")
        try:
            return next(iter(candidate)).as_posix()
        except StopIteration:
            return None
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="GPI v5.1 pipeline runner")
    parser.add_argument("--dir", help="Dossier de la course (ex: data/R1C2)")
    parser.add_argument("--reunion", help="R?, ex: R1")
    parser.add_argument("--course", help="C?, ex: C2")
    parser.add_argument("--date", help="YYYY-MM-DD (optionnel)")
    parser.add_argument("--budget", type=float, default=BUDGET_DEFAULT, help="Budget total (par défaut 5 €)")
    args = parser.parse_args(argv)

    course_dir = _guess_course_dir(args)
    if not course_dir:
        print("[ERREUR] Spécifiez --dir data/R?C? ou --reunion/--course.", file=sys.stderr)
        return 2

    res = run_pipeline(course_dir, budget=args.budget)
    print(json.dumps(res, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
