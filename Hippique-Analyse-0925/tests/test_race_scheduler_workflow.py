from pathlib import Path

import yaml


def test_race_scheduler_dispatch_inputs_and_schedule_path():
    workflow_path = Path(".github/workflows/race_scheduler.yml")
    data = yaml.safe_load(workflow_path.read_text())

    triggers = data.get("on") or data.get(True) or {}
    dispatch = triggers.get("workflow_dispatch", {})
    inputs = dispatch.get("inputs", {})
    expected_keys = {
        "mode",
        "course_id",
        "date",
        "meeting",
        "race",
        "hippodrome",
        "discipline",
    }
    assert expected_keys.issubset(inputs.keys())

    concurrency = data.get("concurrency", {})
    group = concurrency.get("group", "")
    assert "github.event.inputs.course_id" in group

    schedule_runner = data["jobs"].get("schedule-runner")
    assert schedule_runner is not None

    steps = schedule_runner.get("steps", [])
    run_step = next(
        step for step in steps if step.get("name") == "Run scheduler windows (H-30/H-5)"
    )
    assert "if" not in run_step, "cron execution should remain unconditional"
