import os
import sys
import json
from pathlib import Path

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import analyse_courses_du_jour_enrichie as acde


class DummyResp:
    def __init__(self, text: str):
        self.text = text
        self.status_code = 200

    def raise_for_status(self) -> None:
        return None


@pytest.mark.parametrize("phase, expect_pipeline", [("H30", False), ("H5", True)])
def test_single_reunion(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, phase: str, expect_pipeline: bool) -> None:
    html = """
    <html>
      <body>
        <a href="/fr/course/123">C1</a>
        <a href="/fr/course/456">C2</a>
      </body>
    </html>
    """

    def fake_get(url: str, headers: dict | None = None, timeout: int = 10) -> DummyResp:
        return DummyResp(html)

    monkeypatch.setattr(acde.requests, "get", fake_get)

    snaps: list[tuple[str, str, Path]] = []

    def fake_snapshot(cid: str, ph: str, rc_dir: Path) -> Path:
        suffix = "H-5" if ph.upper() == "H5" else "H-30"
        dest = rc_dir / f"snap_{cid}_{suffix}.json"
        dest.write_text("{}", encoding="utf-8")
        snaps.append((cid, ph, rc_dir))
        return dest

    monkeypatch.setattr(acde, "write_snapshot_from_geny", fake_snapshot)

    enrich_calls: list[Path] = []

    def fake_enrich(rc_dir: Path, **kw) -> None:
        snap = next(rc_dir.glob("*_H-5.json"))
        stem = snap.stem
        (rc_dir / f"{stem}_je.csv").write_text(
            "num,nom,j_rate,e_rate\n1,A,0.1,0.2\n", encoding="utf-8"
        )
        (rc_dir / "chronos.csv").write_text(
            "num,chrono\n1,1.0\n", encoding="utf-8"
        )
        enrich_calls.append(rc_dir)

    monkeypatch.setattr(acde, "enrich_h5", fake_enrich)

    pipeline_calls: list[Path] = []
    monkeypatch.setattr(acde, "build_p_finale", lambda rc_dir, **kw: pipeline_calls.append(rc_dir))
    monkeypatch.setattr(acde, "run_pipeline", lambda rc_dir, **kw: pipeline_calls.append(rc_dir))
    monkeypatch.setattr(acde, "build_prompt_from_meta", lambda rc_dir, **kw: pipeline_calls.append(rc_dir))

    csv_calls: list[Path] = []
    monkeypatch.setattr(
        acde,
        "export_per_horse_csv",
        lambda rc_dir: (csv_calls.append(rc_dir) or (rc_dir / "per_horse_report.csv")),
    )
    
    argv = [
        "analyse_courses_du_jour_enrichie.py",
        "--reunion-url",
        "https://www.zeturf.fr/fr/reunion/2024-09-25/R1-test",
        "--phase",
        phase,
        "--data-dir",
        str(tmp_path),
    ]
    monkeypatch.setattr(sys, "argv", argv)
    acde.main()

    assert [(c, p) for c, p, _ in snaps] == [("123", phase), ("456", phase)]
    if expect_pipeline:
         assert len(enrich_calls) == 2
        assert len(pipeline_calls) == 6  # 3 funcs * 2 courses
        assert len(csv_calls) == 2
    else:
        assert not enrich_calls
        assert not pipeline_calls
        assert not csv_calls


def test_batch_mode(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    payload = {"reunions": [{"url_zeturf": "http://r1"}]}
    fp = tmp_path / "reuns.json"
    fp.write_text(json.dumps(payload), encoding="utf-8")

    calls: list[list[str]] = []

    def fake_run(cmd, check):  # pragma: no cover - simple recorder
        calls.append(cmd)

    monkeypatch.setattr(acde.subprocess, "run", fake_run)

    monkeypatch.setattr(
        sys,
        "argv",
        ["analyse_courses_du_jour_enrichie.py", "--reunions-file", str(fp)],
    )
    acde.main()

    script_path = str(Path(acde.__file__).resolve())
    assert calls == [
        [
            sys.executable,
            script_path,
            "--reunion-url",
            "http://r1",
            "--phase",
            "H30",
            "--data-dir",
            "data",
            "--budget",
            "100.0",
            "--kelly",
            "1.0",
        ],
        [
            sys.executable,
            script_path,
            "--reunion-url",
            "http://r1",
            "--phase",
            "H5",
            "--data-dir",
            "data",
            "--budget",
            "100.0",
            "--kelly",
            "1.0",
        ],
    ]


def test_missing_enrich_outputs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    html = """
    <html><body><a href="/fr/course/123">C1</a></body></html>
    """

    def fake_get(url: str, headers: dict | None = None, timeout: int = 10) -> DummyResp:
        return DummyResp(html)

    monkeypatch.setattr(acde.requests, "get", fake_get)

    def fake_snapshot(cid: str, ph: str, rc_dir: Path) -> Path:
        dest = rc_dir / "snap_H-5.json"
        dest.write_text("{}", encoding="utf-8")
        return dest

    monkeypatch.setattr(acde, "write_snapshot_from_geny", fake_snapshot)

    monkeypatch.setattr(acde, "enrich_h5", lambda rc_dir, **kw: None)
    monkeypatch.setattr(acde, "build_p_finale", lambda *a, **k: None)
    monkeypatch.setattr(acde, "run_pipeline", lambda *a, **k: None)
    monkeypatch.setattr(acde, "build_prompt_from_meta", lambda *a, **k: None)
    monkeypatch.setattr(acde, "export_per_horse_csv", lambda *a, **k: None)

    argv = [
        "analyse_courses_du_jour_enrichie.py",
        "--reunion-url",
        "https://www.zeturf.fr/fr/reunion/2024-09-25/R1-test",
        "--phase",
        "H5",
        "--data-dir",
        str(tmp_path),
    ]
    monkeypatch.setattr(sys, "argv", argv)
    with pytest.raises(SystemExit) as exc:
        acde.main()
    assert exc.value.code == 1


def test_export_per_horse_csv(tmp_path: Path) -> None:
    snap = tmp_path / "snap_H-5.json"
    snap.write_text("{}", encoding="utf-8")
    (tmp_path / f"{snap.stem}_je.csv").write_text(
        "num,nom,j_rate,e_rate\n1,A,0.1,0.2\n", encoding="utf-8"
    )
    (tmp_path / "chronos.csv").write_text("num,chrono\n1,1.0\n", encoding="utf-8")
    data = {"p_true": {"1": 0.5}, "meta": {"id2name": {"1": "A"}}}
    (tmp_path / "p_finale.json").write_text(json.dumps(data), encoding="utf-8")
    out = acde.export_per_horse_csv(tmp_path)
    assert out.exists()
    lines = out.read_text(encoding="utf-8").strip().splitlines()
    assert lines[0] == "num,nom,p_finale,j_rate,e_rate,chrono_ok"
    assert lines[1].startswith("1,A,0.5,0.1,0.2,True")
