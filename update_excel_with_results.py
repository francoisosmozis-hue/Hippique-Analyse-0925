diff --git a//dev/null b/scripts/update_excel_with_results.py
index 0000000000000000000000000000000000000000..02f2baba404000d6f02bc572f8d465af666a77c1 100644
--- a//dev/null
+++ b/scripts/update_excel_with_results.py
@@ -0,0 +1,59 @@
+from __future__ import annotations
+
+import argparse
+import json
+from collections import defaultdict
+from pathlib import Path
+from typing import Dict
+
+
+def compute_monthly_clv(results_dir: Path) -> Dict[str, float]:
+    """Return the average CLV per month for JSON files in ``results_dir``.
+
+    Each JSON file is expected to contain a ``tickets`` list where individual
+    tickets may expose a ``clv`` value.  The month is inferred from the file
+    name and must start with ``YYYY-MM``.
+    """
+
+    monthly: defaultdict[str, list[float]] = defaultdict(list)
+    for path in results_dir.glob("*.json"):
+        try:
+            data = json.loads(path.read_text())
+        except Exception:  # pragma: no cover - invalid JSON ignored
+            continue
+        tickets = data.get("tickets", []) if isinstance(data, dict) else []
+        month = path.stem[:7]
+        for ticket in tickets:
+            clv = ticket.get("clv")
+            if isinstance(clv, (int, float)):
+                monthly[month].append(float(clv))
+    return {m: sum(v) / len(v) for m, v in monthly.items() if v}
+
+
+def main() -> None:
+    parser = argparse.ArgumentParser(description="Update Excel and archive CLV metrics")
+    parser.add_argument("--excel", type=Path, help="Path to Excel workbook", nargs="?")
+    parser.add_argument("--arrivees", type=Path, help="Path to results JSON", nargs="?")
+    parser.add_argument("--analyses-dir", type=Path, help="Directory with analyses", nargs="?")
+    parser.add_argument("--save", action="store_true", help="Write results to disk")
+    parser.add_argument("--results-dir", type=Path, help="Directory with results JSON including CLV")
+    parser.add_argument("--out", type=Path, help="Output JSON file for monthly CLV averages")
+    args = parser.parse_args()
+
+    results_dir = args.results_dir
+    if results_dir is None and args.arrivees is not None:
+        results_dir = args.arrivees.parent
+    if results_dir is None:
+        raise SystemExit("results directory not provided")
+
+    monthly = compute_monthly_clv(results_dir)
+
+    out_path = args.out or results_dir / "clv_monthly.json"
+    if args.save or args.out:
+        out_path.write_text(json.dumps(monthly, indent=2, sort_keys=True))
+    else:
+        print(json.dumps(monthly, indent=2, sort_keys=True))
+
+
+if __name__ == "__main__":
+    main()
