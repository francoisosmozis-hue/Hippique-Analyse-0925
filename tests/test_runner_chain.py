import pytest
import sys
import subprocess
import json
from pathlib import Path
from src.hippique_orchestrator import runner_chain

@pytest.fixture
def mock_dependencies(mocker):
    """Mocks all external dependencies for runner_chain."""
    mocker.patch("src.hippique_orchestrator.runner_chain.run_subprocess")
    mocker.patch("src.hippique_orchestrator.runner_chain.run_pipeline", return_value={"abstain": True, "tickets": []})
    mocker.patch("src.hippique_orchestrator.runner_chain.send_email")
    mocker.patch("src.hippique_orchestrator.runner_chain.render_ticket_html")
    mocker.patch("src.hippique_orchestrator.runner_chain.fetch_and_write_arrivals")
    mocker.patch("src.hippique_orchestrator.runner_chain.update_excel")
    mocker.patch("pathlib.Path.mkdir")

def test_run_chain_h30_zeturf_success(mock_dependencies, mocker):
    """Tests the H30 phase with zeturf source on success."""
    result = runner_chain.run_chain(reunion="R1", course="C1", phase="H30", budget=5.0, source="zeturf")

    # Check that the correct script was called
    run_subprocess_mock = runner_chain.run_subprocess
    run_subprocess_mock.assert_called_once()
    args, _ = run_subprocess_mock.call_args
    cmd = args[0]
    assert "online_fetch_zeturf.py" in cmd[1]
    assert "--reunion" in cmd
    assert "R1" in cmd
    assert "--course" in cmd
    assert "C1" in cmd

    # Check the output message
    assert "H-30 snapshot created from zeturf" in result["message"]
    assert result["abstain"] is True

def test_run_chain_h30_boturfers_success(mock_dependencies, mocker):
    """Tests the H30 phase with boturfers source on success."""
    runner_chain.run_chain(reunion="R1", course="C1", phase="H30", budget=5.0, source="boturfers")

    # Check that the correct script was called
    run_subprocess_mock = runner_chain.run_subprocess
    run_subprocess_mock.assert_called_once()
    args, _ = run_subprocess_mock.call_args
    cmd = args[0]
    assert "online_fetch_boturfers.py" in cmd[1]

def test_validate_snapshot_or_die_invalid_type():
    """Tests that validate_snapshot_or_die exits on invalid snapshot type."""
    with pytest.raises(SystemExit) as e:
        runner_chain.validate_snapshot_or_die([], "H5")
    assert e.value.code == 2

def test_validate_snapshot_or_die_no_runners():
    """Tests that validate_snapshot_or_die exits on empty runners list."""
    with pytest.raises(SystemExit) as e:
        runner_chain.validate_snapshot_or_die({"runners": []}, "H5")
    assert e.value.code == 2

def test_validate_snapshot_or_die_success():
    """Tests that validate_snapshot_or_die passes with valid data."""
    try:
        runner_chain.validate_snapshot_or_die({"runners": [{"num": 1}]}, "H5")
    except SystemExit:
        pytest.fail("validate_snapshot_or_die failed with valid data")

def test_run_chain_h5_success(mock_dependencies, mocker):
    """Tests the H5 phase on success without email."""
    mocker.patch("pathlib.Path.exists", return_value=True)

    runner_chain.run_chain(reunion="R1", course="C1", phase="H5", budget=5.0)

    run_subprocess_mock = runner_chain.run_subprocess
    assert run_subprocess_mock.call_count == 2
    call_args_list = run_subprocess_mock.call_args_list
    assert "fetch_je_stats.py" in call_args_list[0].args[0][1]
    assert "fetch_je_chrono.py" in call_args_list[1].args[0][1]

    runner_chain.run_pipeline.assert_called_once_with(reunion="R1", course="C1", phase="H5", budget=5.0)
    runner_chain.send_email.assert_not_called()

