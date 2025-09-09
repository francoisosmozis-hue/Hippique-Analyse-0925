+#!/usr/bin/env python3
+"""Fetch today's race meetings from Zeturf and save to JSON."""
+
+from __future__ import annotations
+
+import argparse
+import datetime as dt
+import json
+import os
+from typing import Any, Dict, List
+
+import requests
+import yaml
+
+
+def fetch_meetings(url: str) -> Any:
+    """Retrieve meeting data from the given URL."""
+    resp = requests.get(url, timeout=10)
+    resp.raise_for_status()
+    return resp.json()
+
+
+def filter_today(meetings: Any) -> List[Dict[str, Any]]:
+    """Filter meetings that occur today based on a ``date`` field."""
+    today = dt.date.today().isoformat()
+    items = meetings
+    if isinstance(meetings, dict):
+        items = meetings.get("meetings") or meetings.get("data") or []
+    return [m for m in items if m.get("date") == today]
+
+
+def main() -> None:
+    parser = argparse.ArgumentParser(description="Fetch today's meetings from Zeturf")
+    parser.add_argument("--out", required=True, help="Output JSON file")
+    parser.add_argument("--sources", default="config/sources.yml", help="Path to sources YAML config")
+    parser.add_argument("--mode", default="planning", help="Operational mode (unused)")
+    args = parser.parse_args()
+
+    with open(args.sources, "r", encoding="utf-8") as fh:
+        config = yaml.safe_load(fh) or {}
+
+    url = config.get("zeturf", {}).get("url")
+    if not url:
+        raise ValueError("No Zeturf source URL configured in sources.yml")
+
+    meetings = fetch_meetings(url)
+    today_meetings = filter_today(meetings)
+
+    os.makedirs(os.path.dirname(args.out), exist_ok=True)
+    with open(args.out, "w", encoding="utf-8") as fh:
+        json.dump(today_meetings, fh, ensure_ascii=False, indent=2)
+
+
+if __name__ == "__main__":
+    main()
