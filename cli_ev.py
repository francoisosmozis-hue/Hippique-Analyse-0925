+#!/usr/bin/env python3
+from __future__ import annotations
+
+import argparse
+import json
+from pathlib import Path
+from typing import Any, List
+
+import yaml
+
+from ev_calculator import compute_ev_roi
+
+
+def load_tickets(path: Path) -> List[dict[str, Any]]:
+    """Load ticket definitions from a JSON or YAML file."""
+    with path.open() as handle:
+        if path.suffix.lower() in {".yaml", ".yml"}:
+            data = yaml.safe_load(handle)
+        else:
+            data = json.load(handle)
+    if isinstance(data, dict) and "tickets" in data:
+        tickets = data["tickets"]
+    elif isinstance(data, list):
+        tickets = data
+    else:
+        raise ValueError("Ticket file must contain a list or a 'tickets' key")
+    if not isinstance(tickets, list):
+        raise ValueError("Tickets must be a list of dictionaries")
+    return tickets
+
+
+def main() -> None:
+    parser = argparse.ArgumentParser(description="Compute EV/ROI for betting tickets")
+    parser.add_argument("--tickets", required=True, help="Path to tickets file (JSON or YAML)")
+    parser.add_argument("--budget", type=float, required=True, help="Bankroll budget to use")
+    parser.add_argument(
+        "--ev-threshold",
+        type=float,
+        default=0.0,
+        help="Minimum EV to mark as green",
+    )
+    parser.add_argument(
+        "--roi-threshold",
+        type=float,
+        default=0.0,
+        help="Minimum ROI to mark as green",
+    )
+    args = parser.parse_args()
+
+    tickets = load_tickets(Path(args.tickets))
+    result = compute_ev_roi(tickets, budget=args.budget)
+
+    ev = result["ev"]
+    roi = result["roi"]
+    risk = result["risk_of_ruin"]
+    is_green = ev >= args.ev_threshold and roi >= args.roi_threshold
+    pastille = "\U0001F7E2" if is_green else "\U0001F534"  # green or red circle
+
+    print(f"EV: {ev:.2f}")
+    print(f"ROI: {roi:.2%}")
+    print(f"Risk of ruin: {risk:.2%}")
+    print(f"Pastille: {pastille}")
+
+
+if __name__ == "__main__":
+    main()
