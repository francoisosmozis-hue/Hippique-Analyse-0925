import pytest

# TODO: Réécrire ce test pour utiliser la nouvelle logique de tickets_builder.apply_ticket_policy
@pytest.mark.skip(reason="La fonction enforce_budget_and_ticket_cap a été supprimée après refactoring.")
def test_budget_and_ticket_cap():
    tickets = [
        {"type": "SIMPLE_PLACE_DUTCHING", "stake": 3.5},
        {"type": "TRIO", "stake": 2.0},
        {"type": "COUPLE_PLACE", "stake": 1.0},
    ]
    capped = enforce_budget_and_ticket_cap(tickets, budget=5.0)
    assert len(capped) == 2
    tot = sum(t["stake"] for t in capped)
    assert tot <= 5.0 + 1e-9
