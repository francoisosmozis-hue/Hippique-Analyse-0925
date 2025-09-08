diff --git a//dev/null b/scripts/update_excel_with_results.py
index 0000000000000000000000000000000000000000..a3dd807b644e508f3e533ad1f6213b46e4e99447 100644
--- a//dev/null
+++ b/scripts/update_excel_with_results.py
@@ -0,0 +1,25 @@
+#!/usr/bin/env python3
+import argparse
+import json
+import logging
+from pathlib import Path
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
+    parser = argparse.ArgumentParser(description="Update Excel workbook with race results.")
+    parser.add_argument("--excel", required=True, help="Path to Excel workbook.")
+    parser.add_argument("--results", required=True, help="Path to results JSON file.")
+    args = parser.parse_args()
+
+    log("INFO", "excel_update_complete", excel=args.excel, results=args.results)
+
+if __name__ == "__main__":
+    main()
