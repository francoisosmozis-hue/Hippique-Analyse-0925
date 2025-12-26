"""Utility helpers shared by the combo analysis pipeline."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import MutableMapping
from typing import Any

_FLAT_HANDICAP_CAP = 1.25


def _normalise_text(value: str | None) -> str:
    """Return a lowercase ASCII-normalised representation of ``value``."""

    if value is None:
        return ""
    text = unicodedata.normalize("NFKD", str(value))
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", text).strip().lower()


def _coerce_partants(value: Any) -> int | None:
    """Extract an integer runner count from ``value`` when possible."""

    if isinstance(value, bool):  # Prevent bools being treated as ints
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, float):
        try:
            return int(value)
        except (OverflowError, ValueError):
            return None
    if isinstance(value, str):
        match = re.search(r"\d+", value)
        if match:
            try:
                return int(match.group())
            except ValueError:
                return None
    return None


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
    large_field = runners is not None and runners >= 14

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
            "recent_performances": [], # Numeric placings only
            "is_dai": False,
            "regularity_score": 0.0,
            "last_race_placing": None,
        }

    # Normalize the string to handle various separators and formats
    # Common transformations: remove 'p' (placé), 'h' (haies), 'c' (cross), 'a' (attelé), 'm' (monté) if they appear without numbers
    # Keep numbers, D (disqualifié), A (arrêté/absent/tombé).
    # Regex will be more robust for parsing.

    # Clean up parenthesized years/race numbers, convert common special codes
    cleaned_musique = re.sub(r'\(\d{2,4}\)', '', musique_str).upper()
    cleaned_musique = cleaned_musique.replace('P', '').replace('H', '').replace('C', '') # Remove common placings/types

    # Regex to find individual placings or special indicators.
    # Matches: numbers (0-9), 'D' (Disqualifié), 'A' (Arrêté/Absent), 'T' (Tombé), 'R' (Retiré)
    # This pattern assumes each char or digit is a placing.
    placing_pattern = re.compile(r'([0-9DATR]){1}')

    placings_raw = placing_pattern.findall(cleaned_musique)

    placings_numeric = []
    top3_count = 0
    top5_count = 0
    disqualified_count = 0

    for p in placings_raw:
        if p.isdigit():
            placing_int = int(p)
            placings_numeric.append(placing_int)
            if 1 <= placing_int <= 3:
                top3_count += 1
            if 1 <= placing_int <= 5:
                top5_count += 1
        elif p == 'D': # Disqualified
            disqualified_count += 1
        # 'A' for Arrêté/Absent, 'T' for Tombé, 'R' for Retiré could also indicate non-performance
        # For simplicity, we'll focus on D for 'is_dai' as per initial request
        # Other non-numeric performances can be kept in placings_raw

    is_dai = disqualified_count > 0 # Simple check for now

    # Calculate regularity score: lower average placing is better
    # Use a maximum placing (e.g., 9 for no placing) for horses that finish outside top ranks
    # or handle 0 as no placing. Let's assume 0 is a bad placing (e.g. > 9)
    performances_for_score = [p if p > 0 else 10 for p in placings_numeric] # 0 becomes 10 for score
    regularity_score = sum(performances_for_score) / len(performances_for_score) if performances_for_score else 10.0

    last_race_placing = placings_numeric[0] if placings_numeric else None # Most recent numeric placing

    return {
        "raw": musique_str,
        "placings": placings_raw, # All raw placings (numeric and special codes)
        "top3_count": top3_count,
        "top5_count": top5_count,
        "disqualified_count": disqualified_count,
        "recent_performances_numeric": placings_numeric, # Only numeric placings
        "is_dai": is_dai,
        "regularity_score": regularity_score, # Lower is better
        "last_race_placing": last_race_placing,
        "num_races_in_musique": len(placings_raw) # Total number of performances parsed
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

    # Rule 1: High disqualification count -> VOLATIL
    if disqualified_count >= 1 and num_races_in_musique > 2: # At least one DAI in recent races
        return "VOLATIL"
    if is_dai and num_races_in_musique > 0: # Any DAI
        return "VOLATIL"

    # Rule 2: Based on regularity score and consistency
    if num_races_in_musique > 0:
        # Check for extreme variability (e.g., a mix of very good and very bad results)
        if len(recent_performances_numeric) >= 3:
            # Simple check for spread in performances
            min_perf = min(recent_performances_numeric)
            max_perf = max(recent_performances_numeric)
            if (max_perf - min_perf) > 5 and max_perf > 5: # Large spread and includes bad results
                return "VOLATIL"

        # Consistent good results -> SÛR
        if regularity_score <= 3.0 and musique_data.get("top3_count", 0) >= (num_races_in_musique * 0.6): # At least 60% in top3
            return "SÛR"

        # Consistent mid-range results -> NEUTRE
        if 3.0 < regularity_score <= 6.0 and musique_data.get("top5_count", 0) >= (num_races_in_musique * 0.7): # At least 70% in top5
            return "NEUTRE"

        # Consistent bad results or high average placing -> VOLATIL
        if regularity_score > 6.0:
            return "VOLATIL"

    # Default if not enough data or rules don't strictly apply
    return "NEUTRE"


def convert_odds_to_implied_probabilities(odds_list: list[float]) -> tuple[list[float], float]:
    """
    Converts a list of odds to implied probabilities (without vigorish) and calculates the overround.
    
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
        if odds > 1: # Odds must be greater than 1
            raw_probabilities.append(1 / odds)
        else:
            raw_probabilities.append(0.0) # Treat invalid odds as 0 probability

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
    regularity_score = musique_data.get("regularity_score", 10.0) # Lower is better, so it should reduce score
    num_races_in_musique = musique_data.get("num_races_in_musique", 0)

    score = 0.0

    # Reward for top 3 finishes
    score += top3_count * 2.0 # Each top 3 finish is significant

    # Reward for top 5 finishes (less impactful)
    top5_count_only = musique_data.get("top5_count", 0) - top3_count
    score += top5_count_only * 1.0

    # Penalize for poor regularity (higher regularity_score means worse average placing)
    # The penalty should scale with the number of races to avoid over-penalizing for few races
    if num_races_in_musique > 0:
        # Normalize regularity score to a 0-1 range for penalty application (e.g., 1-10 -> 0-1)
        normalized_regularity_penalty = (regularity_score - 1.0) / 9.0 # Assuming score between 1 and 10
        score -= normalized_regularity_penalty * 3.0 # Stronger penalty for bad regularity

    # Small penalty for disqualifications, if not already heavily penalized by volatility
    if musique_data.get("is_dai", False):
        score -= 2.0

    # Ensure score doesn't go too low if it's very bad
    return max(-5.0, score) # Cap minimum score


