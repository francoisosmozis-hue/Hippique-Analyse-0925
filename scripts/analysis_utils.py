#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Utility functions for the analysis pipeline."""

import re
import unicodedata
from typing import Any, Dict


def compute_overround_cap(
    discipline: str | None,
    partants: Any,
    *,
    default_cap: float = 1.30,
    course_label: str | None = None,
    context: Dict[str, Any] | None = None,
) -> float:
    """Return the overround ceiling adjusted for flat-handicap races."""

    try:
        cap = float(default_cap)
    except (TypeError, ValueError):
        cap = 1.30
    if cap <= 0:
        cap = 1.30
    default_cap_value = cap

    def _coerce_partants(value: Any) -> int | None:
        if isinstance(value, (int, float)):
            try:
                return int(value)
            except (TypeError, ValueError):
                return None
        if isinstance(value, str):
            match = re.search(r"\d+", value)
            if match:
                try:
                    return int(match.group())
                except ValueError:
                    return None
        return None

    partants_int = _coerce_partants(partants)

    def _normalise_text(value: str | None) -> str:
        if not value:
            return ""
        normalised = unicodedata.normalize("NFKD", value)
        ascii_only = normalised.encode("ascii", "ignore").decode("ascii")
        return ascii_only.lower()

    discipline_text = _normalise_text(discipline)
    course_text = _normalise_text(course_label)
    combined_text = " ".join(token for token in (discipline_text, course_text) if token)

    flat_tokens = ("plat", "galop", "galopeur")
    handicap_tokens = ("handicap", "hand.", "hcap", "handi")
    obstacle_tokens = ("haies", "steeple", "obstacle", "cross")
    trot_tokens = ("trot", "attel", "mont", "sulky")

    flat_hint = any(token in combined_text for token in flat_tokens)
    is_handicap = any(token in combined_text for token in handicap_tokens)
    is_obstacle = any(token in combined_text for token in obstacle_tokens)
    is_trot = any(token in combined_text for token in trot_tokens)

    is_flat = flat_hint or (is_handicap and not is_obstacle and not is_trot)

    triggered = False
    reason: str | None = None
    adjusted = cap

    def _mark_adjustment(candidate: float, reason_label: str) -> None:
        nonlocal adjusted, triggered, reason
        if candidate < adjusted:
            adjusted = candidate
            triggered = True
            reason = reason_label
        elif candidate == adjusted:
            triggered = True
            if not reason:
                reason = reason_label

    if is_flat:
        if is_handicap:
            candidate = min(adjusted, 1.25)
            _mark_adjustment(candidate, "flat_handicap")
        elif partants_int is not None and partants_int >= 14:
            candidate = min(adjusted, 1.25)
            _mark_adjustment(candidate, "flat_large_field")

    if context is not None:
        context["default_cap"] = default_cap_value
        context["cap"] = adjusted
        if discipline_text:
            context["discipline"] = discipline_text
        if course_text:
            context["course_label"] = course_text
        if partants_int is not None:
            context["partants"] = partants_int
        context["triggered"] = triggered
        if reason:
            context["reason"] = reason

    return adjusted
