import pytest
from unittest.mock import patch, mock_open, call
from hippique_orchestrator import runner_chain
import datetime as dt
import json
from freezegun import freeze_time
from pathlib import Path
from hippique_orchestrator.validator_ev import ValidationError as ValidatorEvValidationError

@pytest.fixture
def mock_runner_dependencies(mocker):
    """Mocks all external dependencies for the modern runner_chain."""
    mocker.patch.object(runner_chain.ofz, 'fetch_race_snapshot', return_value={"runners": []})
    mocker.patch.object(runner_chain, 'upload_file', return_value=None)
    mocker.patch.object(runner_chain, 'simulate_ev_batch', return_value={})
    mocker.patch.object(runner_chain, 'validate_ev', return_value=True)
    mocker.patch('pathlib.Path.mkdir')
    mocker.patch('json.dump')
    # Let tests mock these as needed for fine-grained control
    mocker.patch('pathlib.Path.exists', return_value=True)
    mocker.patch('pathlib.Path.is_file', return_value=True)
    mocker.patch('pathlib.Path.open', mock_open())


def test_import_modern_runner():
    """A simple smoke test to ensure the modern runner_chain can be imported."""
    assert runner_chain is not None

def test_coerce_payload_raises_error_on_bad_data():
    """
    Tests that _coerce_payload raises PayloadValidationError for invalid data.
    """
    bad_data = {
        "id_course": "123",  # Too short
        "reunion": "R1",
        "course": "C1",
        "phase": "INVALID_PHASE",
        "start_time": "not-a-date",
        "budget": 0.5  # Too low
    }
    with pytest.raises(runner_chain.PayloadValidationError) as excinfo:
        runner_chain._coerce_payload(bad_data, context="test")
    
    error_str = str(excinfo.value)
    assert "id_course" in error_str
    assert "phase" in error_str
    assert "start_time" in error_str
    assert "budget" in error_str
    assert "test: " in error_str

def test_load_planning_raises_error_on_bad_data(mocker):
    """
    Tests that _load_planning raises ValueError if the planning file
    does not contain a list.
    """
    bad_planning_data = {"not": "a list"}
    mocker.patch('pathlib.Path.open', mock_open(read_data=json.dumps(bad_planning_data)))
    with pytest.raises(ValueError, match="Planning file must contain a list"):
        runner_chain._load_planning(Path("dummy_planning.json"))

def test_write_snapshot_handles_fetch_failure(mocker):
    """
    Tests that _write_snapshot correctly handles an exception from the fetcher,
    writing a 'no-data' status file.
    """
    mocker.patch('src.runner_chain.is_gcs_enabled', return_value=False)
    mocker.patch('pathlib.Path.mkdir')
    mocker.patch('pathlib.Path.open', mock_open())
    mock_fetch = mocker.patch.object(runner_chain.ofz, 'fetch_race_snapshot')
    mock_fetch.side_effect = Exception("Network Error")
    
    mock_json_dump = mocker.patch('json.dump')

    payload = runner_chain.RunnerPayload(
        id_course="123456",
        reunion="R1",
        course="C1",
        phase="H30",
        start_time=dt.datetime.now(),
        budget=5.0
    )
    
    runner_chain._write_snapshot(payload, "H30", Path("/fake/dir"))

    mock_json_dump.assert_called_once()
    written_payload = mock_json_dump.call_args.args[0]
    assert written_payload['status'] == 'no-data'
    assert written_payload['reason'] == 'Network Error'


def test_single_race_h30_writes_snapshot(mock_runner_dependencies, mocker):
    """
    Tests that a single-race invocation for H30 phase correctly triggers
    the snapshot writing process.
    """
    mocker.patch('src.runner_chain.is_gcs_enabled', return_value=False)
    start_time_str = dt.datetime.now().isoformat()
    argv = [
        'src/runner_chain.py',
        '--reunion', 'R1',
        '--course', 'C1',
        '--phase', 'H30',
        '--course-id', '123456',
        '--start-time', start_time_str,
        '--budget', '5.0'
    ]
    mocker.patch.object(runner_chain.sys, 'argv', argv)
    mock_write_snapshot = mocker.patch('src.runner_chain._write_snapshot')
    runner_chain.main()
    mock_write_snapshot.assert_called_once()
    payload, window, _ = mock_write_snapshot.call_args.args
    assert payload.reunion == 'R1'
    assert payload.course == 'C1'
    assert payload.phase == 'H30'
    assert window == 'H30'

