import subprocess
from pathlib import Path

import main


def _recording_run(recorder):
    def _run(cmd, **kwargs):
        recorder.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="ok\n", stderr="")

    return _run


def test_analyse_meeting_splits_into_reunion_and_course(monkeypatch):
    recorded_cmds = []
    monkeypatch.setattr(main.subprocess, "run", _recording_run(recorded_cmds))

    params = main.AnalyseParams(meeting="R1C3", phase="H5", run_export=False)
    result = main.analyse(params)

    assert result.ok is True
    assert recorded_cmds, "Le script principal doit être invoqué"
    cmd = recorded_cmds[0]
    assert "--data-dir" in cmd
    data_dir_index = cmd.index("--data-dir")
    assert cmd[data_dir_index + 1] == result.outputs_dir
    assert "--meeting" not in cmd
    assert "--reunion" in cmd
    assert "--course" in cmd
    reunion_index = cmd.index("--reunion")
    course_index = cmd.index("--course")
    assert cmd[reunion_index + 1] == "R1"
    assert cmd[course_index + 1] == "C3"


def test_analyse_accepts_separate_reunion_course(monkeypatch):
    recorded_cmds = []
    monkeypatch.setattr(main.subprocess, "run", _recording_run(recorded_cmds))

    params = main.AnalyseParams(reunion="r2", course="5", phase="H30", run_export=False)
    result = main.analyse(params)

    assert result.ok is True
    cmd = recorded_cmds[0]
    assert "--data-dir" in cmd
    data_dir_index = cmd.index("--data-dir")
    assert cmd[data_dir_index + 1] == result.outputs_dir
    reunion_index = cmd.index("--reunion")
    course_index = cmd.index("--course")
    assert cmd[reunion_index + 1] == "R2"
    assert cmd[course_index + 1] == "C5"


def test_analyse_maps_course_url_to_reunion_url(monkeypatch):
    recorded_cmds = []
    monkeypatch.setattr(main.subprocess, "run", _recording_run(recorded_cmds))

    params = main.AnalyseParams(
        course_url="https://example.test/reunion",
        phase="H30",
        run_export=False,
    )
    result = main.analyse(params)

    assert result.ok is True
    assert recorded_cmds, "Le script principal doit être invoqué"
    cmd = recorded_cmds[0]
    assert "--data-dir" in cmd
    data_dir_index = cmd.index("--data-dir")
    assert cmd[data_dir_index + 1] == result.outputs_dir
    assert "--reunion-url" in cmd
    url_index = cmd.index("--reunion-url")
    assert cmd[url_index + 1] == params.course_url
    assert "--course-url" not in cmd



def test_analyse_export_discovers_p_finale(monkeypatch, tmp_path):
    recorded_cmds = []
    outputs_dir = tmp_path / "call_outputs"
    outputs_dir.mkdir()

    def fake_mkdtemp(prefix):
        return str(outputs_dir)

    def _run(cmd, **kwargs):
        recorded_cmds.append(cmd)
        if "p_finale_export.py" in cmd:
            idx = cmd.index("--outputs-dir")
            export_dir = Path(cmd[idx + 1])
            export_dir.mkdir(parents=True, exist_ok=True)
            (export_dir / "p_finale.json").write_text('{"status": "ok"}', encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, stdout="ok\n", stderr="")

    monkeypatch.setattr(main.tempfile, "mkdtemp", fake_mkdtemp)
    monkeypatch.setattr(main.subprocess, "run", _run)

    params = main.AnalyseParams(phase="H5")
    result = main.analyse(params)

    assert result.ok is True
    assert Path(result.outputs_dir) == outputs_dir
    assert result.p_finale_path == str(outputs_dir / "p_finale.json")

    assert len(recorded_cmds) == 2
    pipeline_cmd, export_cmd = recorded_cmds

    assert "--data-dir" in pipeline_cmd
    data_dir_index = pipeline_cmd.index("--data-dir")
    assert pipeline_cmd[data_dir_index + 1] == str(outputs_dir)

    assert "p_finale_export.py" in export_cmd
    assert "--outputs-dir" in export_cmd
    export_dir_index = export_cmd.index("--outputs-dir")
    assert export_cmd[export_dir_index + 1] == str(outputs_dir)
