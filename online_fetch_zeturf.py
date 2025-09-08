+#!/usr/bin/env python3
+"""Fetch Zeturf data and store it as JSON.
+
+This script currently implements the *planning* mode which retrieves the
+race planning from Zeturf and writes it to the destination file.  The URL of
+Zeturf's API is provided through a YAML configuration file.  The configuration
+is expected to contain a ``zeturf`` section with a ``planning_url`` field
+which may contain a ``{date}`` placeholder.
+"""
+
+from __future__ import annotations
+
+import argparse
+import json
+import logging
+import sys
+from pathlib import Path
+from typing import Any, Dict
+
+import requests
+import yaml
+
+
+def _fetch_json(url: str) -> Dict[str, Any]:
+    """Return JSON content fetched from *url*.
+
+    Raises:
+        requests.RequestException: if the HTTP request fails.
+        ValueError: if the response body is not valid JSON.
+    """
+
+    response = requests.get(url, timeout=15)
+    response.raise_for_status()
+    return response.json()
+
+
+def fetch_planning(cfg: Dict[str, Any], out_path: Path) -> None:
+    """Fetch race planning and write it to *out_path*.
+
+    The configuration must contain ``zeturf.planning_url`` which can include a
+    ``{date}`` placeholder.  The placeholder is filled with the stem of
+    ``out_path`` (typically ``YYYY-MM-DD``).
+    """
+
+    url_template = cfg["zeturf"]["planning_url"]
+    date_str = out_path.stem
+    url = url_template.format(date=date_str)
+
+    logging.info("Fetching planning from %s", url)
+    data = _fetch_json(url)
+
+    out_path.parent.mkdir(parents=True, exist_ok=True)
+    with out_path.open("w", encoding="utf-8") as fh:
+        json.dump(data, fh, ensure_ascii=False, indent=2)
+    logging.info("Saved planning to %s", out_path)
+
+
+def main() -> int:
+    parser = argparse.ArgumentParser(description="Fetch Zeturf data")
+    parser.add_argument("--mode", choices=["planning"], default="planning")
+    parser.add_argument("--out", type=Path, required=True,
+                        help="Output JSON file path")
+    parser.add_argument("--sources", type=Path, required=True,
+                        help="YAML configuration file")
+    args = parser.parse_args()
+
+    logging.basicConfig(level=logging.INFO,
+                        format="%(levelname)s:%(message)s")
+
+    try:
+        with args.sources.open("r", encoding="utf-8") as fh:
+            cfg = yaml.safe_load(fh) or {}
+
+        if args.mode == "planning":
+            fetch_planning(cfg, args.out)
+        else:
+            raise ValueError(f"Unsupported mode: {args.mode}")
+
+        return 0
+    except Exception as exc:  # noqa: BLE001 - log and return non-zero
+        logging.error("%s", exc)
+        return 1
+
+
+if __name__ == "__main__":  # pragma: no cover - CLI entry point
+    sys.exit(main())
