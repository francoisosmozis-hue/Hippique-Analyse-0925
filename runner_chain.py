diff --git a//dev/null b/scripts/runner_chain.py
index 0000000000000000000000000000000000000000..6eefbd650a2a53b212a082afac660adff495aa84 100644
--- a//dev/null
+++ b/scripts/runner_chain.py
@@ -0,0 +1,38 @@
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
+    parser = argparse.ArgumentParser(description="Run pipeline phases for a race.")
+    parser.add_argument("--reunion", required=True, help="Reunion identifier (e.g., R1).")
+    parser.add_argument("--course", required=True, help="Course identifier (e.g., C3).")
+    parser.add_argument("--phase", choices=["H30", "H5", "RESULT"], required=True,
+                        help="Pipeline phase to execute.")
+    parser.add_argument("--ttl-hours", type=int, default=6, help="TTL for snapshots.")
+    parser.add_argument("--budget", type=float, help="Budget per course in euros.")
+    parser.add_argument("--calibration", default=CONFIG_DIR / "payout_calibration.yaml",
+                        help="Calibration file for payouts.")
+    parser.add_argument("--excel", default=Path("excel") / "modele_suivi_courses_hippiques.xlsx",
+                        help="Excel file for results update.")
+    args = parser.parse_args()
+
+    log("INFO", "runner_chain_start", **vars(args))
+    # Placeholder for the actual pipeline logic
+    log("INFO", "runner_chain_complete", phase=args.phase)
+
+if __name__ == "__main__":
+    main()
