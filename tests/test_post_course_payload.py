from __future__ import annotations

import pytest

from hippique_orchestrator.post_course_payload import (
    PostCourseSummary,
    apply_summary_to_ticket_container,
    build_payload,
    build_payload_from_sources,
    compute_post_course_summary,
    format_csv_line,
    merge_meta,
    summarise_ticket_metrics,
)

# --- Tests for merge_meta ---


def test_merge_meta_both_sources():
    """Test merging metadata from both 'arrivee' and 'tickets' dicts."""
    arrivee = {"meta": {"date": "2025-01-01", "hippodrome": "Vincennes"}}
    tickets = {"meta": {"rc": "R1C1", "model": "v5"}}
    meta = merge_meta(arrivee, tickets)
    assert meta == {"date": "2025-01-01", "hippodrome": "Vincennes", "rc": "R1C1", "model": "v5"}


def test_merge_meta_tickets_takes_priority():
    """'tickets' metadata should be the base, 'arrivee' should not override existing keys."""
    arrivee = {"meta": {"rc": "R9C9"}}
    tickets = {"meta": {"rc": "R1C1"}}
    meta = merge_meta(arrivee, tickets)
    assert meta["rc"] == "R1C1"


def test_merge_meta_with_top_level_keys():
    """Test fallback to top-level keys if not in meta."""
    arrivee = {"date": "2025-01-01", "discipline": "Attelé"}
    tickets = {"rc": "R1C1"}
    meta = merge_meta(arrivee, tickets)
    assert meta["date"] == "2025-01-01"
    assert meta["discipline"] == "Attelé"
    assert meta["rc"] == "R1C1"


def test_merge_meta_handles_missing_or_invalid_inputs():
    assert merge_meta(None, None) == {}
    assert merge_meta({}, {}) == {}
    assert merge_meta({"meta": "not-a-dict"}, {"meta": {"rc": "R1C1"}}) == {"rc": "R1C1"}


def test_merge_meta_model_alias():
    """Test that 'MODEL' is aliased to 'model'."""
    tickets = {"meta": {"MODEL": "v5_special"}}
    meta = merge_meta(None, tickets)
    assert meta["model"] == "v5_special"


# --- Tests for compute_post_course_summary ---


@pytest.fixture
def sample_tickets():
    return [
        {"id": "1", "stake": 10.0, "odds": 5.0, "p": 0.2},  # Winner
        {"id": "2", "stake": 20.0, "odds": 3.0, "p": 0.3},  # Loser
        {"id": "3", "stake": 0.0, "odds": 10.0, "p": 0.1},  # Zero stake
        {"id": "4", "stake": 5.0, "odds": 4.0},  # No 'p' for brier/ev calc
    ]


def test_compute_post_course_summary_nominal(sample_tickets):
    winners = {"1"}
    summary = compute_post_course_summary(sample_tickets, winners)

    # Check ticket updates
    assert sample_tickets[0]["gain_reel"] == 50.0
    assert sample_tickets[0]["result"] == 1
    assert sample_tickets[1]["gain_reel"] == 0.0
    assert sample_tickets[1]["result"] == 0

    # Check summary aggregates
    assert summary.total_stake == 35.0
    assert summary.total_gain == 50.0
    assert summary.roi == pytest.approx((50 - 35) / 35)

    # EV & Brier for ticket 1: p=0.2, stake=10, odds=5. result=1, gain=50
    # ev = 10 * (0.2 * 4 - 0.8) = 0.0. diff_ev = 50 - 0 = 50
    # brier = (1 - 0.2)**2 = 0.64
    # EV & Brier for ticket 2: p=0.3, stake=20, odds=3. result=0, gain=0
    # ev = 20 * (0.3 * 2 - 0.7) = -2.0. diff_ev = 0 - (-2) = 2
    # brier = (0 - 0.3)**2 = 0.09
    # Brier for ticket 3: p=0.1, result=0 -> (0-0.1)**2 = 0.01
    assert summary.ev_total == pytest.approx(0.0 - 2.0)
    assert summary.ev_diff_total == pytest.approx(50.0 + 2.0)
    assert summary.brier_total == pytest.approx(0.64 + 0.09 + 0.01)
    assert summary.brier_mean == pytest.approx((0.64 + 0.09 + 0.01) / 4)


