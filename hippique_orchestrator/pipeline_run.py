import logging
import math
import pathlib
import statistics
from itertools import combinations
from typing import Any

from hippique_orchestrator.kelly import calculate_kelly_fraction
from hippique_orchestrator.simulate_wrapper import evaluate_combo

# --- Logging ---
logger = logging.getLogger(__name__)

CALIB_PATH = pathlib.Path(__file__).resolve().parent / "config" / "payout_calibration.yaml"




# ==============================================================================
# Helper Functions
# ==============================================================================


def _clamp(value: float, min_val: float, max_val: float) -> float:
    """Clamps a value between a minimum and a maximum."""
    return max(min(value, max_val), min_val)


def _normalize_probs(probs: list[float]) -> list[float]:
    """Normalizes a list of probabilities so that they sum to 1."""
    total = sum(probs)
    if total == 0:
        return [1 / len(probs)] * len(probs) if probs else []
    return [p / total for p in probs]


# ==============================================================================
# Probability Adjustment Logic
# ==============================================================================


def _apply_base_stat_adjustment(runners: list[dict], je_stats: dict, weights: dict) -> list[float]:
    """Applies JE and Horse Stats adjustments. Returns UNNORMALIZED probabilities."""

    def get_je_factor(runner_stats: dict, je_weights: dict) -> float:
        je_bonus = je_weights.get("je_bonus", 1.0)
        je_malus = je_weights.get("je_malus", 1.0)

        j_rate_bonus_threshold = je_weights.get("j_rate_bonus_threshold", 12.0)
        e_rate_bonus_threshold = je_weights.get("e_rate_bonus_threshold", 15.0)
        j_rate_malus_threshold = je_weights.get("j_rate_malus_threshold", 6.0)
        e_rate_malus_threshold = je_weights.get("e_rate_malus_threshold", 8.0)

        try:
            j_rate = (
                float(runner_stats.get("j_rate"))
                if runner_stats.get("j_rate") is not None
                else None
            )
            e_rate = (
                float(runner_stats.get("e_rate"))
                if runner_stats.get("e_rate") is not None
                else None
            )
        except (ValueError, TypeError):
            return 1.0

        if j_rate is not None and e_rate is not None:
            if j_rate >= j_rate_bonus_threshold or e_rate >= e_rate_bonus_threshold:
                return je_bonus
            if j_rate < j_rate_malus_threshold or e_rate < e_rate_malus_threshold:
                return je_malus
        return 1.0

    def get_horse_stats_factor(runner_stats: dict, horse_weights: dict) -> float:
        factor = 1.0
        # This logic can be expanded as per GPI spec for short_form_place, etc.
        return factor

    adjusted_probs = []
    je_weights = weights.get("base", {})
    horse_weights = weights.get("horse_stats", {})

    for runner in runners:
        p_base = runner["p_base"]
        runner_num = str(runner.get("num"))
        runner_je_stats = je_stats.get(runner_num, {})

        factor = 1.0
        factor *= get_je_factor(runner_je_stats, je_weights)
        factor *= get_horse_stats_factor(runner_je_stats, horse_weights)

        adjusted_probs.append(p_base * factor)

    return adjusted_probs


def _apply_chrono_adjustment(
    runners: list[dict], je_stats: dict, chrono_config: dict
) -> list[float]:
    """
    Applies chrono adjustment factor based on GPI v5.1 spec.
    ASSUMPTION: je_stats contains 'last_3_chrono': [float, float, float].
    """
    k_c = chrono_config.get("k_c", 0.18)
    factors = []

    best_chronos = []
    for runner in runners:
        runner_num = str(runner.get("num"))
        runner_je_stats = je_stats.get(runner_num, {})
        # Ensure last_3_chrono is a list of numbers
        last_3_chrono = runner_je_stats.get("last_3_chrono", [])
        if (
            last_3_chrono
            and isinstance(last_3_chrono, list)
            and all(isinstance(i, (int, float)) for i in last_3_chrono)
        ):
            best_chronos.append((runner["num"], min(last_3_chrono)))

    if not best_chronos:
        return [1.0] * len(runners)

    chrono_values = [c[1] for c in best_chronos]
    rk_median = statistics.median(chrono_values)

    best_chronos_map = dict(best_chronos)
    for runner in runners:
        runner_num = runner.get("num")
        rk_best3 = best_chronos_map.get(runner_num)

        if rk_best3 is None:
            factors.append(1.0)
            continue

        z_chrono = _clamp((rk_median - rk_best3) / 0.5, -2.0, 2.0)
        f_chrono = _clamp(math.exp(k_c * z_chrono), 0.85, 1.25)

        if rk_best3 > rk_median + 1.0:
            f_chrono = min(f_chrono, 0.92)

        factors.append(f_chrono)

    return factors


