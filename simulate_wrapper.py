diff --git a//dev/null b/scripts/simulate_wrapper.py
index 0000000000000000000000000000000000000000..a7c71084b5f9acf8ab60e2c9f1bc29cee858a209 100644
--- a//dev/null
+++ b/scripts/simulate_wrapper.py
@@ -0,0 +1,33 @@
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
+    parser = argparse.ArgumentParser(description="Wrapper around EV simulation pipeline.")
+    parser.add_argument("--snapshot", required=True, help="Snapshot JSON path under data/")
+    parser.add_argument("--calibration", default=CONFIG_DIR / "payout_calibration.yaml",
+                        help="Calibration file.")
+    parser.add_argument("--out", required=True, help="Output JSON path under data/")
+    args = parser.parse_args()
+
+    out_path = Path(args.out)
+    out_path.parent.mkdir(parents=True, exist_ok=True)
+    out_path.write_text(json.dumps({"snapshot": args.snapshot, "ev": 0.0}, indent=2))
+    log("INFO", "simulate_wrapper_complete", out=str(out_path))
+
+if __name__ == "__main__":
+    main()
