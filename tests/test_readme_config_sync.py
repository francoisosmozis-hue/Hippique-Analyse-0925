import re
from pathlib import Path

import yaml


def test_readme_roi_sp_matches_config():
    cfg = yaml.safe_load(Path("config/gpi.yml").read_text(encoding="utf-8"))
    target = cfg["ev"]["min_roi_sp"]

    readme = Path("README.md")
    if not readme.exists():
        return

    text = readme.read_text(encoding="utf-8", errors="ignore")
    match = re.search(r"ROI[_\s]*SP[^0-9]*([0-9]{1,2})\s*%", text, flags=re.IGNORECASE)
    assert match, "README must mention ROI_SP threshold"
    assert float(match.group(1)) / 100.0 >= target