def _apply_drift_adjustment(
    runners: list[dict], h30_odds_map: dict, drift_config: dict
) -> list[float]:
    """Applies odds drift adjustment factor based on GPI v5.1 spec."""
    k_d_default = drift_config.get("k_d", 0.70)
    drift_threshold = drift_config.get("threshold", 0.07)
    fav_odds_threshold = drift_config.get("favorite_odds", 4.0)
    fav_drift_factor = drift_config.get("favorite_factor", 1.20)
    out_odds_threshold = drift_config.get("outsider_odds", 8.0)
    out_steam_factor = drift_config.get("outsider_steam_factor", 0.85)
    high_odds_threshold = drift_config.get("high_odds", 60.0)
    extreme_drift_factor = drift_config.get("extreme_factor", 1.80)
    factors = []

    for runner in runners:
        runner_num = runner.get("num")
        odds_5 = runner.get("odds_place")
        odds_30 = h30_odds_map.get(runner_num)

        if odds_5 is None or odds_30 is None or odds_30 == 0:
            factors.append(1.0)
            continue

        if abs(odds_5 / odds_30 - 1.0) < drift_threshold:
            factors.append(1.0)
            continue

        r = math.log(odds_5 / odds_30)
        k_d = k_d_default

        if odds_30 <= fav_odds_threshold and (odds_5 / odds_30) >= fav_drift_factor:
            k_d = drift_config.get("k_d_fav_drift", 0.90)
        elif odds_30 >= out_odds_threshold and (odds_5 / odds_30) <= out_steam_factor:
            k_d = drift_config.get("k_d_out_steam", 0.85)

        f_drift = _clamp(math.exp(-k_d * r), 0.80, 1.20)

        if odds_30 > high_odds_threshold or odds_5 > high_odds_threshold:
            f_drift = _clamp(f_drift, 0.90, 1.10)
        if (odds_5 / odds_30) > extreme_drift_factor:
            f_drift = max(f_drift, 0.80)

        factors.append(f_drift)

    return factors


# ==============================================================================
# Main Ticket Generation Logic
# ==============================================================================


