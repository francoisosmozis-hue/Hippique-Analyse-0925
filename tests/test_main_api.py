import json
import subprocess
from pathlib import Path
from typing import get_args

import anyio

import analyse_courses_du_jour_enrichie as acde
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
    assert "--budget" in cmd
    budget_index = cmd.index("--budget")
    assert cmd[budget_index + 1] == str(main.DEFAULT_BUDGET)
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
    assert "--budget" in cmd
    budget_index = cmd.index("--budget")
    assert cmd[budget_index + 1] == str(main.DEFAULT_BUDGET)
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
    assert "--budget" in cmd
    budget_index = cmd.index("--budget")
    assert cmd[budget_index + 1] == str(main.DEFAULT_BUDGET)
    assert "--reunion-url" in cmd
    url_index = cmd.index("--reunion-url")
    assert cmd[url_index + 1] == params.course_url
    assert "--course-url" not in cmd


def test_analyse_passes_budget_override(monkeypatch):
    recorded_cmds = []
    monkeypatch.setattr(main.subprocess, "run", _recording_run(recorded_cmds))

    params = main.AnalyseParams(default_budget=42.5, run_export=False)
    result = main.analyse(params)

    assert result.ok is True
    assert recorded_cmds, "Le script principal doit être invoqué"
    cmd = recorded_cmds[0]
    assert "--budget" in cmd
    budget_index = cmd.index("--budget")
    assert cmd[budget_index + 1] == str(params.default_budget)


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


def test_fastapi_analyse_returns_500_on_pipeline_failure(monkeypatch):
    def _failing_run(cmd, **kwargs):
        return subprocess.CompletedProcess(
            cmd,
            1,
            stdout="info\n",
            stderr="boom\n",
        )

    monkeypatch.setattr(main.subprocess, "run", _failing_run)

    async def post_analyse_async(payload: dict) -> tuple[int, list[tuple[bytes, bytes]], bytes]:
        body_bytes = json.dumps(payload).encode("utf-8")
        events = [
            {"type": "http.request", "body": body_bytes, "more_body": False},
        ]

        async def receive() -> dict:
            if events:
                return events.pop(0)
            return {"type": "http.disconnect"}

        messages: list[dict] = []

        async def send(message: dict) -> None:
            messages.append(message)

        scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/analyse",
            "raw_path": b"/analyse",
            "headers": [
                (b"host", b"testserver"),
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body_bytes)).encode("latin-1")),
            ],
            "query_string": b"",
            "root_path": "",
            "client": ("testclient", 50000),
            "server": ("testserver", 80),
            "state": {},
        }

        await main.app(scope, receive, send)

        start_message = next(msg for msg in messages if msg["type"] == "http.response.start")
        status_code = start_message["status"]
        headers = start_message.get("headers", [])
        body_chunks = [msg.get("body", b"") for msg in messages if msg["type"] == "http.response.body"]
        return status_code, headers, b"".join(body_chunks)

    def post_analyse(payload: dict) -> tuple[int, list[tuple[bytes, bytes]], bytes]:
        return anyio.run(post_analyse_async, payload, backend="asyncio")

    status_code, _, body = post_analyse({"phase": "H5", "run_export": False})

    assert status_code == 500
    payload = json.loads(body.decode("utf-8"))
    assert "detail" in payload
    assert "analyse_courses_du_jour_enrichie.py a échoué" in payload["detail"]
    assert "STDERR" in payload["detail"]


def test_fastapi_analyse_accepts_declared_phases(monkeypatch, tmp_path):
    phase_field = main.AnalyseParams.model_fields["phase"]
    declared_phases = list(get_args(phase_field.annotation))
    assert declared_phases, "AnalyseParams.phase should advertise at least one option"

    recorded_cmds = []

    def _phase_guard_run(cmd, **kwargs):
        recorded_cmds.append(cmd)
        if "--phase" in cmd:
            idx = cmd.index("--phase")
            phase_value = cmd[idx + 1]
            try:
                acde._normalise_phase(phase_value)
            except ValueError as exc:  # pragma: no cover - defensive
                raise RuntimeError(f"Invalid phase {phase_value!r}") from exc
        return subprocess.CompletedProcess(cmd, 0, stdout="ok\n", stderr="")

    counter = {"value": 0}
    created_dirs = []

    def fake_mkdtemp(prefix):
        counter["value"] += 1
        path = tmp_path / f"{prefix}{counter['value']}"
        path.mkdir(parents=True, exist_ok=True)
        created_dirs.append(path)
        return str(path)

    monkeypatch.setattr(main.subprocess, "run", _phase_guard_run)
    monkeypatch.setattr(main.tempfile, "mkdtemp", fake_mkdtemp)

    async def post_analyse_async(payload: dict) -> tuple[int, list[tuple[bytes, bytes]], bytes]:
        body_bytes = json.dumps(payload).encode("utf-8")
        events = [
            {"type": "http.request", "body": body_bytes, "more_body": False},
        ]

        async def receive() -> dict:
            if events:
                return events.pop(0)
            return {"type": "http.disconnect"}

        messages: list[dict] = []

        async def send(message: dict) -> None:
            messages.append(message)

        scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/analyse",
            "raw_path": b"/analyse",
            "headers": [
                (b"host", b"testserver"),
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body_bytes)).encode("latin-1")),
            ],
            "query_string": b"",
            "root_path": "",
            "client": ("testclient", 50000),
            "server": ("testserver", 80),
            "state": {},
        }

        await main.app(scope, receive, send)

        start_message = next(msg for msg in messages if msg["type"] == "http.response.start")
        status_code = start_message["status"]
        headers = start_message.get("headers", [])
        body_chunks = [msg.get("body", b"") for msg in messages if msg["type"] == "http.response.body"]
        return status_code, headers, b"".join(body_chunks)

    def post_analyse(payload: dict) -> tuple[int, list[tuple[bytes, bytes]], bytes]:
        return anyio.run(post_analyse_async, payload, backend="asyncio")

    for phase in declared_phases:
        recorded_cmds.clear()
        status_code, _, body = post_analyse({"phase": phase, "run_export": False})
        assert status_code == 200, body.decode("utf-8")
        payload = json.loads(body.decode("utf-8"))
        assert payload["ok"] is True
        assert payload["params"]["phase"] == phase
        assert recorded_cmds, "Le script principal doit être invoqué"
        cmd = recorded_cmds[0]
        assert "analyse_courses_du_jour_enrichie.py" in cmd
        phase_index = cmd.index("--phase")
        assert cmd[phase_index + 1] == phase
        data_dir_index = cmd.index("--data-dir")
        assert cmd[data_dir_index + 1] == str(created_dirs[-1])