def test_single_race_h5_writes_snapshot_and_analysis(mock_runner_dependencies, mocker):
    """
    Tests that a single-race invocation for H5 phase correctly triggers both
    snapshot and analysis writing processes.
    """
    mocker.patch('src.runner_chain.is_gcs_enabled', return_value=False)
    start_time_str = dt.datetime.now().isoformat()
    argv = [
        'src/runner_chain.py',
        '--reunion', 'R1',
        '--course', 'C2',
        '--phase', 'H5',
        '--course-id', '654321',
        '--start-time', start_time_str,
        '--budget', '7.5'
    ]
    mocker.patch.object(runner_chain.sys, 'argv', argv)
    mock_write_snapshot = mocker.patch('src.runner_chain._write_snapshot')
    mock_write_analysis = mocker.patch('src.runner_chain._write_analysis')
    runner_chain.main()
    mock_write_snapshot.assert_called_once()
    payload_snap, window_snap, _ = mock_write_snapshot.call_args.args
    assert payload_snap.race_id == 'R1C2'
    assert window_snap == 'H5'
    mock_write_analysis.assert_called_once()
    kwargs_analysis = mock_write_analysis.call_args.kwargs
    assert kwargs_analysis['budget'] == 7.5

def test_h5_analysis_skips_if_calibration_missing(mock_runner_dependencies, mocker):
    """
    Tests that H5 analysis writes an 'insufficient_data' status if the
    payout calibration file is missing.
    """
    mocker.patch('src.runner_chain.is_gcs_enabled', return_value=False)
    start_time_str = dt.datetime.now().isoformat()
    argv = [
        'src/runner_chain.py',
        '--reunion', 'R1',
        '--course', 'C5',
        '--phase', 'H5',
        '--course-id', '555555',
        '--start-time', start_time_str,
    ]
    mocker.patch.object(runner_chain.sys, 'argv', argv)
    
    mocker.patch('pathlib.Path.exists', return_value=False)
    mock_json_dump = mocker.patch('json.dump')
    
    runner_chain.main()

    assert mock_json_dump.call_count == 2
    analysis_payload = mock_json_dump.call_args.args[0]
    
    assert analysis_payload['status'] == 'insufficient_data'
    assert 'calibration_missing' in analysis_payload['notes']

def test_gcs_upload_is_called_when_enabled(mock_runner_dependencies, mocker):
    """
    Tests that upload_file is called for snapshot and analysis when GCS is enabled.
    """
    mocker.patch('src.runner_chain.USE_GCS', True)
    mock_upload = mocker.patch('src.runner_chain.upload_file')
    
    start_time_str = dt.datetime.now().isoformat()
    argv = [
        'src/runner_chain.py',
        '--reunion', 'R1',
        '--course', 'C6',
        '--phase', 'H5',
        '--course-id', '666666',
        '--start-time', start_time_str,
    ]
    mocker.patch.object(runner_chain.sys, 'argv', argv)
    
    runner_chain.main()

    assert mock_upload.call_count == 2
    
    # Check that it was called with the snapshot and analysis paths
    call_paths = [c.args[0] for c in mock_upload.call_args_list]
    assert any('snapshot_H5.json' in str(p) for p in call_paths)
    assert any('analysis.json' in str(p) for p in call_paths)


def test_single_race_result_phase_writes_excel_command(mock_runner_dependencies, mocker):
    """
    Tests that the RESULT phase triggers the Excel update command writing.
    """
    mocker.patch('src.runner_chain.is_gcs_enabled', return_value=False)
    start_time_str = dt.datetime.now().isoformat()
    argv = [
        'src/runner_chain.py',
        '--reunion', 'R4',
        '--course', 'C4',
        '--phase', 'RESULT',
        '--course-id', '444444',
        '--start-time', start_time_str,
        '--budget', '5.0'
    ]
    mocker.patch.object(runner_chain.sys, 'argv', argv)
    
    mock_write_excel_cmd = mocker.patch('src.runner_chain._write_excel_update_command')
    
    runner_chain.main()

    mock_write_excel_cmd.assert_called_once()
    call_kwargs = mock_write_excel_cmd.call_args.kwargs
    assert call_kwargs['arrivee_path'].name == 'arrivee_officielle.json'

