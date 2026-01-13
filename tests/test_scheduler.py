from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from hippique_orchestrator import scheduler

# A sample plan with one race in the past and one in the future
# Use a fixed 'now' to avoid race conditions when tests run near midnight
now = datetime.now()
future_time = now + timedelta(hours=1)
past_time = now - timedelta(hours=1)

SAMPLE_PLAN = [
    {
        "r_label": "R1",
        "c_label": "C1",
        "time_local": past_time.strftime("%H:%M"),
        "date": past_time.strftime("%Y-%m-%d"),
        "course_url": "http://example.com/r1c1",
    },
    {
        "r_label": "R1",
        "c_label": "C2",
        "time_local": future_time.strftime("%H:%M"),
        "date": future_time.strftime("%Y-%m-%d"),
        "course_url": "http://example.com/r1c2",
    },
]


def test_schedule_all_races_dry_run_no_force():
    """
    Given a plan with a past race, a dry run without force should mark it as skipped.
    """
    results = scheduler.schedule_all_races(
        plan=SAMPLE_PLAN, force=False, dry_run=True, service_url="http://test.service"
    )

    skipped_tasks = [r for r in results if not r["ok"]]
    candidate_tasks = [r for r in results if r["ok"]]

    # R1C1 (H30 and H5) should be skipped because it's in the past
    assert len(skipped_tasks) == 2
    assert all("R1C1" in task["race"] and "in the past" in task["reason"] for task in skipped_tasks)

    # R1C2 (H30 and H5) should be a candidate
    assert len(candidate_tasks) == 2
    assert all("R1C2" in task["race"] for task in candidate_tasks)


def test_schedule_all_races_dry_run_with_force():
    """
    Given a plan with a past race, a dry run with force should make it a candidate.
    """
    results = scheduler.schedule_all_races(
        plan=SAMPLE_PLAN, force=True, dry_run=True, service_url="http://test.service"
    )

    skipped_tasks = [r for r in results if not r["ok"]]
    candidate_tasks = [r for r in results if r["ok"]]

    # With force=True, all tasks should be candidates
    assert len(candidate_tasks) == 4  # 2 races * 2 phases
    assert len(skipped_tasks) == 0

    # Check if the reason for forcing is logged
    assert all("Forced schedule" in task["reason"] for task in candidate_tasks)


def test_schedule_all_races_real_run_with_force(mock_cloud_tasks):
    """
    A real run with force=True should attempt to create tasks for all races.
    """
    results = scheduler.schedule_all_races(
        plan=SAMPLE_PLAN, force=True, dry_run=False, service_url="http://test.service"
    )

    # All 4 potential tasks should have been processed
    assert len(results) == 4
    # The client's create_task method should have been called for each of the 4 candidate tasks
    assert mock_cloud_tasks.create_task.call_count == 4
    # All results should indicate success
    assert all(r["ok"] for r in results)


def test_schedule_all_races_real_run_no_force(mock_cloud_tasks):
    """
    A real run without force should only create tasks for future races.
    """
    results = scheduler.schedule_all_races(
        plan=SAMPLE_PLAN, force=False, dry_run=False, service_url="http://test.service"
    )

    # All 4 potential tasks are in the results list
    assert len(results) == 4

    # But create_task is only called for the 2 future tasks
    assert mock_cloud_tasks.create_task.call_count == 2

    # Check that the skipped tasks are marked as not "ok"
    skipped_results = [r for r in results if not r["ok"]]
    assert len(skipped_results) == 2
    assert all("R1C1" in r["race"] for r in skipped_results)

    # Check that the successful tasks are marked as "ok"
    ok_results = [r for r in results if r["ok"]]
    assert len(ok_results) == 2
    assert all("R1C2" in r["race"] for r in ok_results)
