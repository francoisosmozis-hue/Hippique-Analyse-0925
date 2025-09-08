+import math
+import os
+import sys
+
+sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
+
+from ticket_metrics import ticket_metrics
+
+
+def test_ticket_metrics_clv_and_roi() -> None:
+    ticket = {"stake": 10, "payout": 0, "odds": 2.0, "closing_odds": 1.8}
+    metrics = ticket_metrics(ticket)
+    assert math.isclose(metrics["roi"], -1.0)
+    assert math.isclose(metrics["clv"], (1.8 - 2.0) / 2.0)