def test_result_phase_handles_missing_arrivee(mock_runner_dependencies, mocker):
    """
    Tests that the RESULT phase correctly handles a missing arrivee_officielle.json
    by writing a 'missing' status payload and a CSV.
    """
    mocker.patch('src.runner_chain.is_gcs_enabled', return_value=False)
    start_time_str = dt.datetime.now().isoformat()
    argv = [
        'src/runner_chain.py',
        '--reunion', 'R5',
        '--course', 'C1',
        '--phase', 'RESULT',
        '--course-id', '555555',
        '--start-time', start_time_str,
        '--budget', '5.0'
    ]
    mocker.patch.object(runner_chain.sys, 'argv', argv)
    
    # Mock the specific Path object for arrivee_officielle.json
    mock_arrivee_path = mocker.Mock(spec=Path)
    mock_arrivee_path.exists.return_value = False
    mock_arrivee_path.name = 'arrivee_officielle.json'
    mock_arrivee_path.__truediv__ = mocker.Mock(return_value=mock_arrivee_path) # Allow chaining
    mock_arrivee_path.open = mock_open() # Ensure open works for this mock
    
    # Mock the Path object that represents the race directory
    mock_race_dir = mocker.Mock(spec=Path)
    mock_race_dir.__truediv__ = mocker.Mock(return_value=mock_arrivee_path)
    mock_race_dir.exists.return_value = True # Assume race_dir exists
    mock_race_dir.name = 'R5C1' # For debugging/clarity
    mock_race_dir.open = mock_open() # Ensure open works for this mock
    
    # Mock the Path object that represents the analysis directory
    mock_analysis_dir = mocker.Mock(spec=Path)
    mock_analysis_dir.__truediv__ = mocker.Mock(return_value=mock_race_dir)
    mock_analysis_dir.exists.return_value = True # Assume analysis_dir exists
    mock_analysis_dir.name = 'analyses' # For debugging/clarity
    mock_analysis_dir.open = mock_open() # Ensure open works for this mock
    
    # Store the original Path constructor from pathlib
    original_path_constructor = Path
    
    def path_side_effect(*args, **kwargs):
        path_str = str(args[0]) if args else ''
        
        if path_str == 'data/analyses':
            return mock_analysis_dir
        elif 'arrivee_officielle.json' in path_str:
            return mock_arrivee_path
        elif 'R5C1' in path_str: # This is for the race_dir
            return mock_race_dir
        else:
            # For any other path, return a *real* Path object, but then mock its methods
            # This is the crucial part: we need a real Path object for pytest,
            # but a mockable one for our test.
            real_path_instance = original_path_constructor(*args, **kwargs)
            
            # Now, create a mock *around* this real Path instance
            mock_real_path = mocker.Mock(wraps=real_path_instance)
            mock_real_path.exists.return_value = True # Default to existing
            # Mock __truediv__ to return a mock that wraps the result of real __truediv__
            mock_real_path.__truediv__ = mocker.Mock(side_effect=lambda other: mocker.Mock(wraps=real_path_instance / other))
            mock_real_path.open = mock_open() # Ensure open works for this mock
            return mock_real_path

    # Patch the Path object *within* the runner_chain module
    mocker.patch('src.runner_chain.Path', side_effect=path_side_effect)
    
    mock_write_json_file = mocker.patch('src.runner_chain._write_json_file')
    mock_write_text_file = mocker.patch('src.runner_chain._write_text_file')

    runner_chain.main()

    # Assert _write_json_file was called with the missing status
    mock_write_json_file.assert_called_once()
    json_call_args, json_call_kwargs = mock_write_json_file.call_args
    assert json_call_args[0].name == 'arrivee_officielle.json'
    assert json_call_args[1]['status'] == 'missing'
    assert json_call_args[1]['R'] == 'R5'
    assert json_call_args[1]['C'] == 'C1'

    # Assert _write_text_file was called with the CSV content
    mock_write_text_file.assert_called_once()
    text_call_args, text_call_kwargs = mock_write_text_file.call_args
    assert text_call_args[0].name == 'arrivee_officielle.json'
    assert 'status;R;C;date' in text_call_args[1]
    assert 'missing;R5;C1;' in text_call_args[1]


