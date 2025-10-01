"""Tests covering place odds synthesis and market metrics."""

from __future__ import annotations

import logging

import pytest

from pipeline_run import PLACE_FEE, _build_market, _ensure_place_odds


def _expected_synthetic(probability: float) -> float:
    probability_floor = max(probability, 1e-6)
    implied = (1.0 / probability_floor) * (1.0 - PLACE_FEE)
    return max(1.1, implied)


def test_ensure_place_odds_synthesizes_missing_values(caplog: pytest.LogCaptureFixture) -> None:
    """Runners without place odds should receive a synthetic conservative quote."""

    runner = {"id": "7", "name": "Lucky", "p": 0.42}

    with caplog.at_level(logging.INFO):
        sanitized = _ensure_place_odds([runner])

    assert len(sanitized) == 1
    enriched = sanitized[0]
    expected = _expected_synthetic(0.42)
    assert enriched["odds_place"] == pytest.approx(expected)
    assert enriched["odds_place_source"] == "synthetic"
    assert "Synthetic place odds" in caplog.text


def test_ensure_place_odds_preserves_existing_quote() -> None:
    """Existing place odds should be retained without marking them synthetic."""

    runners = [
        {
            "id": "3",
            "name": "Established",
            "odds_place": 2.8,
            "probabilities": {"p": 0.25},
        }
    ]

    sanitized = _ensure_place_odds(runners)

    assert len(sanitized) == 1
    enriched = sanitized[0]
    assert enriched["odds_place"] == pytest.approx(2.8)
    assert "odds_place_source" not in enriched


def test_build_market_uses_synthetic_place_odds() -> None:
    """Synthetic odds should feed into the place overround calculation."""

    runners = [
        {"id": str(idx), "name": f"Runner {idx}", "p": 0.75}
        for idx in range(1, 5)
    ]

    sanitized = _ensure_place_odds(runners)
    assert all(entry.get("odds_place_source") == "synthetic" for entry in sanitized)

    metrics = _build_market(sanitized, slots_place=2)
    assert "overround_place" in metrics

    overround_expected = sum(1.0 / entry["odds_place"] for entry in sanitized) / 2.0
    assert metrics["overround_place"] == pytest.approx(overround_expected)
    assert metrics["overround_place"] > 1.30