def _initialize_and_validate(
    snapshot_data: dict[str, Any], gpi_config: dict[str, Any]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    runners = snapshot_data.get("runners", [])

    if not runners:
        raise ValueError("No runners found")

    try:
        config = {
            "budget": gpi_config["budget"],
            "max_vol_per_horse": gpi_config.get("max_vol_per_horse", 0.6),
            "je_stats": gpi_config.get("je_stats"),
            "h30_snapshot_data": gpi_config.get("h30_snapshot_data"),
            "sp_config": gpi_config["tickets"]["sp_dutching"],
            "exotics_config": gpi_config["tickets"]["exotics"],
            "chrono_config": gpi_config.get("adjustments", {}).get("chrono", {}),
            "drift_config": gpi_config.get("adjustments", {}).get("drift", {}),
            "adjustments": gpi_config.get("adjustments", {}), # For other adjustments
            "roi_min_global": gpi_config["roi_min_global"],
            "roi_min_sp": gpi_config["roi_min_sp"],
            "weights": gpi_config["weights"],
            "overround_max": gpi_config["overround_max_exotics"],
            "ev_min_combo": gpi_config["ev_min_combo"],
            "payout_min_combo": gpi_config["payout_min_combo"],
        }

    except KeyError as e:
        raise ValueError(f"Configuration file is missing a critical key: {e}") from e

    return runners, config


def _calculate_adjusted_probabilities(
    runners: list[dict[str, Any]], config: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[str]]:
    je_stats = config["je_stats"] or {}
    weights = config["weights"]
    chrono_config = config["chrono_config"]
    drift_config = config["drift_config"]
    h30_snapshot_data = config.get("h30_snapshot_data")

    analysis_messages = []
    p_bases = []
    for runner in runners:
        p_base = runner.get("p_no_vig") or runner.get("p_place")
        if p_base is None:
            raise ValueError("Missing base probabilities")
        runner["p_base"] = p_base
        p_bases.append(p_base)

    p_adjusted_stat = _apply_base_stat_adjustment(runners, je_stats, weights)
    chrono_factors = _apply_chrono_adjustment(runners, je_stats, chrono_config)
    p_adjusted_chrono = [p * f for p, f in zip(p_adjusted_stat, chrono_factors, strict=False)]

    p_unnormalized = p_adjusted_chrono
    if h30_snapshot_data:
        h30_runners = h30_snapshot_data.get("runners", [])
        h30_odds_map = {
            r.get("num"): r.get("odds_place")
            for r in h30_runners
            if r.get("num") and r.get("odds_place")
        }
        if h30_odds_map:
            drift_factors = _apply_drift_adjustment(runners, h30_odds_map, drift_config)
            p_unnormalized = [p * f for p, f in zip(p_adjusted_chrono, drift_factors, strict=False)]
            analysis_messages.append("Drift adjustment applied.")

    p_finale_list = _normalize_probs(p_unnormalized)
    for i, runner in enumerate(runners):
        runner["p_unnormalized_for_roi"] = p_unnormalized[i]
        runner["p_finale"] = p_finale_list[i]

    return runners, analysis_messages


def _generate_sp_dutching_tickets(
    runners: list[dict[str, Any]],
    config: dict[str, Any],
    final_tickets: list[dict[str, Any]],
    analysis_messages: list[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    sp_config = config["sp_config"]
    roi_min_sp = config["roi_min_sp"]
    budget = config["budget"]

    sp_budget = budget * sp_config["budget_ratio"]
    sp_candidates = []
    for r in runners:
        odds = r.get("odds_place", 0)
        prob_for_roi = r.get("p_unnormalized_for_roi", 0)
        if odds > 1 and sp_config["odds_range"][0] <= odds <= sp_config["odds_range"][1]:
            roi = prob_for_roi * (odds - 1) - (1 - prob_for_roi)
            if roi >= roi_min_sp:
                sp_candidates.append(
                    {
                        "num": r["num"],
                        "odds": odds,
                        "prob": r["p_finale"],
                        "roi": roi,
                    }
                )

    if len(sp_candidates) >= sp_config["legs_min"]:
        kelly_frac = sp_config["kelly_frac"]
        stakes = {}
        total_kelly_frac = 0
        for cand in sp_candidates:
            frac = calculate_kelly_fraction(cand["prob"], cand["odds"], kelly_frac)
            if frac > 0:
                stakes[cand["num"]] = frac
                total_kelly_frac += frac

        final_stakes = {}
        if total_kelly_frac > 0:
            for num, frac in stakes.items():
                final_stakes[num] = (frac / total_kelly_frac) * sp_budget

        if final_stakes:
            total_stake = sum(final_stakes.values())
            weighted_roi = (
                sum(
                    c["roi"] * final_stakes[c["num"]]
                    for c in sp_candidates
                    if c["num"] in final_stakes
                )
                / total_stake
                if total_stake > 0
                else 0
            )
            final_tickets.append(
                {
                    "type": "SP_DUTCHING",
                    "stake": total_stake,
                    "roi_est": weighted_roi,
                    "horses": list(final_stakes.keys()),
                    "details": final_stakes,
                }
            )
            analysis_messages.append(f"SP Dutching ticket created with {len(final_stakes)} horses.")
    return sp_candidates, final_tickets, analysis_messages


def _get_legs_for_exotic_type(exotic_type: str) -> int:
    """Returns the number of horses required for a given exotic bet type."""
    if exotic_type in ["COUPLE", "COUPLE_PLACE", "ZE234"]: # Assuming ZE234 is a 2-horse bet
        return 2
    if exotic_type == "TRIO":
        return 3
    if exotic_type == "ZE4":
        return 4
    # Add other types as needed
    logger.warning(f"Unknown exotic type '{exotic_type}', assuming 3 legs.")
    return 3


def _generate_exotic_tickets(
    sp_candidates: list[dict[str, Any]],
    snapshot_data: dict[str, Any],
    config: dict[str, Any],
    final_tickets: list[dict[str, Any]],
    analysis_messages: list[str],
) -> tuple[list[dict[str, Any]], list[str]]:
    exotics_config = config["exotics_config"]
    overround_max = config["overround_max"]
    budget = config["budget"]
    sp_config = config["sp_config"]
    ev_min_combo = config["ev_min_combo"]
    payout_min_combo = config["payout_min_combo"]
    adjustments = config.get("adjustments", {})
    min_sp_candidates_global = adjustments.get("exotics", {}).get("min_sp_candidates", 3)

    exotics_allowed_by_overround = snapshot_data.get("market", {}).get("overround_place", 0.0) <= overround_max
    if not exotics_allowed_by_overround:
        analysis_messages.append("Exotics forbidden due to high overround.")
        return final_tickets, analysis_messages

    allowed_exotic_types = exotics_config.get("allowed", [])
    if not allowed_exotic_types:
        return final_tickets, analysis_messages

    combo_budget = budget * (1 - sp_config["budget_ratio"])
    best_combo_overall = None

    for exotic_type in allowed_exotic_types:
        num_legs = _get_legs_for_exotic_type(exotic_type)
        if len(sp_candidates) < num_legs:
            continue

        exotic_combinations = list(combinations(sp_candidates, num_legs))

        for combo in exotic_combinations:
            combo_legs = list(combo)
            try:
                combo_odds_heuristic = math.prod(leg["odds"] for leg in combo_legs)
            except (TypeError, KeyError):
                continue

            combo_eval_result = evaluate_combo(
                tickets=[{"type": exotic_type, "odds": combo_odds_heuristic, "legs": combo_legs}],
                bankroll=combo_budget,
                calibration=CALIB_PATH,
            )

            if combo_eval_result.get("status") == "ok":
                is_profitable = (
                    combo_eval_result.get("roi", 0) >= ev_min_combo
                    and combo_eval_result.get("payout_expected", 0) >= payout_min_combo
                )
                if is_profitable:
                    current_combo_details = {
                        "type": exotic_type,
                        "legs": [c["num"] for c in combo_legs],
                        "roi": combo_eval_result.get("roi"),
                        "payout": combo_eval_result.get("payout_expected"),
                    }

                    if best_combo_overall is None or current_combo_details["roi"] > best_combo_overall["roi"]:
                        best_combo_overall = current_combo_details

    if best_combo_overall:
        final_tickets.append(
            {
                "type": best_combo_overall["type"],
                "stake": combo_budget,
                "roi_est": best_combo_overall["roi"],
                "payout_est": best_combo_overall["payout"],
                "horses": best_combo_overall["legs"],
            }
        )
        analysis_messages.append(f"Profitable {best_combo_overall['type']} combo found: {best_combo_overall['legs']}.")

    return final_tickets, analysis_messages


def _finalize_and_decide(
    final_tickets: list[dict[str, Any]],
    roi_min_global: float,
    analysis_messages: list[str],
) -> dict[str, Any]:
    if not final_tickets:
        return {
            "gpi_decision": "Abstain: No valid tickets found",
            "tickets": [],
            "roi_global_est": 0,
            "message": " ".join(
                ["No profitable tickets found after analysis."] + analysis_messages
            ),
        }

    total_stake = sum(t.get("stake", 0) for t in final_tickets)
    roi_global_est = (
        sum(t.get("roi_est", 0) * t.get("stake", 0) for t in final_tickets) / total_stake
        if total_stake > 0
        else 0
    )

    if roi_global_est < roi_min_global:
        return {
            "gpi_decision": (
                f"Abstain: Global ROI ({roi_global_est:.2f}) < threshold ({roi_min_global:.2f})"
            ),
            "tickets": [],
            "roi_global_est": roi_global_est,
            "message": f"Global ROI ({roi_global_est:.2f}) is below the minimum threshold.",
        }

    return {
        "gpi_decision": "Play",
        "tickets": final_tickets,
        "roi_global_est": roi_global_est,
        "message": "Profitable tickets found. " + " ".join(analysis_messages),
    }


def generate_tickets(snapshot_data: dict[str, Any], gpi_config: dict[str, Any]) -> dict[str, Any]:
    """
    Génère des tickets de paris basés sur les règles GPI v5.2,
    incluant les ajustements Chrono et Drift.
    """
    analysis_messages = []
    try:
        runners, config = _initialize_and_validate(snapshot_data, gpi_config)
        runners, analysis_messages = _calculate_adjusted_probabilities(runners, config)
    except ValueError as e:
        return {"gpi_decision": f"Abstain: {e}", "tickets": [], "roi_global_est": 0}

    final_tickets = []
    sp_candidates, final_tickets, analysis_messages = _generate_sp_dutching_tickets(
        runners, config, final_tickets, analysis_messages
    )
    final_tickets, analysis_messages = _generate_exotic_tickets(
        sp_candidates,
        snapshot_data,
        config,
        final_tickets,
        analysis_messages,
    )
    return _finalize_and_decide(final_tickets, config["roi_min_global"], analysis_messages)