def test_write_excel_update_command_generates_correct_command(mock_runner_dependencies, mocker):
    """
    Tests that _write_excel_update_command generates the correct command string
    and writes it to the specified file.
    """
    mocker.patch('src.runner_chain.is_gcs_enabled', return_value=False)
    mock_write_text_file = mocker.patch('src.runner_chain._write_text_file')

    mock_race_dir = mocker.Mock(spec=Path)
    mock_race_dir.name = 'R1C1'
    mock_race_dir.as_posix.return_value = 'data/analyses/R1C1'
    mock_race_dir.__truediv__ = mocker.Mock(side_effect=lambda other: mocker.Mock(spec=Path, name=str(other), as_posix=mocker.Mock(return_value=f"{mock_race_dir.as_posix.return_value}/{other}"), exists=mocker.Mock(return_value=False))) # Ensure exists() returns False for candidates

    mock_arrivee_path = mocker.Mock(spec=Path)
    mock_arrivee_path.name = 'arrivee_officielle.json'
    mock_arrivee_path.as_posix.return_value = 'data/analyses/R1C1/arrivee_officielle.json'

    mock_excel_path = mocker.Mock(spec=Path)
    mock_excel_path.name = 'planning.xlsx'
    mock_excel_path.as_posix.return_value = 'excel/planning.xlsx'

    mock_tickets_path = mocker.Mock(spec=Path)
    mock_tickets_path.name = 'tickets.json'
    mock_tickets_path.as_posix.return_value = 'data/analyses/R1C1/tickets.json'

    runner_chain._write_excel_update_command(
        mock_race_dir,
        arrivee_path=mock_arrivee_path,
        tickets_path=mock_tickets_path, # Provide tickets_path
        excel_path=mock_excel_path.as_posix()
    )

    mock_write_text_file.assert_called_once()
    call_args, call_kwargs = mock_write_text_file.call_args
    
    expected_command = (
        "python update_excel_with_results.py "
        f'--excel "{mock_excel_path.as_posix()}" ' 
        f'--arrivee "{mock_arrivee_path.as_posix()}" ' 
        f'--tickets "{mock_tickets_path.as_posix()}"\n'
    )
    assert call_args[1].strip() == expected_command.strip()
    assert call_args[0].as_posix() == f"{mock_race_dir.as_posix.return_value}/cmd_update_excel.txt"


def test_write_excel_update_command_finds_tickets_file(mock_runner_dependencies, mocker):
    """
    Tests that _write_excel_update_command correctly finds a tickets file
    when tickets_path is not provided.
    """
    mocker.patch('src.runner_chain.is_gcs_enabled', return_value=False)
    mock_write_text_file = mocker.patch('src.runner_chain._write_text_file')

    # Mock Path objects for race_dir, arrivee_path, excel_path
    mock_race_dir = mocker.Mock(spec=Path)
    mock_race_dir.name = 'R1C1'
    mock_race_dir.as_posix.return_value = 'data/analyses/R1C1'
    
    # Configure __truediv__ to return mocks with specific exists() behavior
    def race_dir_truediv_side_effect(other):
        mock_path_child = mocker.Mock(spec=Path)
        mock_path_child.name = str(other)
        mock_path_child.as_posix.return_value = f"{mock_race_dir.as_posix.return_value}/{other}"
        mock_path_child.__truediv__ = mocker.Mock(return_value=mock_path_child) # For chaining
        mock_path_child.open = mock_open() # For any open calls
        
        if other == "tickets.json":
            mock_path_child.exists.return_value = False
        elif other == "p_finale.json":
            mock_path_child.exists.return_value = False
        elif other == "analysis.json":
            mock_path_child.exists.return_value = True # This one exists
        else:
            mock_path_child.exists.return_value = False # Others don't
        return mock_path_child
        
    mock_race_dir.__truediv__ = mocker.Mock(side_effect=race_dir_truediv_side_effect)

    mock_arrivee_path = mocker.Mock(spec=Path)
    mock_arrivee_path.name = 'arrivee_officielle.json'
    mock_arrivee_path.as_posix.return_value = 'data/analyses/R1C1/arrivee_officielle.json'

    mock_excel_path = mocker.Mock(spec=Path)
    mock_excel_path.name = 'planning.xlsx'
    mock_excel_path.as_posix.return_value = 'excel/planning.xlsx'

    # Call _write_excel_update_command without tickets_path
    runner_chain._write_excel_update_command(
        mock_race_dir,
        arrivee_path=mock_arrivee_path,
        excel_path=mock_excel_path.as_posix()
    )

    mock_write_text_file.assert_called_once()
    call_args, call_kwargs = mock_write_text_file.call_args
    
    expected_command = (
        "python update_excel_with_results.py "
        f'--excel "{mock_excel_path.as_posix()}" ' 
        f'--arrivee "{mock_arrivee_path.as_posix()}" ' 
        f'--tickets "{mock_race_dir.as_posix.return_value}/analysis.json"\n' # Expect analysis.json
    )
    assert call_args[1].strip() == expected_command.strip()
    assert call_args[0].as_posix() == f"{mock_race_dir.as_posix.return_value}/cmd_update_excel.txt"


