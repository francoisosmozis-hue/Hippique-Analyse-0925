+"""Simple simulation wrapper applying calibrated probabilities.
+
+The module reads calibration data produced by ``calibration/calibrate_simulator.py``
+from ``calibration/probabilities.yaml``.  For each call, the calibration file
+is reloaded if modified so that simulations use the latest probabilities.
+"""
+from __future__ import annotations
+
+from pathlib import Path
+from typing import Iterable, List, Dict
+
+import yaml
+
+CALIBRATION_PATH = Path("calibration/probabilities.yaml")
+
+_calibration_cache: Dict[str, float] = {}
+_calibration_mtime: float = 0.0
+
+
+def _load_calibration() -> None:
+    """Reload calibration file if it has changed on disk."""
+    global _calibration_cache, _calibration_mtime
+    try:
+        mtime = CALIBRATION_PATH.stat().st_mtime
+    except FileNotFoundError:
+        _calibration_cache = {}
+        _calibration_mtime = 0.0
+        return
+    if mtime <= _calibration_mtime:
+        return
+    with CALIBRATION_PATH.open("r", encoding="utf-8") as fh:
+        data = yaml.safe_load(fh) or {}
+    _calibration_cache = {k: float(v.get("p", 0.0)) for k, v in data.items()}
+    _calibration_mtime = mtime
+
+
+def simulate_wrapper(legs: Iterable[object]) -> float:
+    """Return calibrated win probability for a combination of ``legs``.
+
+    Parameters
+    ----------
+    legs:
+        Iterable describing the components of the combiné.
+
+    Returns
+    -------
+    float
+        Calibrated probability if available, otherwise a naive estimate
+        ``0.5 ** len(legs)``.
+    """
+    _load_calibration()
+    key = "|".join(map(str, legs))
+    if key in _calibration_cache:
+        return _calibration_cache[key]
+    # Fallback: assume independent 50% events
+    legs_list: List[object] = list(legs)
+    return 0.5 ** len(legs_list)
