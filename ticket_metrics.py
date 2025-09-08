+from __future__ import annotations
+
+from typing import Any, Dict
+
+
+def ticket_metrics(ticket: Dict[str, Any]) -> Dict[str, float]:
+    """Compute basic metrics for a settled ticket.
+
+    Parameters
+    ----------
+    ticket:
+        Mapping describing the ticket. Expected keys include ``stake`` and
+        ``payout`` to compute ROI and optionally ``closing_odds`` to compute
+        the closing line value (CLV).
+
+    Returns
+    -------
+    dict
+        Dictionary containing at least ``roi`` and ``clv`` when enough
+        information is provided. Missing information results in ``0.0`` values.
+    """
+
+    stake = float(ticket.get("stake", 0) or 0)
+    payout = float(ticket.get("payout", 0) or 0)
+    open_odds = ticket.get("odds")
+    closing_odds = ticket.get("closing_odds")
+
+    metrics: Dict[str, float] = {}
+    metrics["roi"] = (payout - stake) / stake if stake else 0.0
+    if open_odds is not None and closing_odds is not None and open_odds > 0:
+        metrics["clv"] = (closing_odds - open_odds) / open_odds
+    else:
+        metrics["clv"] = 0.0
+    return metrics
+
+
+__all__ = ["ticket_metrics"]