def test_write_excel_update_command_skips_if_no_tickets_file(mock_runner_dependencies, mocker):
    """
    Tests that _write_excel_update_command skips writing the command
    if no tickets file is found.
    """
    mocker.patch('src.runner_chain.is_gcs_enabled', return_value=False)
    mock_write_text_file = mocker.patch('src.runner_chain._write_text_file')
    mock_logger_warning = mocker.patch('src.runner_chain.logger.warning')

    # Mock Path objects for race_dir, arrivee_path, excel_path
    mock_race_dir = mocker.Mock(spec=Path)
    mock_race_dir.name = 'R1C1'
    mock_race_dir.as_posix.return_value = 'data/analyses/R1C1'
    
    # Configure __truediv__ to return mocks with specific exists() behavior
    def race_dir_truediv_side_effect(other):
        mock_path_child = mocker.Mock(spec=Path)
        mock_path_child.name = str(other)
        mock_path_child.as_posix.return_value = f"{mock_race_dir.as_posix.return_value}/{other}"
        mock_path_child.__truediv__ = mocker.Mock(return_value=mock_path_child) # For chaining
        mock_path_child.open = mock_open() # For any open calls
        mock_path_child.exists.return_value = False # All candidates don't exist
        return mock_path_child
        
    mock_race_dir.__truediv__ = mocker.Mock(side_effect=race_dir_truediv_side_effect)

    mock_arrivee_path = mocker.Mock(spec=Path)
    mock_arrivee_path.name = 'arrivee_officielle.json'
    mock_arrivee_path.as_posix.return_value = 'data/analyses/R1C1/arrivee_officielle.json'

    mock_excel_path = mocker.Mock(spec=Path)
    mock_excel_path.name = 'planning.xlsx'
    mock_excel_path.as_posix.return_value = 'excel/planning.xlsx'

    # Call _write_excel_update_command without tickets_path
    runner_chain._write_excel_update_command(
        mock_race_dir,
        arrivee_path=mock_arrivee_path,
        excel_path=mock_excel_path.as_posix()
    )

    mock_write_text_file.assert_not_called()
    mock_logger_warning.assert_called_once()
    assert "No tickets file found" in mock_logger_warning.call_args[0][0]


def test_load_sources_config_handles_missing_file(mock_runner_dependencies, mocker):
    """
    Tests that _load_sources_config returns an empty dictionary when the
    sources config file is missing.
    """
    # Mock Path.is_file to return False for the config file
    mocker.patch('pathlib.Path.is_file', return_value=False)
    
    # Mock os.getenv to ensure no default path is set
    mocker.patch('os.getenv', return_value=None)

    config = runner_chain._load_sources_config()
    assert config == {}


