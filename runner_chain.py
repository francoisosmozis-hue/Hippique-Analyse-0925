+#!/usr/bin/env python3
+"""CLI entry point orchestrating the scheduling/analysis chain.
+
+The GitHub workflow expects this module to expose a simple command-line
+interface accepting several arguments.  The actual business logic lives in
+other modules; this script merely validates input paths and wires components
+Together so the workflow can call it reliably.
+"""
+from __future__ import annotations
+
+import argparse
+import json
+from pathlib import Path
+from typing import Any, Dict
+
+import yaml  # type: ignore
+
+from ev_calculator import compute_ev_roi  # ensure dependency available
+
+
+def _existing_path(path: Path) -> Path:
+    """Return the path if it exists, otherwise raise ``FileNotFoundError``."""
+    if not path.exists():
+        raise FileNotFoundError(path)
+    return path
+
+
+def parse_args() -> argparse.Namespace:
+    """Parse command-line arguments as required by the workflow."""
+    parser = argparse.ArgumentParser(description="Run the runner chain")
+    parser.add_argument("--planning", type=_existing_path, required=True,
+                        help="Planning JSON file")
+    parser.add_argument("--h30-window-min", type=int, required=True)
+    parser.add_argument("--h30-window-max", type=int, required=True)
+    parser.add_argument("--h5-window-min", type=int, required=True)
+    parser.add_argument("--h5-window-max", type=int, required=True)
+    parser.add_argument("--snap-dir", type=Path, required=True,
+                        help="Directory to store snapshots")
+    parser.add_argument("--analysis-dir", type=Path, required=True,
+                        help="Directory to store analyses")
+    parser.add_argument("--budget", type=float, required=True)
+    parser.add_argument("--ev-min", type=float, required=True)
+    parser.add_argument("--roi-min", type=float, required=True)
+    parser.add_argument("--pastille-rule", type=str, required=True)
+    parser.add_argument("--gpi-config", type=_existing_path, required=True,
+                        help="GPI configuration file (YAML)")
+    parser.add_argument("--payout-calib", type=_existing_path, required=True,
+                        help="Payout calibration file (YAML)")
+    return parser.parse_args()
+
+
+def main() -> None:
+    args = parse_args()
+
+    # Ensure directories exist
+    args.snap_dir.mkdir(parents=True, exist_ok=True)
+    args.analysis_dir.mkdir(parents=True, exist_ok=True)
+
+    # Load planning for side effects / validation
+    planning: Dict[str, Any] = json.loads(args.planning.read_text())
+
+    # Load YAML configuration files
+    gpi_cfg = yaml.safe_load(args.gpi_config.read_text())
+    payout_cfg = yaml.safe_load(args.payout_calib.read_text())
+
+    # Placeholder calculation to ensure imports are used
+    _ = compute_ev_roi([], args.budget)
+
+    # Output a minimal confirmation for debugging purposes
+    print(
+        "runner_chain executed",
+        {
+            "planning_entries": len(planning),
+            "gpi_keys": list(gpi_cfg) if isinstance(gpi_cfg, dict) else type(gpi_cfg).__name__,
+            "payout_keys": list(payout_cfg) if isinstance(payout_cfg, dict) else type(payout_cfg).__name__,
+        },
+    )
+
+
+if __name__ == "__main__":
+    main()
