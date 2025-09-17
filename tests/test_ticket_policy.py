import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from simulate_ev import allocate_dutching_sp
from tickets_builder import PAYOUT_MIN_COMBO, allow_combo

def test_max_two_tickets():
    cfg = {
        "BUDGET_TOTAL": 100,
        "SP_RATIO": 1.0,
        "MAX_VOL_PAR_CHEVAL": 0.60,
        "MIN_STAKE_SP": 0.10,
        "ROUND_TO_SP": 0.10,
        "KELLY_FRACTION": 1.0,
        "MAX_TICKETS_SP": 2,
    }
    runners = [
        {"id": "1", "name": "A", "odds": 2.0, "p": 0.6},
        {"id": "2", "name": "B", "odds": 3.0, "p": 0.4},
        {"id": "3", "name": "C", "odds": 5.0, "p": 0.25},
    ]
    tickets, _ = allocate_dutching_sp(cfg, runners)
    tickets.sort(key=lambda t: t["ev_ticket"], reverse=True)
    tickets = tickets[: int(cfg["MAX_TICKETS_SP"])]
    assert len(tickets) <= 2



def test_combo_thresholds_cfg():
    cfg = {
        "EV_MIN_GLOBAL": 0.0,
        "ROI_MIN_GLOBAL": 0.0,
        "MIN_PAYOUT_COMBOS": PAYOUT_MIN_COMBO,
    }

    # default threshold from cfg keeps the 10€ combo and rejects below
    assert not allow_combo(ev_global=0.5, roi_global=0.5, payout_est=9.9, cfg=cfg)
    assert allow_combo(ev_global=0.5, roi_global=0.5, payout_est=10.0, cfg=cfg)

    # increasing payout threshold via cfg rejects lower payouts
    cfg["MIN_PAYOUT_COMBOS"] = 15.0
    assert not allow_combo(ev_global=0.5, roi_global=0.5, payout_est=14.9, cfg=cfg)
    assert allow_combo(ev_global=0.5, roi_global=0.5, payout_est=15.0, cfg=cfg)

    # raising EV and ROI thresholds filters out combos accordingly
    cfg["EV_MIN_GLOBAL"] = 0.6
    assert not allow_combo(ev_global=0.5, roi_global=0.5, payout_est=20.0, cfg=cfg)

    cfg["EV_MIN_GLOBAL"] = 0.0
    cfg["ROI_MIN_GLOBAL"] = 0.3
    assert not allow_combo(ev_global=0.5, roi_global=0.2, payout_est=20.0, cfg=cfg)
    assert allow_combo(ev_global=0.5, roi_global=0.3, payout_est=20.0, cfg=cfg)

    def test_combo_thresholds_lower_payout_cfg():
    cfg = {
        "EV_MIN_GLOBAL": 0.0,
        "ROI_MIN_GLOBAL": 0.0,
        "MIN_PAYOUT_COMBOS": 5.0,
    }

    assert allow_combo(ev_global=0.5, roi_global=0.5, payout_est=5.0, cfg=cfg)