def test_run_chain_h5_sends_email_on_tickets(mock_dependencies, mocker):
    """Tests that H5 phase sends an email when tickets are generated."""
    mocker.patch("pathlib.Path.exists", return_value=True)
    mocker.patch.dict(runner_chain.os.environ, {"EMAIL_TO": "test@example.com"})
    runner_chain.run_pipeline.return_value = {
        "abstain": False,
        "tickets": [{"type": "SP_DUTCHING", "stake": 3.0}],
        "roi_global_est": 0.25
    }

    runner_chain.run_chain(reunion="R1", course="C1", phase="H5", budget=5.0)

    runner_chain.send_email.assert_called_once()
    args, _ = runner_chain.send_email.call_args
    assert "Tickets Hippiques pour R1C1" in args[0]
    assert "test@example.com" in args[2]

def test_run_chain_h5_abstains_on_enrichment_failure(mock_dependencies, mocker):
    """Tests that H5 phase abstains if an enrichment script fails."""
    run_subprocess_mock = runner_chain.run_subprocess
    run_subprocess_mock.side_effect = subprocess.CalledProcessError(1, "cmd", "Error")

    result = runner_chain.run_chain(reunion="R1", course="C1", phase="H5", budget=5.0)

    assert result["abstain"] is True
    assert "enrichment fetch failed" in result["message"]
    runner_chain.run_pipeline.assert_not_called()

def test_run_chain_h5_abstains_on_missing_enrichment_files(mock_dependencies, mocker):
    """Tests that H5 phase abstains if enrichment files are not created."""
    mocker.patch("pathlib.Path.exists", return_value=False)

    result = runner_chain.run_chain(reunion="R1", course="C1", phase="H5", budget=5.0)

    assert result["abstain"] is True
    assert "missing J/E or chrono data" in result["message"]
    runner_chain.run_pipeline.assert_not_called()

def test_run_chain_result_success(mock_dependencies, mocker):
    """Tests the RESULT phase on a full success path."""
    mocker.patch("pathlib.Path.exists", return_value=True)

    result = runner_chain.run_chain(reunion="R1", course="C1", phase="RESULT", budget=5.0)

    runner_chain.fetch_and_write_arrivals.assert_called_once()
    runner_chain.update_excel.assert_called_once()
    assert result["message"] == "Result phase completed."

def test_run_chain_result_skips_on_missing_planning_file(mock_dependencies, mocker):
    """Tests that RESULT phase skips processing if the planning file is missing."""
    mocker.patch("pathlib.Path.exists", side_effect=[False])

    runner_chain.run_chain(reunion="R1", course="C1", phase="RESULT", budget=5.0)

    runner_chain.fetch_and_write_arrivals.assert_not_called()
    runner_chain.update_excel.assert_not_called()

def test_run_chain_result_skips_excel_on_missing_arrivals(mock_dependencies, mocker):
    """Tests that RESULT phase skips Excel update if arrivals file is missing."""
    mocker.patch("pathlib.Path.exists", side_effect=[True, False, True])

    runner_chain.run_chain(reunion="R1", course="C1", phase="RESULT", budget=5.0)

    runner_chain.fetch_and_write_arrivals.assert_called_once()
    runner_chain.update_excel.assert_not_called()

def test_run_chain_unknown_phase(mock_dependencies):
    """Tests that an unknown phase returns a specific message."""
    result = runner_chain.run_chain(reunion="R1", course="C1", phase="UNKNOWN", budget=5.0)
    assert result["message"] == "Unknown phase."

def test_main_calls_run_chain_with_args(mocker):
    """Tests that the main CLI entrypoint parses args and calls run_chain."""
    mocker.patch.object(runner_chain.sys, "argv", ["runner_chain.py", "--reunion", "R1", "--course", "C9", "--phase", "H5", "--budget", "12.34", "--source", "boturfers"])
    mock_run_chain = mocker.patch("src.hippique_orchestrator.runner_chain.run_chain", return_value={"status": "ok"})
    mock_print = mocker.patch("builtins.print")
    mock_json_dumps = mocker.patch("json.dumps", return_value='{"status": "ok"}')

    runner_chain.main()

    mock_run_chain.assert_called_once_with(reunion="R1", course="C9", phase="H5", budget=12.34, source="boturfers")
    mock_json_dumps.assert_called_once_with({"status": "ok"})
    mock_print.assert_called_once_with('{"status": "ok"}')