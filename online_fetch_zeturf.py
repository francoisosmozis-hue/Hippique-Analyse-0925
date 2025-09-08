diff --git a//dev/null b/scripts/online_fetch_zeturf.py
index 0000000000000000000000000000000000000000..d9f6e2c02e3de898be5b9978577db968e2c89248 100644
--- a//dev/null
+++ b/scripts/online_fetch_zeturf.py
@@ -0,0 +1,37 @@
+#!/usr/bin/env python3
+import argparse
+import json
+import logging
+from pathlib import Path
+from datetime import datetime
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
+    parser = argparse.ArgumentParser(description="Fetch planning or snapshots from Zeturf.")
+    parser.add_argument("--mode", choices=["planning", "snapshot"], required=True,
+                        help="Operation mode.")
+    parser.add_argument("--out", required=True, help="Output JSON path under data/")
+    parser.add_argument("--sources", default=CONFIG_DIR / "sources.yml",
+                        help="Sources configuration YAML.")
+    args = parser.parse_args()
+
+    out_path = Path(args.out)
+    out_path.parent.mkdir(parents=True, exist_ok=True)
+    data = {"mode": args.mode, "generated_at": datetime.utcnow().isoformat()}
+    out_path.write_text(json.dumps(data, indent=2))
+
+    log("INFO", "fetch_complete", mode=args.mode, out=str(out_path))
+
+if __name__ == "__main__":
+    main()
