diff --git a//dev/null b/scripts/p_finale_export.py
index 0000000000000000000000000000000000000000..a295f8a75bab90d325b5709c4c5b6ac6bb2ad27a 100644
--- a//dev/null
+++ b/scripts/p_finale_export.py
@@ -0,0 +1,46 @@
+#!/usr/bin/env python3
+import argparse
+import csv
+import json
+import logging
+from pathlib import Path
+
+DATA_DIR = Path("data")
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
+    parser = argparse.ArgumentParser(description="Export final analysis to JSON and CSV.")
+    parser.add_argument("--analysis", required=True, help="Analysis JSON input.")
+    parser.add_argument("--out-json", required=True, help="Output JSON path under data/")
+    parser.add_argument("--out-csv", required=True, help="Output CSV path under data/")
+    args = parser.parse_args()
+
+    analysis_path = Path(args.analysis)
+    data = {}
+    if analysis_path.exists():
+        data = json.loads(analysis_path.read_text())
+
+    json_path = Path(args.out_json)
+    csv_path = Path(args.out_csv)
+    json_path.parent.mkdir(parents=True, exist_ok=True)
+    csv_path.parent.mkdir(parents=True, exist_ok=True)
+
+    json_path.write_text(json.dumps(data, indent=2))
+    with csv_path.open("w", newline="") as csv_file:
+        writer = csv.writer(csv_file)
+        writer.writerow(["key", "value"])
+        for k, v in data.items():
+            writer.writerow([k, v])
+
+    log("INFO", "export_complete", json=str(json_path), csv=str(csv_path))
+
+if __name__ == "__main__":
+    main()