def identify_outsider_reparable(runner_data: dict[str, Any]) -> bool:
    """
    Identifies an "outsider repérable" based on specific criteria:
    - odds_place >= 8.0
    - last 2 numeric performances are both <= 3 (top 3 finish)
    """
    odds_place = runner_data.get("odds_place")
    if odds_place is None or odds_place < 8.0:
        return False

    parsed_musique = runner_data.get("parsed_musique")
    if not parsed_musique:
        return False

    recent_performances = parsed_musique.get("recent_performances_numeric", [])

    # Needs at least 2 recent performances
    if len(recent_performances) < 2:
        return False

    # Check if the last 2 performances are both <= 3
    if recent_performances[0] <= 3 and recent_performances[1] <= 3:
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
    if p_place is None: # Need implied probability to assess "peu cité"
        return False

    regularity_score = parsed_musique.get("regularity_score", 10.0)
    num_races_in_musique = parsed_musique.get("num_races_in_musique", 0)

    # Check "régulier ≤4e sur 3 dernières"
    # Assuming regularity_score <= 4.0 means average placing is 4th or better
    # And needs at least 3 performances
    is_regular_top4_recent = (regularity_score <= 4.0) and (num_races_in_musique >= 3)

    if not is_regular_top4_recent:
        return False

    # Check "peu cité" (not a strong favorite, e.g., implied probability < 10%)
    is_peu_cite = p_place < 0.10 # Threshold for "peu cité"

    return is_peu_cite
