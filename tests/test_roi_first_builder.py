from src.hippique_orchestrator.pipeline_run import build_tickets_roi_first


def _base_market():
    return {
        "sp_odds": [2.5, 3.5, 5.5],
        "sp_meta": [
            {"odds": 2.5, "ecurie": "A", "driver": "X", "chrono_last": 1.2},
            {"odds": 3.5, "ecurie": "B", "driver": "Y", "chrono_last": 1.1},
            {"odds": 5.5, "ecurie": "C", "driver": "Z", "chrono_last": 1.0},
        ],
        "model_probs": [0.95, 0.60, 0.50],
    }


def test_overround_gate_blocks_market():
    market = _base_market()
    market["sp_odds"] = [1.5, 1.5, 1.5]
    result = build_tickets_roi_first(market, budget=5.0, meta={"discipline": "trot", "n_partants": 6})
    assert result["tickets"] == []
    assert result["abstention"].startswith("OVERROUND")


def test_builds_sp_ticket_with_mid_odds():
    market = _base_market()
    result = build_tickets_roi_first(market, budget=5.0, meta={"discipline": "plat", "n_partants": 10})
    assert result["abstention"] is None
    assert result["tickets"]
    sp_ticket = result["tickets"][0]
    assert sp_ticket["type"] == "SP_DUTCH"
    assert abs(sum(leg["stake"] for leg in sp_ticket["legs"]) - sp_ticket["stake"]) < 0.02