def test_compute_post_course_summary_no_winners(sample_tickets):
    summary = compute_post_course_summary(sample_tickets, winners=set())
    assert summary.total_gain == 0.0
    assert summary.roi == -1.0
    assert summary.total_stake == 35.0


def test_compute_post_course_summary_empty_tickets():
    summary = compute_post_course_summary([], winners={"1"})
    assert summary.total_stake == 0.0
    assert summary.roi == 0.0
    assert summary.as_dict()["brier_mean"] == 0.0


def test_summarise_ticket_metrics():
    """Test summarising metrics from already enriched tickets."""
    enriched_tickets = [
        {"gain_reel": 50, "stake": 10, "roi_reel": 4.0, "result": 1, "p": 0.2},
        {"gain_reel": 0, "stake": 20, "roi_reel": -1.0, "result": 0, "p": 0.3},
    ]
    summary = summarise_ticket_metrics(enriched_tickets)
    assert summary.total_stake == 30.0
    assert summary.total_gain == 50.0
    assert summary.roi == pytest.approx((50 - 30) / 30)
    assert summary.brier_total == pytest.approx((1 - 0.2) ** 2 + (0 - 0.3) ** 2)


# --- Tests for other helpers ---


def test_apply_summary_to_ticket_container():
    """Test that summary metrics are correctly applied to a container dict."""
    container = {}
    summary = PostCourseSummary(
        total_gain=50,
        total_stake=25,
        roi=1.0,
        ev_total=5,
        ev_diff_total=45,
        result_mean=0.5,
        roi_ticket_mean=0.8,
        brier_total=0.7,
        brier_mean=0.35,
    )
    apply_summary_to_ticket_container(container, summary)
    assert container["roi_reel"] == 1.0
    assert container["ev_total"] == 5


def test_build_payload():
    """Test the final payload construction."""
    meta = {"rc": "R1C1"}
    tickets = [{"id": "1"}]
    summary = PostCourseSummary(
        total_gain=10,
        total_stake=5,
        roi=1.0,
        ev_total=1,
        ev_diff_total=9,
        result_mean=1,
        roi_ticket_mean=1,
        brier_total=0,
        brier_mean=0,
    )
    payload = build_payload(meta=meta, arrivee={}, tickets=tickets, summary=summary, winners=["1"])

    assert payload["schema_version"]
    assert payload["meta"]["rc"] == "R1C1"
    assert payload["arrivee"]["result"] == ["1"]
    assert payload["tickets"][0]["id"] == "1"
    assert payload["mises"]["total"] == 5
    assert payload["ev_observees"]["roi_reel"] == 1.0


def test_build_payload_from_sources():
    """Test the high-level helper for building a payload."""
    arrivee = {"meta": {"date": "2025-01-01"}, "result": ["3"]}
    tickets_container = {
        "meta": {"rc": "R1C1"},
        "tickets": [{"id": "3", "stake": 10, "gain_reel": 50}],
    }

    payload = build_payload_from_sources(arrivee, tickets_container)

    assert payload["meta"] == {"date": "2025-01-01", "rc": "R1C1"}
    assert payload["mises"]["total"] == 10
    assert payload["mises"]["gains"] == 50
    assert payload["arrivee"]["result"] == ["3"]


def test_format_csv_line():
    """Test the CSV line formatting."""
    meta = {"rc": "R1C1", "date": "2025-01-01", "model": "v5"}
    summary = PostCourseSummary(
        total_gain=10,
        total_stake=5,
        roi=1.0,
        ev_total=1,
        ev_diff_total=9,
        result_mean=1,
        roi_ticket_mean=1,
        brier_total=0.1,
        brier_mean=0.05,
    )

    line = format_csv_line(meta, summary)
    parts = line.split(';')

    assert parts[0] == "R1C1"
    assert parts[4] == "5.00"
    assert parts[5] == "1.0000"
    assert parts[12] == "v5"
