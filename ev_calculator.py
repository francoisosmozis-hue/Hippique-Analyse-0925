from typing import List, Dict, Any, Optional
def compute_ev_roi(tickets: List[Dict[str, Any]], bankroll: float = 100.0,
                   kelly_cap: Optional[float] = None, **kwargs) -> Dict[str, float]:
    total_stake = ev_cash = 0.0
    for t in tickets or []:
        stake = float(t.get("stake", 0.0) or 0.0)
        ev_cash += stake * float(t.get("ev", 0.0) or 0.0)
        total_stake += stake
    roi = (ev_cash / total_stake) if total_stake > 0 else 0.0
    vol = 0.5
    return {"ev": ev_cash, "roi": roi, "vol": vol, "ror": max(0.0, roi*0.01), "sharpe": (roi/vol if vol else 0.0)}
