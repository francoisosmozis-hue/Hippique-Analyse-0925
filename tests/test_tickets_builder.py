from __future__ import annotations

from tickets_builder import apply_ticket_policy


def test_apply_ticket_policy_filters_homogeneous_trio():
    cfg = {
        "BUDGET_TOTAL": 5.0,
        "SP_RATIO": 0.6,
        "COMBO_RATIO": 0.4,
    }
    runners = [
        {"id": "1", "name": "A", "odds": 2.2},
        {"id": "2", "name": "B", "odds": 2.3},
        {"id": "3", "name": "C", "odds": 2.1},
        {"id": "4", "name": "D", "odds": 2.4},
    ]
    combo_candidates = [
        [
            {
                "id": "combo1",
                "type": "TRIO",
                "legs": ["1", "2", "3"],
                "odds": 15.0,
                "stake": 1.0,
            }
        ]
    ]

    sp_tickets, combos, info = apply_ticket_policy(
        cfg,
        runners,
        combo_candidates=combo_candidates,
        allow_heuristic=True,
    )

    assert combos == []
    assert "homogeneous_field_filtered" in info.get("notes", [])
