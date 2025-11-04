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
