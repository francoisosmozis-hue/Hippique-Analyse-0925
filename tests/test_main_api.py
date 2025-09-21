import subprocess

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
    assert "--reunion-url" in cmd
    url_index = cmd.index("--reunion-url")
    assert cmd[url_index + 1] == params.course_url
    assert "--course-url" not in cmd
