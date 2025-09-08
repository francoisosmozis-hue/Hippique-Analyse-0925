+import json
+import os
+import sys
+from pathlib import Path
+
+import pytest
+
+sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
+
+from scripts.update_excel_with_results import compute_monthly_clv
+
+
+def test_compute_monthly_clv(tmp_path: Path) -> None:
+    data_may1 = {"tickets": [{"clv": 0.1}, {"clv": -0.05}]}
+    data_may20 = {"tickets": [{"clv": 0.2}]}
+    data_june = {"tickets": [{"clv": 0.3}]}
+    (tmp_path / "2024-05-01_results.json").write_text(json.dumps(data_may1))
+    (tmp_path / "2024-05-20_results.json").write_text(json.dumps(data_may20))
+    (tmp_path / "2024-06-02_results.json").write_text(json.dumps(data_june))
+
+    result = compute_monthly_clv(tmp_path)
+    assert result["2024-05"] == pytest.approx((0.1 - 0.05 + 0.2) / 3)
+    assert result["2024-06"] == pytest.approx(0.3)