def test_load_sources_config_handles_invalid_yaml(mock_runner_dependencies, mocker):
    """
    Tests that _load_sources_config returns an empty dictionary when the
    sources config file contains invalid YAML.
    """
    # Mock Path.is_file to return True for the config file
    mocker.patch('pathlib.Path.is_file', return_value=True)
    
    # Mock Path.open to return invalid YAML content
    mocker.patch('pathlib.Path.open', mock_open(read_data="invalid: -"))
    
    # Mock yaml.safe_load to raise an exception for invalid YAML
    mocker.patch('yaml.safe_load', side_effect=runner_chain.yaml.YAMLError("Invalid YAML"))

    config = runner_chain._load_sources_config()
    assert config == {}

def test_planning_mode_triggers_correct_phase(mock_runner_dependencies, mocker):
    """
    Tests that planning mode correctly identifies and triggers the right phase
    based on the time window.
    """
    mocker.patch('src.runner_chain.is_gcs_enabled', return_value=False)
    race_start_time = dt.datetime.now() + dt.timedelta(minutes=30)
    planning_data = [{
        "id_course": "789101",
        "reunion": "R3",
        "course": "C3",
        "start_time": race_start_time.isoformat(),
        "budget": 9.99
    }]
    
    mocker.patch('pathlib.Path.open', mock_open(read_data=json.dumps(planning_data)))
    
    argv = [
        'src/runner_chain.py',
        '--planning', 'dummy_planning.json',
    ]
    mocker.patch.object(runner_chain.sys, 'argv', argv)
    mock_trigger_phase = mocker.patch('src.runner_chain._trigger_phase')

    # 1. Test H-30 window
    with freeze_time(race_start_time - dt.timedelta(minutes=30)):
        runner_chain.main()
    
    mock_trigger_phase.assert_called_once()
    payload_h30 = mock_trigger_phase.call_args.args[0]
    assert payload_h30.phase == 'H30'
    assert payload_h30.race_id == 'R3C3'

    # Reset mock for the next call
    mock_trigger_phase.reset_mock()

    # 2. Test H-5 window
    with freeze_time(race_start_time - dt.timedelta(minutes=5)):
        runner_chain.main()

    mock_trigger_phase.assert_called_once()
    payload_h5 = mock_trigger_phase.call_args.args[0]
    assert payload_h5.phase == 'H5'
    assert payload_h5.race_id == 'R3C3'
    assert payload_h5.budget == 9.99

