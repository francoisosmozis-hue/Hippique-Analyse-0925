import importlib
import os
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

stub_fetch = types.ModuleType("scripts.online_fetch_zeturf")
stub_fetch.normalize_snapshot = lambda payload: payload
sys.modules.setdefault("scripts.online_fetch_zeturf", stub_fetch)

acde = importlib.import_module("analyse_courses_du_jour_enrichie")


class DummyResp:
    def __init__(self, text: str):
        self.text = text
        self.status_code = 200

    def raise_for_status(self) -> None:
        return None


def test_check_enrich_outputs_no_bet_payload(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(acde.time, "sleep", lambda delay: None)

    result = acde._check_enrich_outputs(tmp_path)

    assert result == {
        "status": "no-bet",
        "decision": "ABSTENTION",
        "reason": "data-missing",
        "details": {"missing": ["snap_H-5_je.csv", "chronos.csv"]},
    }


def test_check_enrich_outputs_prefers_latest_snapshot(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    older = tmp_path / "20240101T120000_R1C1_H-5.json"
    older.write_text("{}", encoding="utf-8")
    newer = tmp_path / "20240101T120500_R1C1_H-5.json"
    newer.write_text("{}", encoding="utf-8")

    os.utime(older, (1000, 1000))
    os.utime(newer, (2000, 2000))

    monkeypatch.setattr(acde.time, "sleep", lambda delay: None)

    result = acde._check_enrich_outputs(tmp_path)

    assert result == {
        "status": "no-bet",
        "decision": "ABSTENTION",
        "reason": "data-missing",
        "details": {
            "missing": [
                "20240101T120500_R1C1_H-5_je.csv",
                "chronos.csv",
            ]
        },
    }
def test_process_reunion_continues_after_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    html = """
    <html>
      <body>
        <a href="/fr/course/111">C1</a>
        <a href="/fr/course/222">C2</a>
      </body>
    </html>
    """

    monkeypatch.setattr(acde.requests, "get", lambda *a, **k: DummyResp(html))

    def fake_snapshot(cid: str, ph: str, rc_dir: Path, *, course_url: str | None = None) -> Path:
        rc_dir.mkdir(parents=True, exist_ok=True)
        stem = f"snap_{cid}_H-5"
        path = rc_dir / f"{stem}.json"
        path.write_text("{}", encoding="utf-8")
        return path
    monkeypatch.setattr(acde, "write_snapshot_from_geny", fake_snapshot)

    def fake_enrich(rc_dir: Path, **kw) -> None:
        snap = next(rc_dir.glob("*_H-5.json"))
        if rc_dir.name.endswith("C1"):
            return
        (rc_dir / f"{snap.stem}_je.csv").write_text(
            "num,nom,j_rate,e_rate\n1,A,0.1,0.2\n", encoding="utf-8"
        )
        (rc_dir / "chronos.csv").write_text("num,chrono\n1,1.0\n", encoding="utf-8")

    monkeypatch.setattr(acde, "enrich_h5", fake_enrich)
    monkeypatch.setattr(acde.time, "sleep", lambda delay: None)
    monkeypatch.setattr(acde.subprocess, "run", lambda *a, **k: None)

    pipeline_calls: list[Path] = []
    monkeypatch.setattr(
        acde,
        "build_p_finale",
        lambda rc_dir, **kw: pipeline_calls.append(rc_dir),
    )
    monkeypatch.setattr(
        acde,
        "run_pipeline",
        lambda rc_dir, **kw: pipeline_calls.append(rc_dir),
    )
    monkeypatch.setattr(
        acde,
        "build_prompt_from_meta",
        lambda rc_dir, **kw: pipeline_calls.append(rc_dir),
    )
    monkeypatch.setattr(
        acde,
        "export_per_horse_csv",
        lambda rc_dir: (pipeline_calls.append(rc_dir) or (rc_dir / "per_horse_report.csv")),
    )

    acde._process_reunion(
        "https://www.zeturf.fr/fr/reunion/2024-09-25/R1-test",
        "H5",
        tmp_path,
        source="geny",
        budget=100.0,
        kelly=1.0,
        gcs_prefix=None,
    )

    assert all(rc.name.endswith("C2") for rc in pipeline_calls)
    decision_path = tmp_path / "R1C1" / "decision.json"
    assert decision_path.exists()


def test_mark_course_unplayable_writes_marker(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc_dir = tmp_path / "R1C1"
    rc_dir.mkdir()

    missing = ["chronos.csv", "R1C1_H-5_je.csv"]
    info = acde._mark_course_unplayable(rc_dir, missing)

    marker = rc_dir / "UNPLAYABLE.txt"
    assert marker.exists()
    content = marker.read_text(encoding="utf-8")
    for item in missing:
        assert item in content

    assert info["marker_path"].endswith("UNPLAYABLE.txt")
    assert info["marker_written"] is True
    assert "chronos.csv" in info["marker_message"]

    captured = capsys.readouterr()
    assert "Course non jouable" in captured.err
