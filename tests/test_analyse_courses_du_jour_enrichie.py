import json
import os
import sys
import types
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

stub_fetch = types.ModuleType("scripts.online_fetch_zeturf")
stub_fetch.normalize_snapshot = lambda payload: payload
sys.modules.setdefault("scripts.online_fetch_zeturf", stub_fetch)

import analyse_courses_du_jour_enrichie as acde


class DummyResp:
    def __init__(self, text: str):
        self.text = text
        self.status_code = 200

    def raise_for_status(self) -> None:
        return None


def test_process_reunion_executes_pipeline(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    html = """
    <html>
      <body>
        <h1>Réunion R2</h1>
        <a href="/fr/course/123">Course C1</a>
        <a href="/fr/course/456">Course C2</a>
      </body>
    </html>
    """

    def fake_get(url: str, headers: dict | None = None, timeout: int = 10) -> DummyResp:
        return DummyResp(html)

    monkeypatch.setattr(acde.requests, "get", fake_get)

    snapshot_calls: list[dict[str, Any]] = []

    def fake_snapshot(
        cid: str, ph: str, rc_dir: Path, *, course_url: str | None = None
    ) -> Path:
        rc_dir.mkdir(parents=True, exist_ok=True)
        snapshot_calls.append(
            {
                "course_id": cid,
                "phase": ph,
                "rc_dir": rc_dir,
                "course_url": course_url,
            }
        )
        dest = rc_dir / "snapshot.json"
        dest.write_text("{}", encoding="utf-8")
        return dest

    monkeypatch.setattr(acde, "write_snapshot_from_geny", fake_snapshot)

    chain_calls: list[tuple[Path, float, float]] = []

    def fake_execute(rc_dir: Path, *, budget: float, kelly: float):
        chain_calls.append((rc_dir, budget, kelly))
        return True, None

    monkeypatch.setattr(acde, "_execute_h5_chain", fake_execute)
    monkeypatch.setattr(
        acde,
        "export_per_horse_csv",
        lambda rc_dir: rc_dir / "per_horse_report.csv",
    )

    acde._process_reunion(
        "https://www.zeturf.fr/fr/reunion/2024-09-25/R2-paris",
        "H5",
        tmp_path,
        budget=42.0,
        kelly=0.25,
        gcs_prefix=None,
    )

    assert [call["course_id"] for call in snapshot_calls] == ["123", "456"]
    assert [call["phase"] for call in snapshot_calls] == ["H5", "H5"]
    assert [call["course_url"] for call in snapshot_calls] == [
        "https://www.zeturf.fr/fr/course/123",
        "https://www.zeturf.fr/fr/course/456",
    ]
    assert [call["rc_dir"].relative_to(tmp_path) for call in snapshot_calls] == [
        Path("R2C1"),
        Path("R2C2"),
    ]
    assert [entry[0].relative_to(tmp_path) for entry in chain_calls] == [
        Path("R2C1"),
        Path("R2C2"),
    ]
    assert all(budget == 42.0 and kelly == 0.25 for _, budget, kelly in chain_calls)


@pytest.mark.parametrize("phase, expect_pipeline", [("H30", False), ("H5", True)])
def test_single_reunion(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, phase: str, expect_pipeline: bool
) -> None:
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

    snaps: list[tuple[str, str, Path, str | None]] = []

    def fake_snapshot(
        cid: str, ph: str, rc_dir: Path, *, course_url: str | None = None
    ) -> Path:
        suffix = "H-5" if ph.upper() == "H5" else "H-30"
        dest = rc_dir / f"snap_{cid}_{suffix}.json"
        dest.write_text("{}", encoding="utf-8")
        snaps.append((cid, ph, rc_dir, course_url))
        return dest

    monkeypatch.setattr(acde, "write_snapshot_from_geny", fake_snapshot)

    def fake_guard(rc_dir: Path, *, budget: float) -> tuple[bool, dict[str, Any], None]:
        return True, {}, None

    monkeypatch.setattr(acde, "_run_h5_guard_phase", fake_guard)

    enrich_calls: list[Path] = []

    def fake_enrich(rc_dir: Path, **kw) -> None:
        snap = next(rc_dir.glob("*_H-5.json"))
        stem = snap.stem
        (rc_dir / f"{stem}_je.csv").write_text(
            "num,nom,j_rate,e_rate\n1,A,0.1,0.2\n", encoding="utf-8"
        )
        (rc_dir / "chronos.csv").write_text("num,chrono\n1,1.0\n", encoding="utf-8")
        enrich_calls.append(rc_dir)

    monkeypatch.setattr(acde, "enrich_h5", fake_enrich)

    pipeline_calls: list[Path] = []
    monkeypatch.setattr(
        acde, "build_p_finale", lambda rc_dir, **kw: pipeline_calls.append(rc_dir)
    )
    monkeypatch.setattr(
        acde, "run_pipeline", lambda rc_dir, **kw: pipeline_calls.append(rc_dir)
    )
    monkeypatch.setattr(
        acde,
        "build_prompt_from_meta",
        lambda rc_dir, **kw: pipeline_calls.append(rc_dir),
    )

    csv_calls: list[Path] = []
    monkeypatch.setattr(
        acde,
        "export_per_horse_csv",
        lambda rc_dir: (csv_calls.append(rc_dir) or (rc_dir / "per_horse_report.csv")),
    )

    argv = [
        "analyse_courses_du_jour_enrichie.py",
        "--course-url",
        "https://www.zeturf.fr/fr/reunion/2024-09-25/R1-test",
        "--phase",
        phase,
        "--data-dir",
        str(tmp_path),
    ]
    monkeypatch.setattr(sys, "argv", argv)
    acde.main()

    assert [(c, p) for c, p, *_ in snaps] == [("123", phase), ("456", phase)]
    assert [url for *_rest, url in snaps] == [
        "https://www.zeturf.fr/fr/course/123",
        "https://www.zeturf.fr/fr/course/456",
    ]
    if expect_pipeline:
        assert len(enrich_calls) == 2
        assert len(pipeline_calls) == 6  # 3 funcs * 2 courses
        assert len(csv_calls) == 2
    else:
        assert not enrich_calls
        assert not pipeline_calls
        assert not csv_calls


def test_course_url_shortcuts_single_course(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    html = """
    <html>
      <body>
        <h1>R1 - C3</h1>
      </body>
    </html>
    """

    requested: list[str] = []

    def fake_get(url: str, headers: dict | None = None, timeout: int = 10) -> DummyResp:
        requested.append(url)
        return DummyResp(html)

    monkeypatch.setattr(acde.requests, "get", fake_get)

    captured: dict[str, Any] = {}

    def fake_snapshot(
        cid: str, ph: str, rc_dir: Path, *, course_url: str | None = None
    ) -> Path:
        captured.update(
            {
                "course_id": cid,
                "phase": ph,
                "rc_dir": rc_dir,
                "course_url": course_url,
            }
        )
        rc_dir.mkdir(parents=True, exist_ok=True)
        dest = rc_dir / "snap.json"
        dest.write_text("{}", encoding="utf-8")
        return dest

    monkeypatch.setattr(acde, "write_snapshot_from_geny", fake_snapshot)

    argv = [
        "analyse_courses_du_jour_enrichie.py",
        "--course-url",
        "https://www.zeturf.fr/fr/course/654321",
        "--phase",
        "H30",
        "--data-dir",
        str(tmp_path),
    ]
    monkeypatch.setattr(sys, "argv", argv)

    acde.main()

    assert requested == ["https://www.zeturf.fr/fr/course/654321"]
    assert captured["course_id"] == "654321"
    assert captured["phase"].upper() == "H30"
    assert captured["course_url"] == "https://www.zeturf.fr/fr/course/654321"
    assert captured["rc_dir"].relative_to(tmp_path) == Path("R1C3")


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
            "--course-url",
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
            "--course-url",
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


def test_missing_enrich_outputs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    html = """
    <html><body><a href="/fr/course/123">C1</a></body></html>
    """

    def fake_get(url: str, headers: dict | None = None, timeout: int = 10) -> DummyResp:
        return DummyResp(html)

    monkeypatch.setattr(acde.requests, "get", fake_get)

    def fake_snapshot(
        cid: str, ph: str, rc_dir: Path, *, course_url: str | None = None
    ) -> Path:
        dest = rc_dir / "snap_H-5.json"
        payload = {"id_course": cid, "course_id": cid}
        dest.write_text(json.dumps(payload), encoding="utf-8")
        return dest

    monkeypatch.setattr(acde, "write_snapshot_from_geny", fake_snapshot)

    def fake_enrich(rc_dir: Path, **kw) -> None:
        snap_path = rc_dir / "snap_H-5.json"
        course_id = ""
        if snap_path.exists():
            try:
                payload = json.loads(snap_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                payload = {}
            course_id = str(
                (payload.get("id_course") or payload.get("course_id") or "")
            )
        minimal = {"course_id": course_id, "runners": [{"id": "1", "chrono": ""}]}
        (rc_dir / "normalized_h5.json").write_text(
            json.dumps(minimal), encoding="utf-8"
        )
        (rc_dir / "partants.json").write_text(json.dumps(minimal), encoding="utf-8")

    monkeypatch.setattr(acde, "enrich_h5", fake_enrich)
    monkeypatch.setattr(acde.time, "sleep", lambda delay: None)
    monkeypatch.setattr(acde, "build_p_finale", lambda *a, **k: None)
    monkeypatch.setattr(acde, "run_pipeline", lambda *a, **k: None)
    monkeypatch.setattr(acde, "build_prompt_from_meta", lambda *a, **k: None)
    monkeypatch.setattr(acde, "export_per_horse_csv", lambda *a, **k: None)

    calls: list[list[str]] = []

    def fake_run(cmd: list[str], check: bool = False):
        calls.append(cmd)
        return types.SimpleNamespace(returncode=0)

    monkeypatch.setattr(acde.subprocess, "run", fake_run)

    argv = [
        "analyse_courses_du_jour_enrichie.py",
        "--course-url",
        "https://www.zeturf.fr/fr/reunion/2024-09-25/R1-test",
        "--phase",
        "H5",
        "--data-dir",
        str(tmp_path),
    ]
    monkeypatch.setattr(sys, "argv", argv)
    acde.main()

    rc_dir = next(tmp_path.glob("R*C*"))
    decision_path = rc_dir / "decision.json"
    assert decision_path is not None
    payload = json.loads(decision_path.read_text(encoding="utf-8"))
    assert payload.get("status") == "no-bet"
    assert payload.get("decision") == "ABSTENTION"
    assert payload.get("reason") == "data-missing"

    details = payload.get("details", {})
    assert isinstance(details, dict)
    missing = details.get("missing")
    assert missing == ["snap_H-5_je.csv"]
    marker = rc_dir / "UNPLAYABLE.txt"
    assert marker.exists()
    chronos_path = rc_dir / "chronos.csv"
    assert chronos_path.exists()
    fetch_stats = str(
        Path(acde.__file__).resolve().with_name("scripts") / "fetch_je_stats.py"
    )
    assert calls == [
        [
            sys.executable,
            fetch_stats,
            "--course-id",
            "123",
            "--h5",
            str(rc_dir / "normalized_h5.json"),
            "--out",
            str(rc_dir / "stats_je.json"),
        ]
    ]


def test_missing_enrich_outputs_recovers_after_fetch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    html = """
    <html><body><a href="/fr/course/123">C1</a></body></html>
    """

    monkeypatch.setattr(acde.requests, "get", lambda *a, **k: DummyResp(html))

    def fake_snapshot(
        cid: str, ph: str, rc_dir: Path, *, course_url: str | None = None
    ) -> Path:
        dest = rc_dir / "snap_H-5.json"
        payload = {"id_course": cid, "course_id": cid}
        dest.write_text(json.dumps(payload), encoding="utf-8")
        return dest

    monkeypatch.setattr(acde, "write_snapshot_from_geny", fake_snapshot)
    monkeypatch.setattr(acde, "enrich_h5", lambda rc_dir, **kw: None)

    def fake_guard(rc_dir: Path, *, budget: float) -> tuple[bool, dict[str, Any], None]:
        return True, {}, None

    monkeypatch.setattr(acde, "_run_h5_guard_phase", fake_guard)

    def fake_enrich(rc_dir: Path, **kw) -> None:
        snap_path = rc_dir / "snap_H-5.json"
        course_id = ""
        if snap_path.exists():
            try:
                payload = json.loads(snap_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                payload = {}
            course_id = str(
                (payload.get("id_course") or payload.get("course_id") or "")
            )
        minimal = {"course_id": course_id, "runners": [{"id": "1", "chrono": "1.0"}]}
        (rc_dir / "normalized_h5.json").write_text(
            json.dumps(minimal), encoding="utf-8"
        )
        (rc_dir / "partants.json").write_text(json.dumps(minimal), encoding="utf-8")

    monkeypatch.setattr(acde, "enrich_h5", fake_enrich)

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
        lambda rc_dir: (
            pipeline_calls.append(rc_dir) or (rc_dir / "per_horse_report.csv")
        ),
    )

    def fake_run(cmd: list[str], check: bool = False):
        if "fetch_je_stats.py" in cmd[1]:
            out_index = cmd.index("--out")
            rc_dir = Path(cmd[out_index + 1]).parent
        snap = rc_dir / "snap_H-5.json"
        if snap.exists():
            if "fetch_je_stats.py" in cmd[1]:
                (rc_dir / f"{snap.stem}_je.csv").write_text(
                    "num,nom,j_rate,e_rate\n1,A,0.1,0.2\n",
                    encoding="utf-8",
                )
        return types.SimpleNamespace(returncode=0)

    monkeypatch.setattr(acde.subprocess, "run", fake_run)

    argv = [
        "analyse_courses_du_jour_enrichie.py",
        "--course-url",
        "https://www.zeturf.fr/fr/reunion/2024-09-25/R1-test",
        "--phase",
        "H5",
        "--data-dir",
        str(tmp_path),
    ]
    monkeypatch.setattr(sys, "argv", argv)
    acde.main()

    rc_dir = next(tmp_path.glob("R*C*"))
    assert not (rc_dir / "UNPLAYABLE.txt").exists()
    assert (rc_dir / "decision.json").exists() is False
    assert len(pipeline_calls) == 4


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


def test_export_per_horse_csv_missing_je(tmp_path: Path) -> None:
    snap = tmp_path / "snap_H-5.json"
    snap.write_text("{}", encoding="utf-8")
    (tmp_path / "chronos.csv").write_text("num,chrono\n1,1.0\n", encoding="utf-8")
    data = {"p_true": {"1": 0.5}, "meta": {"id2name": {"1": "A"}}}
    (tmp_path / "p_finale.json").write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(FileNotFoundError):
        acde.export_per_horse_csv(tmp_path)


def test_export_per_horse_csv_missing_chronos(tmp_path: Path) -> None:
    snap = tmp_path / "snap_H-5.json"
    snap.write_text("{}", encoding="utf-8")
    (tmp_path / f"{snap.stem}_je.csv").write_text(
        "num,nom,j_rate,e_rate\n1,A,0.1,0.2\n", encoding="utf-8"
    )
    data = {"p_true": {"1": 0.5}, "meta": {"id2name": {"1": "A"}}}
    (tmp_path / "p_finale.json").write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(FileNotFoundError):
        acde.export_per_horse_csv(tmp_path)


def test_h5_pipeline_produces_outputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    meeting_payload = {
        "meetings": [
            {
                "r": "R1",
                "courses": [
                    {
                        "c": "C1",
                        "id_course": "COURSE42",
                    }
                ],
            }
        ]
    }
    monkeypatch.setattr(acde, "_load_geny_today_payload", lambda: meeting_payload)

    base_meta = {
        "id_course": "COURSE42",
        "rc": "R1C1",
        "hippodrome": "TestVille",
        "date": "2025-09-10",
        "discipline": "plat",
        "r_label": "R1",
    }
    h30_runners = [
        {"id": str(idx), "name": name, "odds": odds}
        for idx, (name, odds) in enumerate(
            [
                ("Alpha", 2.0),
                ("Bravo", 3.0),
                ("Charlie", 4.0),
                ("Delta", 6.0),
                ("Echo", 8.5),
                ("Foxtrot", 10.0),
            ],
            start=1,
        )
    ]
    h5_runners = [dict(runner, odds=runner["odds"] * 1.05) for runner in h30_runners]

    h30_payload = dict(base_meta)
    h30_payload["runners"] = h30_runners
    h5_payload = dict(base_meta)
    h5_payload["runners"] = h5_runners

    h30_filename = "20250910T150000_R1C1_H-30.json"
    h5_filename = "20250910T155000_R1C1_H-5.json"

    def fake_write_snapshot(
        course_id: str, phase: str, rc_dir: Path, *, course_url: str | None = None
    ) -> Path:
        rc_dir.mkdir(parents=True, exist_ok=True)
        if phase.upper() == "H30":
            dest = rc_dir / h30_filename
            dest.write_text(json.dumps(h30_payload), encoding="utf-8")
            return dest
        if phase.upper() == "H5":
            # Ensure the H-30 snapshot is present so the enrich step can load it.
            h30_dest = rc_dir / h30_filename
            if not h30_dest.exists():
                h30_dest.write_text(json.dumps(h30_payload), encoding="utf-8")
            dest = rc_dir / h5_filename
            dest.write_text(json.dumps(h5_payload), encoding="utf-8")
            return dest
        raise AssertionError("unexpected phase")

    monkeypatch.setattr(acde, "write_snapshot_from_geny", fake_write_snapshot)

    def fake_guard(rc_dir: Path, *, budget: float) -> tuple[bool, dict[str, Any], None]:
        return True, {}, None

    monkeypatch.setattr(acde, "_run_h5_guard_phase", fake_guard)
    stats_map = {
        str(idx): {"j_win": 20 + idx, "e_win": 15 + idx} for idx in range(1, 7)
    }
    monkeypatch.setattr(
        acde, "collect_stats", lambda *args, **kwargs: (100.0, stats_map)
    )

    argv = [
        "analyse_courses_du_jour_enrichie.py",
        "--reunion",
        "R1",
        "--course",
        "C1",
        "--phase",
        "H5",
        "--data-dir",
        str(tmp_path),
    ]
    monkeypatch.setattr(sys, "argv", argv)
    acde.main()

    rc_dir = tmp_path / "R1C1"
    p_finale_path = rc_dir / "p_finale.json"
    assert p_finale_path.exists()
    data = json.loads(p_finale_path.read_text(encoding="utf-8"))
    assert data.get("meta", {}).get("rc") == "R1C1"
    assert (rc_dir / f"{Path(h5_filename).stem}_je.csv").exists()
    assert (rc_dir / "chronos.csv").exists()
    assert (rc_dir / "prompts" / "prompt.txt").exists()
