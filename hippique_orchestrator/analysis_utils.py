"""Utility helpers shared by the combo analysis pipeline."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import MutableMapping
from typing import Any

# Constants for overround calculation
_FLAT_HANDICAP_CAP = 1.25
LARGE_FIELD_THRESHOLD = 14

# Constants for musique parsing
TOP3_PLACING = 3
TOP5_PLACING = 5
DEFAULT_BAD_PLACING_SCORE = 10.0

# Constants for volatility calculation
MIN_RACES_FOR_DAI_VOLATILITY = 2
MIN_RACES_FOR_SPREAD_VOLATILITY = 3
PERFORMANCE_SPREAD_THRESHOLD = 5
MAX_PERF_FOR_SPREAD_VOLATILITY = 5
REGULARITY_SCORE_SURE_THRESHOLD = 3.0
TOP3_RATIO_SURE_THRESHOLD = 0.6
REGULARITY_SCORE_NEUTRE_THRESHOLD = 6.0
TOP5_RATIO_NEUTRE_THRESHOLD = 0.7
REGULARITY_SCORE_VOLATIL_THRESHOLD = 6.0

# Constants for "Outsider Repérable"
OUTSIDER_REPARABLE_MIN_ODDS = 8.0
OUTSIDER_REPARABLE_MIN_RECENT_PERFS = 2
OUTSIDER_REPARABLE_MAX_PLACING = 3

# Constants for "Profil Oublié"
PROFIL_OUBLIE_REGULARITY_THRESHOLD = 4.0
PROFIL_OUBLIE_MIN_RACES = 3
PROFIL_OUBLIE_P_PLACE_THRESHOLD = 0.10


def _normalise_text(value: str | None) -> str:
    """Return a lowercase ASCII-normalised representation of ``value``."""

    if value is None:
        return ""
    text = unicodedata.normalize("NFKD", str(value))
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", text).strip().lower()


def _coerce_partants(value: Any) -> int | None:
    """Extract an integer runner count from ``value`` when possible."""
    result = None
    if isinstance(value, bool):  # Prevent bools being treated as ints
        return None
    if isinstance(value, int):
        result = value if value >= 0 else None
    elif isinstance(value, float):
        try:
            result = int(value)
        except (OverflowError, ValueError):
            result = None
    elif isinstance(value, str):
        match = re.search(r"\d+", value)
        if match:
            try:
                result = int(match.group())
            except ValueError:
                result = None
    return result


def compute_overround_cap(
    discipline: Any,
    partants: Any,
    *,
    default_cap: float,
    course_label: Any | None = None,
    context: MutableMapping[str, Any] | None = None,
) -> float:
    """Return the effective overround cap for combo tickets."""

    discipline_norm = _normalise_text(discipline)
    label_norm = _normalise_text(course_label)
    runners = _coerce_partants(partants)

    is_handicap = "handicap" in discipline_norm or "handicap" in label_norm
    is_flat = "plat" in discipline_norm or "plat" in label_norm
    is_flat_handicap = is_handicap and (is_flat or not discipline_norm)
    large_field = runners is not None and runners >= LARGE_FIELD_THRESHOLD

    reason: str | None = None
    if large_field and (is_flat_handicap or is_flat):
        reason = "flat_handicap" if is_handicap else "flat_large_field"

    if reason is None:
        return float(default_cap)

    if context is not None:
        context["triggered"] = True
        context["reason"] = reason
        context["default_cap"] = float(default_cap)
        if runners is not None:
            context["partants"] = runners
        if discipline_norm:
            context["discipline"] = discipline_norm
        elif label_norm:
            context["discipline"] = label_norm
        if course_label is not None:
            context["course_label"] = str(course_label)

    return float(min(default_cap, _FLAT_HANDICAP_CAP))


def parse_musique(musique_str: str) -> dict[str, Any]:
    """
    Parses a 'musique' string (e.g., "1p2p(23)3p4hDAI") into a structured format.
    Extracts placings, identifies disqualifications (D), non-runners (A), etc.
    Calculates basic regularity metrics.
    """
    if not isinstance(musique_str, str) or not musique_str.strip():
        return {
            "raw": musique_str,
            "placings": [],
            "top3_count": 0,
            "top5_count": 0,
            "disqualified_count": 0,
            "recent_performances": [],  # Numeric placings only
            "is_dai": False,
            "regularity_score": 0.0,
            "last_race_placing": None,
        }

    # Normalize the string to handle various separators and formats
    # 'p' (placé), 'h' (haies), 'c' (cross), 'a' (attelé), 'm' (monté)
    # are removed if they appear without numbers.
    # Keep numbers, D (disqualifié), A (arrêté/absent/tombé).
    # Regex will be more robust for parsing.

    # Remove parenthesized years like (23) to clean up the string
    cleaned_musique = re.sub(r"\(\d{2,4}\)", "", musique_str)

    # Regex to find multi-digit numbers (placings) or single letters for special events.
    # \d+ matches one or more digits (e.g., "1", "10", "12").
    # [DATRI] matches D, A, T, R, or I (Disqualifié, Arrêté, Tombé, Retiré, etc.).
    placing_pattern = re.compile(r"(\d+|[DATRI])")

    placings_raw = placing_pattern.findall(cleaned_musique)

    placings_numeric = []
    top3_count = 0
    top5_count = 0
    disqualified_count = 0

    for p in placings_raw:
        if p.isdigit():
            placing_int = int(p)
            placings_numeric.append(placing_int)
            if 1 <= placing_int <= TOP3_PLACING:
                top3_count += 1
            if 1 <= placing_int <= TOP5_PLACING:
                top5_count += 1
        elif p == "D":  # Disqualified
            disqualified_count += 1
        # 'A' for Arrêté/Absent, 'T' for Tombé, 'R' for Retiré could also indicate non-performance
        # For simplicity, we'll focus on D for 'is_dai' as per initial request
        # Other non-numeric performances can be kept in placings_raw

    is_dai = disqualified_count > 0  # Simple check for now

    # Calculate regularity score: lower average placing is better
    # Use a maximum placing (e.g., 9 for no placing) for horses that finish outside top ranks
    # or handle 0 as no placing. Let's assume 0 is a bad placing (e.g. > 9)
    performances_for_score = [
        p if p > 0 else 10 for p in placings_numeric
    ]  # 0 becomes 10 for score
    regularity_score = (
        sum(performances_for_score) / len(performances_for_score)
        if performances_for_score
        else DEFAULT_BAD_PLACING_SCORE
    )

    last_race_placing = (
        placings_numeric[0] if placings_numeric else None
    )  # Most recent numeric placing

    return {
        "raw": musique_str,
        "placings": placings_raw,  # All raw placings (numeric and special codes)
        "top3_count": top3_count,
        "top5_count": top5_count,
        "disqualified_count": disqualified_count,
        "recent_performances_numeric": placings_numeric,  # Only numeric placings
        "is_dai": is_dai,
        "regularity_score": regularity_score,  # Lower is better
        "last_race_placing": last_race_placing,
        "num_races_in_musique": len(placings_raw),  # Total number of performances parsed
    }


def calculate_volatility(musique_data: dict[str, Any]) -> str:
    """
    Calculates the volatility of a horse based on parsed musique data.
    Returns "SÛR", "NEUTRE", or "VOLATIL".
    """
    if not musique_data:
        return "NEUTRE"

    is_dai = musique_data.get("is_dai", False)
    disqualified_count = musique_data.get("disqualified_count", 0)
    regularity_score = musique_data.get("regularity_score", 10.0)
    recent_performances_numeric = musique_data.get("recent_performances_numeric", [])
    num_races_in_musique = musique_data.get("num_races_in_musique", 0)

    volatility = "NEUTRE"  # Default value

    # Rule 1: High disqualification count -> VOLATIL
    if (
        disqualified_count >= 1 and num_races_in_musique > MIN_RACES_FOR_DAI_VOLATILITY
    ) or (is_dai and num_races_in_musique > 0):
        volatility = "VOLATIL"
    # Rule 2: Based on regularity score and consistency
    elif num_races_in_musique > 0:
        # Check for extreme variability
        if len(recent_performances_numeric) >= MIN_RACES_FOR_SPREAD_VOLATILITY:
            min_perf = min(recent_performances_numeric)
            max_perf = max(recent_performances_numeric)
            if (
                (max_perf - min_perf) > PERFORMANCE_SPREAD_THRESHOLD
                and max_perf > MAX_PERF_FOR_SPREAD_VOLATILITY
            ):
                volatility = "VOLATIL"

        # Consistent good results -> SÛR
        if regularity_score <= REGULARITY_SCORE_SURE_THRESHOLD and musique_data.get(
            "top3_count", 0
        ) >= (num_races_in_musique * TOP3_RATIO_SURE_THRESHOLD):
            volatility = "SÛR"
        # Consistent mid-range results -> NEUTRE
        elif (
            REGULARITY_SCORE_NEUTRE_THRESHOLD
            < regularity_score
            <= REGULARITY_SCORE_NEUTRE_THRESHOLD
            and musique_data.get("top5_count", 0)
            >= (num_races_in_musique * TOP5_RATIO_NEUTRE_THRESHOLD)
        ):
            volatility = "NEUTRE"
        # Consistent bad results or high average placing -> VOLATIL
        elif regularity_score > REGULARITY_SCORE_VOLATIL_THRESHOLD:
            volatility = "VOLATIL"

    return volatility


def convert_odds_to_implied_probabilities(
    odds_list: list[float],
) -> tuple[list[float], float]:
    """
    Converts odds to implied probabilities (no vigorish) and calculates overround.

    Args:
        odds_list: A list of decimal odds (e.g., [2.5, 3.0, 4.0]).

    Returns:
        A tuple containing:
            - A list of implied probabilities corresponding to the input odds.
            - The calculated overround for the market.
    """
    if not odds_list:
        return [], 0.0

    raw_probabilities = []
    for odds in odds_list:
        if odds > 1:  # Odds must be greater than 1
            raw_probabilities.append(1 / odds)
        else:
            raw_probabilities.append(0.0)  # Treat invalid odds as 0 probability

    overround = sum(raw_probabilities)

    if overround == 0:
        # Avoid division by zero, return uniform probabilities if all odds are invalid
        implied_probabilities = [1.0 / len(odds_list)] * len(odds_list)
    else:
        implied_probabilities = [p / overround for p in raw_probabilities]

    return implied_probabilities, overround


def score_musique_form(musique_data: dict[str, Any]) -> float:
    """
    Calculates a numerical score based on the horse's musique data (form and regularity).
    Higher score indicates better form.
    """
    if not musique_data:
        return 0.0

    top3_count = musique_data.get("top3_count", 0)
    regularity_score = musique_data.get(
        "regularity_score", 10.0
    )  # Lower is better, so it should reduce score
    num_races_in_musique = musique_data.get("num_races_in_musique", 0)

    score = 0.0

    # Reward for top 3 finishes
    score += top3_count * 2.0  # Each top 3 finish is significant

    # Reward for top 5 finishes (less impactful)
    top5_count_only = musique_data.get("top5_count", 0) - top3_count
    score += top5_count_only * 1.0

    # Penalize for poor regularity (higher regularity_score means worse average placing)
    # The penalty should scale with the number of races to avoid over-penalizing for few races
    if num_races_in_musique > 0:
        # Normalize regularity score to a 0-1 range for penalty application (e.g., 1-10 -> 0-1)
        normalized_regularity_penalty = (
            regularity_score - 1.0
        ) / 9.0  # Assuming score between 1 and 10
        score -= normalized_regularity_penalty * 3.0  # Stronger penalty for bad regularity

    # Small penalty for disqualifications, if not already heavily penalized by volatility
    if musique_data.get("is_dai", False):
        score -= 2.0

    # Ensure score doesn't go too low if it's very bad
    return max(-5.0, score)  # Cap minimum score


def identify_outsider_reparable(runner_data: dict[str, Any]) -> bool:
    """
    Identifies an "outsider repérable" based on specific criteria:
    - odds_place >= 8.0
    - last 2 numeric performances are both <= 3 (top 3 finish)
    """
    odds_place = runner_data.get("odds_place")
    if odds_place is None or odds_place < OUTSIDER_REPARABLE_MIN_ODDS:
        return False

    parsed_musique = runner_data.get("parsed_musique")
    if not parsed_musique:
        return False

    recent_performances = parsed_musique.get("recent_performances_numeric", [])

    # Needs at least 2 recent performances
    if len(recent_performances) < OUTSIDER_REPARABLE_MIN_RECENT_PERFS:
        return False

    # Check if the last 2 performances are both <= 3
    if (
        recent_performances[0] <= OUTSIDER_REPARABLE_MAX_PLACING
        and recent_performances[1] <= OUTSIDER_REPARABLE_MAX_PLACING
    ):
        return True

    return False


def identify_profil_oublie(runner_data: dict[str, Any]) -> bool:
    """
    Identifies a "profil oublié" based on specific criteria:
    - régulier ≤4e sur 3 dernières (average placing <= 4.0 for at least 3 recent performances)
    - peu cité (implied probability for place is below a certain threshold, e.g., < 0.10)
    """
    parsed_musique = runner_data.get("parsed_musique")
    if not parsed_musique:
        return False

    p_place = runner_data.get("p_place")
    if p_place is None:  # Need implied probability to assess "peu cité"
        return False

    regularity_score = parsed_musique.get("regularity_score", 10.0)
    num_races_in_musique = parsed_musique.get("num_races_in_musique", 0)

    # Check "régulier ≤4e sur 3 dernières"
    # Assuming regularity_score <= 4.0 means average placing is 4th or better
    # And needs at least 3 performances
    is_regular_top4_recent = (
        regularity_score <= PROFIL_OUBLIE_REGULARITY_THRESHOLD
        and num_races_in_musique >= PROFIL_OUBLIE_MIN_RACES
    )

    if not is_regular_top4_recent:
        return False

    # Check "peu cité" (not a strong favorite, e.g., implied probability < 10%)
    is_peu_cite = p_place < PROFIL_OUBLIE_P_PLACE_THRESHOLD  # Threshold for "peu cité"

    return is_peu_cite
