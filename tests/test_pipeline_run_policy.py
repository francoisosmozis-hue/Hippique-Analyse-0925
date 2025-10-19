import pytest
from pipeline_run import enforce_ror_threshold

def test_enforce_ror_threshold_success():
    """ROI is above or equal to threshold, should pass."""
    tickets = [{"id": 1}]
    final_tickets, _, meta = enforce_ror_threshold(
        cfg={},
        runners=[],
        combo_tickets=tickets,
        bankroll=100,
        global_roi=0.25,
        roi_min_threshold=0.20
    )
    assert final_tickets == tickets
    assert meta["status"] == "success"
    assert not meta["applied"]

def test_enforce_ror_threshold_failure():
    """ROI is below threshold, should fail and return no tickets."""
    tickets = [{"id": 1}]
    final_tickets, _, meta = enforce_ror_threshold(
        cfg={},
        runners=[],
        combo_tickets=tickets,
        bankroll=100,
        global_roi=0.15,
        roi_min_threshold=0.20
    )
    assert final_tickets == []
    assert meta["status"] == "rejected_roi"
    assert meta["applied"]

def test_enforce_ror_threshold_edge_case():
    """ROI is exactly at the threshold."""
    tickets = [{"id": 1}]
    final_tickets, _, meta = enforce_ror_threshold(
        cfg={},
        runners=[],
        combo_tickets=tickets,
        bankroll=100,
        global_roi=0.20,
        roi_min_threshold=0.20
    )
    assert final_tickets == tickets
    assert meta["status"] == "success"
