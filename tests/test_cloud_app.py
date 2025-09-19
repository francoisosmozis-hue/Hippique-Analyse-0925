import json
import sys

import pytest

from cloud import app as cloud_app


class DummyRequest:
    def __init__(self, payload):
        self._payload = payload

    def get_json(self, silent: bool = False):  # pragma: no cover - simple helper
        return self._payload


def test_run_hminus_invokes_script(monkeypatch):
    recorded = {}

    def fake_run(cmd, check, cwd=None):
        recorded["cmd"] = cmd
        recorded["check"] = check
        recorded["cwd"] = cwd

    monkeypatch.setattr(cloud_app.subprocess, "run", fake_run)

    body, status, headers = cloud_app.run_hminus(DummyRequest({"R": "R1", "C": "C2", "when": "H-5"}))

    assert status == 200
    assert json.loads(body) == {"ok": True}
    assert headers["Content-Type"] == "application/json"
    assert recorded["check"] is True
    assert recorded["cwd"] == str(cloud_app.ROOT)
    cmd = recorded["cmd"]
    assert cmd[0] == sys.executable
    assert cmd[1] == str(cloud_app.SCRIPT)
    assert cmd[2:] == ["--reunion", "R1", "--course", "C2", "--phase", "H5"]


@pytest.mark.parametrize(
    "payload",
    [
        {"R": "foo", "C": "C2", "when": "H-5"},
        {"R": "R1", "C": "C2"},
    ],
)
def test_run_hminus_rejects_invalid_payload(monkeypatch, payload):
    called = False

    def fake_run(*args, **kwargs):  # pragma: no cover - should not be called
        nonlocal called
        called = True

    monkeypatch.setattr(cloud_app.subprocess, "run", fake_run)

    body, status, headers = cloud_app.run_hminus(payload)

    assert status == 400
    assert json.loads(body)["ok"] is False
    assert headers["Content-Type"] == "application/json"
    assert called is False
