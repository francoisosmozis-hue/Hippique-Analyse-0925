+#!/usr/bin/env python3
+"""Fetch Zeturf odds and meeting schedule."""
+
+from __future__ import annotations
+
+import argparse
+import datetime as dt
+import json
+import os
+import sys
+from typing import Any
+
+import requests
+
+API_URL = "https://www.zeturf.fr/api/calendar"
+
+
+def fetch_planning(date: str) -> Any:
+    """Retrieve Zeturf planning for the given date."""
+    url = f"{API_URL}?date={date}"
+    resp = requests.get(url, timeout=10)
+    resp.raise_for_status()
+    return resp.json()
+
+
+def main() -> None:
+    parser = argparse.ArgumentParser(description="Fetch Zeturf data")
+    parser.add_argument("--mode", default="planning", choices=["planning"], help="Only planning mode is supported")
+    parser.add_argument("--out", required=True, help="Output JSON path")
+    parser.add_argument("--sources", help="Unused placeholder for compatibility", default=None)
+    parser.add_argument("--date", default=dt.date.today().isoformat(), help="Date YYYY-MM-DD")
+    args = parser.parse_args()
+
+    try:
+        data = fetch_planning(args.date)
+    except Exception as exc:  # pragma: no cover - network error handling
+        sys.stderr.write(f"Error fetching data: {exc}\n")
+        raise
+
+    os.makedirs(os.path.dirname(args.out), exist_ok=True)
+    with open(args.out, "w", encoding="utf-8") as f:
+        json.dump(data, f, ensure_ascii=False, indent=2)
+
+    print(f"Saved planning to {args.out}")
+
+
+if __name__ == "__main__":
+    main()

