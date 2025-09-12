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
    monkeypatch.setattr(
        acde,
        "write_snapshot_from_geny",
        lambda cid, ph, rc_dir: snaps.append((cid, ph, rc_dir)),
    )

    enrich_calls: list[Path] = []
    monkeypatch.setattr(acde, "enrich_h5", lambda rc_dir, **kw: enrich_calls.append(rc_dir))
    monkeypatch.setattr(acde, "build_p_finale", lambda rc_dir, **kw: enrich_calls.append(rc_dir))
    monkeypatch.setattr(acde, "run_pipeline", lambda rc_dir, **kw: enrich_calls.append(rc_dir))
    monkeypatch.setattr(acde, "build_prompt_from_meta", lambda rc_dir, **kw: enrich_calls.append(rc_dir))

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
        assert len(enrich_calls) == 8  # 4 funcs * 2 courses
    else:
        assert not enrich_calls


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