def test_write_json_file_creates_file_and_parents(mock_runner_dependencies, mocker):
    """
    Tests that _write_json_file creates parent directories and writes the payload.
    """
    mock_path = mocker.Mock(spec=Path)
    mock_path.parent = mocker.Mock(spec=Path)
    mock_path.parent.mkdir = mocker.Mock()
    mock_path.write_text = mocker.Mock()
    
    payload = {"key": "value"}
    runner_chain._write_json_file(mock_path, payload)
    
    mock_path.parent.mkdir.assert_called_once_with(parents=True, exist_ok=True)
    mock_path.write_text.assert_called_once_with(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def test_write_text_file_creates_file_and_parents(mock_runner_dependencies, mocker):
    """
    Tests that _write_text_file creates parent directories and writes the content.
    """
    mock_path = mocker.Mock(spec=Path)
    mock_path.parent = mocker.Mock(spec=Path)
    mock_path.parent.mkdir = mocker.Mock()
    mock_path.write_text = mocker.Mock()
    
    content = "some text content"
    runner_chain._write_text_file(mock_path, content)
    
    mock_path.parent.mkdir.assert_called_once_with(parents=True, exist_ok=True)
    mock_path.write_text.assert_called_once_with(content, encoding="utf-8")


def test_write_snapshot_handles_gcs_upload_error(mock_runner_dependencies, mocker):
    """
    Tests that _write_snapshot logs a warning when GCS upload fails.
    """
    mocker.patch('src.runner_chain.USE_GCS', True)
    mock_upload = mocker.patch('src.runner_chain.upload_file', side_effect=OSError("GCS Error"))
    mock_logger_warning = mocker.patch('src.runner_chain.logger.warning')

    payload = runner_chain.RunnerPayload(
        id_course="123456",
        reunion="R1",
        course="C1",
        phase="H30",
        start_time=dt.datetime.now(),
        budget=5.0
    )
    
    mock_base_path = mocker.Mock(spec=Path)
    mock_base_path.mkdir = mocker.Mock()
    
    def base_truediv_side_effect(other):
        mock_child_path = mocker.Mock(spec=Path)
        mock_child_path.name = str(other)
        mock_child_path.as_posix.return_value = f"/fake/dir/{other}"
        mock_child_path.mkdir = mocker.Mock() # Ensure mkdir works on this child path
        mock_child_path.open = mock_open() # Add this line
        
        # This is the crucial part: mock __truediv__ for the child path as well
        mock_child_path.__truediv__ = mocker.Mock(side_effect=lambda other_child: mocker.Mock(spec=Path, name=str(other_child), as_posix=mocker.Mock(return_value=f"{mock_child_path.as_posix.return_value}/{other_child}"), open=mock_open())) # Add open to nested mock
        
        return mock_child_path        
    mock_base_path.__truediv__ = mocker.Mock(side_effect=base_truediv_side_effect)
    
    runner_chain._write_snapshot(payload, "H30", mock_base_path)

    mock_upload.assert_called_once()
    mock_logger_warning.assert_called_once()
    assert "Skipping cloud upload" in mock_logger_warning.call_args[0][0]


def test_write_analysis_handles_gcs_upload_error(mock_runner_dependencies, mocker):
    """
    Tests that _write_analysis logs a warning when GCS upload fails.
    """
    mocker.patch('src.runner_chain.USE_GCS', True)
    mock_upload = mocker.patch('src.runner_chain.upload_file', side_effect=OSError("GCS Error"))
    mock_logger_warning = mocker.patch('src.runner_chain.logger.warning')

    mock_base_path = mocker.Mock(spec=Path)
    mock_base_path.mkdir = mocker.Mock()
    
    def base_truediv_side_effect(other):
        mock_child_path = mocker.Mock(spec=Path)
        mock_child_path.name = str(other)
        mock_child_path.as_posix.return_value = f"/fake/dir/{other}"
        mock_child_path.mkdir = mocker.Mock()
        mock_child_path.open = mock_open()
        mock_child_path.__truediv__ = mocker.Mock(side_effect=lambda other_child: mocker.Mock(spec=Path, name=str(other_child), as_posix=mocker.Mock(return_value=f"{mock_child_path.as_posix.return_value}/{other_child}"), open=mock_open()))
        return mock_child_path
        
    mock_base_path.__truediv__ = mocker.Mock(side_effect=base_truediv_side_effect)

    runner_chain._write_analysis(
        "R1C1",
        mock_base_path,
        budget=5.0,
        ev_min=0.35,
        roi_min=0.25,
        mode="h5",
        calibration=Path("config/payout_calibration.yaml"),
        calibration_available=True
    )

    mock_upload.assert_called_once()
    mock_logger_warning.assert_called_once()
    assert "Skipping cloud upload" in mock_logger_warning.call_args[0][0]


def test_write_analysis_handles_validation_error(mock_runner_dependencies, mocker):
    """
    Tests that _write_analysis returns early when validate_ev raises a ValidationError.
    """
    mock_simulate_ev_batch = mocker.patch('src.runner_chain.simulate_ev_batch', return_value={"ev": 0.1, "roi": 0.05})
    mock_validate_ev = mocker.patch('src.runner_chain.validate_ev', side_effect=ValidatorEvValidationError("Validation failed"))
    mock_json_dump = mocker.patch('json.dump')
    mock_upload = mocker.patch('src.runner_chain.upload_file')

    mock_base_path = mocker.Mock(spec=Path)
    mock_base_path.mkdir = mocker.Mock()
    
    def base_truediv_side_effect(other):
        mock_child_path = mocker.Mock(spec=Path)
        mock_child_path.name = str(other)
        mock_child_path.as_posix.return_value = f"/fake/dir/{other}"
        mock_child_path.mkdir = mocker.Mock()
        mock_child_path.open = mock_open()
        mock_child_path.__truediv__ = mocker.Mock(side_effect=lambda other_child: mocker.Mock(spec=Path, name=str(other_child), as_posix=mocker.Mock(return_value=f"{mock_child_path.as_posix.return_value}/{other_child}"), open=mock_open()))
        return mock_child_path
        
    mock_base_path.__truediv__ = mocker.Mock(side_effect=base_truediv_side_effect)

    runner_chain._write_analysis(
        "R1C1",
        mock_base_path,
        budget=5.0,
        ev_min=0.35,
        roi_min=0.25,
        mode="h5",
        calibration=Path("config/payout_calibration.yaml"),
        calibration_available=True
    )

    mock_json_dump.assert_not_called()


def test_write_analysis_skips_if_calibration_not_available(mock_runner_dependencies, mocker):
    """
    Tests that _write_analysis skips EV simulation and writes an insufficient_data
    payload if calibration is not available.
    """
    mocker.patch('src.runner_chain.USE_GCS', True)
    mock_simulate_ev_batch = mocker.patch('src.runner_chain.simulate_ev_batch')
    mock_validate_ev = mocker.patch('src.runner_chain.validate_ev')
    mock_json_dump = mocker.patch('json.dump')
    mock_upload = mocker.patch('src.runner_chain.upload_file')
    
    mock_base_path = mocker.Mock(spec=Path)
    mock_base_path.mkdir = mocker.Mock()
    
    def base_truediv_side_effect(other):
        mock_child_path = mocker.Mock(spec=Path)
        mock_child_path.name = str(other)
        mock_child_path.as_posix.return_value = f"/fake/dir/{other}"
        mock_child_path.mkdir = mocker.Mock()
        mock_child_path.open = mock_open()
        mock_child_path.__truediv__ = mocker.Mock(side_effect=lambda other_child: mocker.Mock(spec=Path, name=str(other_child), as_posix=mocker.Mock(return_value=f"{mock_child_path.as_posix.return_value}/{other_child}"), open=mock_open()))
        return mock_child_path
        
    mock_base_path.__truediv__ = mocker.Mock(side_effect=base_truediv_side_effect)

    # Mock the calibration path to not exist
    mock_calibration_path = mocker.Mock(spec=Path)
    mock_calibration_path.exists.return_value = False

    runner_chain._write_analysis(
        "R1C1",
        mock_base_path,
        budget=5.0,
        ev_min=0.35,
        roi_min=0.25,
        mode="h5",
        calibration=mock_calibration_path, # Use the mocked calibration path
        calibration_available=False # Calibration not available
    )

    mock_simulate_ev_batch.assert_not_called()
    mock_validate_ev.assert_not_called()
    mock_json_dump.assert_called_once()
    
    payload_dumped = mock_json_dump.call_args.args[0]
    assert payload_dumped['status'] == 'insufficient_data'
    assert 'calibration_missing' in payload_dumped['notes']
    
    # Check GCS upload is called for the insufficient_data payload
    mock_upload.assert_called_once()


def test_planning_mode_triggers_correct_phase(mock_runner_dependencies, mocker):
    """
    Tests that planning mode correctly identifies and triggers the right phase
    based on the time window.
    """
    mocker.patch('src.runner_chain.is_gcs_enabled', return_value=False)
    race_start_time = dt.datetime.now() + dt.timedelta(minutes=30)
    planning_data = [{
        "id_course": "789101",
        "reunion": "R3",
        "course": "C3",
        "start_time": race_start_time.isoformat(),
        "budget": 9.99
    }]
    
    mocker.patch('pathlib.Path.open', mock_open(read_data=json.dumps(planning_data)))
    
    argv = [
        'src/runner_chain.py',
        '--planning', 'dummy_planning.json',
    ]
    mocker.patch.object(runner_chain.sys, 'argv', argv)
    mock_trigger_phase = mocker.patch('src.runner_chain._trigger_phase')

    # 1. Test H-30 window
    with freeze_time(race_start_time - dt.timedelta(minutes=30)):
        runner_chain.main()
    
    mock_trigger_phase.assert_called_once()
    payload_h30 = mock_trigger_phase.call_args.args[0]
    assert payload_h30.phase == 'H30'
    assert payload_h30.race_id == 'R3C3'

    # Reset mock for the next call
    mock_trigger_phase.reset_mock()

    # 2. Test H-5 window
    with freeze_time(race_start_time - dt.timedelta(minutes=5)):
        runner_chain.main()

    mock_trigger_phase.assert_called_once()
    payload_h5 = mock_trigger_phase.call_args.args[0]
    assert payload_h5.phase == 'H5'
    assert payload_h5.race_id == 'R3C3'
    assert payload_h5.budget == 9.99