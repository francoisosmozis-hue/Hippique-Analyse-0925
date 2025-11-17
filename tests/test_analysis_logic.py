# tests/test_analysis_logic.py
import pathlib
import sys

# Add project root to sys.path to allow importing from src
_PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    # Insert at the beginning to ensure it's checked first
    sys.path.insert(0, str(_PROJECT_ROOT))

# This is a private function, which is not ideal to test directly,
# but it's a necessary first step for a safe refactoring.
from src.rules import _norm_float, filter_tickets_by_odds


def test_norm_float():
    """Tests the float normalization utility."""
    assert _norm_float("3,5") == 3.5
    assert _norm_float("4.0") == 4.0
    assert _norm_float(5) == 5.0
    assert _norm_float("invalid") is None
    assert _norm_float(None) is None


def test_filter_sp_and_cp_by_odds():
    """
    Tests the odds filtering logic for SP and CP tickets.
    - SP tickets should be kept only if their decimal odds are >= 5.0.
    - CP tickets should be kept only if the sum of their decimal odds is >= 6.0.
    """
    sample_payload = {
        "tickets": [
            # 1. SP to be removed (odds < 5.0)
            {
                "type": "SP",
                "legs": [{"cote_place": 3.5}]
            },
            # 2. SP to be kept (odds >= 5.0)
            {
                "type": "SP",
                "id": "SP_OK",
                "legs": [{"cote_place": 5.0}]
            },
            # 3. CP to be removed (sum of odds < 6.0)
            {
                "type": "COUPLE_PLACE",
                "legs": [{"cote_place": 2.5}, {"cote_place": 3.0}] # sum = 5.5
            },
            # 4. CP to be kept (sum of odds >= 6.0)
            {
                "type": "COUPLE_PLACE",
                "id": "CP_OK",
                "legs": [{"cote_place": 3.0}, {"cote_place": 4.0}] # sum = 7.0
            },
            # 5. Another type of ticket, should always be kept
            {
                "type": "TRIO",
                "id": "TRIO_OK",
                "legs": [{}, {}]
            }
        ]
    }

    # Apply the filtering logic
    filter_tickets_by_odds(sample_payload)

    # Assertions
    kept_tickets = sample_payload.get("tickets", [])
    kept_ids = {ticket.get("id") for ticket in kept_tickets}

    assert len(kept_tickets) == 3
    assert "SP_OK" in kept_ids
    assert "CP_OK" in kept_ids
    assert "TRIO_OK" in kept_ids

    # Check that rejection notes were added
    notes = sample_payload.get("notes", [])
    assert len(notes) == 2
    assert any("SP retiré" in note for note in notes)
    assert any("CP retiré" in note for note in notes)


def test_filter_by_odds_uses_market_fallback():
    """
    Tests that the filter can find odds in the main market object if not
    present on the ticket leg itself.
    """
    payload = {
        "market": {
            "horses": [
                {"num": "5", "cote": "6,0"} # Odds are here
            ]
        },
        "tickets": [
            {
                "type": "SP",
                "id": "SP_FALLBACK_OK",
                "legs": [
                    {"num": "5"} # But not here
                ]
            }
        ]
    }

    filter_tickets_by_odds(payload)

    kept_tickets = payload.get("tickets", [])
    assert len(kept_tickets) == 1
    assert kept_tickets[0].get("id") == "SP_FALLBACK_OK"
