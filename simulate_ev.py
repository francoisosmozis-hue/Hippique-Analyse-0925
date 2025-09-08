diff --git a//dev/null b/scripts/simulate_ev.py
index 0000000000000000000000000000000000000000..4f41c5c25a3731006152d3d4dcaa1f0f051f885b 100644
--- a//dev/null
+++ b/scripts/simulate_ev.py
@@ -0,0 +1,34 @@
+#!/usr/bin/env python3
+import argparse
+import json
+import logging
+from pathlib import Path
+
+DATA_DIR = Path("data")
+CONFIG_DIR = Path("config")
+
+logging.basicConfig(level=logging.INFO, format="%(message)s")
+logger = logging.getLogger(__name__)
+
+def log(level: str, message: str, **kwargs) -> None:
+    record = {"level": level, "message": message}
+    if kwargs:
+        record.update(kwargs)
+    logger.log(logging.INFO if level == "INFO" else logging.ERROR, json.dumps(record))
+
+def main() -> None:
+    parser = argparse.ArgumentParser(description="Simulate expected value for combinations.")
+    parser.add_argument("--input", required=True, help="Input JSON under data/")
+    parser.add_argument("--calibration", default=CONFIG_DIR / "payout_calibration.yaml",
+                        help="Calibration file path.")
+    parser.add_argument("--out", required=True, help="Output JSON path under data/")
+    args = parser.parse_args()
+
+    out_path = Path(args.out)
+    out_path.parent.mkdir(parents=True, exist_ok=True)
+    result = {"ev": 0.0, "input": args.input}
+    out_path.write_text(json.dumps(result, indent=2))
+    log("INFO", "simulate_ev_complete", out=str(out_path))
+
+if __name__ == "__main__":
+    main()
