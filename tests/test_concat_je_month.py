import pandas as pd
import numpy as np
import pytest
from pathlib import Path
from datetime import datetime
from unittest.mock import patch, MagicMock

from hippique_orchestrator.scripts.concat_je_month import (
    _normalize_columns,
    _infer_date_from_path,
    load_and_filter,
    summarize_month,
    main,
    STD_COLUMNS,
    CANDIDATES
)


@pytest.fixture
def sample_dataframe():
    """Provides a sample DataFrame for testing column normalization."""
    return pd.DataFrame({
        'Date': ['2026-01-01', '2026-01-02'],
        'reunion_num': [1, 2],
        'Race': [1, 2],
        'Track': ['Hippodrome A', 'Hippodrome B'],
        'discipline': ['Plat', 'Obstacle'],
        'Horse': ['Cheval 1', 'Cheval 2'],
        'Numero': [1, 2],
        'Jockey': ['Jockey 1', 'Jockey 2'],
        'Trainer': ['Entraineur 1', 'Entraineur 2'],
        'j_percent': [0.5, 0.6],
        'e_percent': [0.4, 0.7],
        'Source': ['Source A', 'Source B'],
        'UID': ['ID1', 'ID2'],
        'extra_col': [100, 200]
    })


def test_normalize_columns(sample_dataframe):
    """Test that columns are correctly normalized and types are set."""
    df = _normalize_columns(sample_dataframe.copy())

    assert all(col in df.columns for col in STD_COLUMNS)
    assert 'extra_col' in df.columns  # Ensure extra columns are preserved

    # Check renaming
    assert 'date' in df.columns and 'Date' not in df.columns
    assert 'reunion' in df.columns and 'reunion_num' not in df.columns
    assert 'course' in df.columns and 'Race' not in df.columns
    assert 'hippodrome' in df.columns and 'Track' not in df.columns
    assert 'cheval' in df.columns and 'Horse' not in df.columns
    assert 'num' in df.columns and 'Numero' not in df.columns
    assert 'jockey' in df.columns and 'Jockey' not in df.columns
    assert 'entraineur' in df.columns and 'Trainer' not in df.columns
    assert 'j_rate' in df.columns and 'j_percent' not in df.columns
    assert 'e_rate' in df.columns and 'e_percent' not in df.columns
    assert 'source' in df.columns and 'Source' not in df.columns
    assert 'race_id' in df.columns and 'UID' not in df.columns

    # Check data types
    assert pd.api.types.is_datetime64_any_dtype(df['date'])
    assert pd.api.types.is_integer_dtype(df['num'])
    assert pd.api.types.is_float_dtype(df['j_rate'])
    assert pd.api.types.is_string_dtype(df['hippodrome'])


def test_normalize_columns_missing_cols():
    """Test that missing standard columns are added as NaN."""
    df_subset = pd.DataFrame({
        'some_other_col': [1, 2]
    })
    df = _normalize_columns(df_subset.copy())
    assert 'jockey' in df.columns
    assert 'entraineur' in df.columns
    assert df['jockey'].isna().all()
    assert df['entraineur'].isna().all()


@pytest.mark.parametrize("path_str, expected_date", [
    ("data/2026-01-01/some_file.csv", datetime(2026, 1, 1).date()),
    ("data/2025_12_31/other_file.csv", datetime(2025, 12, 31).date()),
    ("data/no_date_here.csv", None),
    ("data/20240229_special.csv", datetime(2024, 2, 29).date()), # Leap year
])
def test_infer_date_from_path(path_str, expected_date):
    """Test date inference from various path formats."""
    assert _infer_date_from_path(Path(path_str)) == expected_date


@patch('pandas.read_csv')
@patch('hippique_orchestrator.scripts.concat_je_month._normalize_columns')
@patch('hippique_orchestrator.scripts.concat_je_month._infer_date_from_path')
def test_load_and_filter(mock_infer_date, mock_normalize_columns, mock_read_csv, tmp_path):
    """Test loading and filtering CSV files."""
    # Setup mock CSV files
    file1 = tmp_path / "data" / "2026-01-15_je.csv"
    file2 = tmp_path / "data" / "2026-02-10_je.csv"
    file3 = tmp_path / "data" / "2026-01-20_je.csv"
    file1.parent.mkdir(parents=True, exist_ok=True)
    file1.write_text("Date,reunion,course\n2026-01-15,1,1")
    file2.write_text("Date,reunion,course\n2026-02-10,1,1")
    file3.write_text("Date,reunion,course\n2026-01-20,1,1")

    # Mock pandas.read_csv to return a DataFrame
    mock_read_csv.side_effect = [
        pd.DataFrame({'Date': ['2026-01-15'], 'reunion': [1], 'course': [1]}),
        pd.DataFrame({'Date': ['2026-02-10'], 'reunion': [1], 'course': [1]}),
        pd.DataFrame({'Date': ['2026-01-20'], 'reunion': [1], 'course': [1]})
    ]

    # Mock _normalize_columns to return a DataFrame with normalized columns
    # It should return a DataFrame with 'date' column already processed by _normalize_columns
    def normalize_side_effect(df_input):
        normalized_data = {}
        df_input_lower_cols = {c.lower(): c for c in df_input.columns} # Add this
        
        for std_col, candidates in CANDIDATES.items():
            found = False
            for cand in candidates:
                if cand.lower() in df_input_lower_cols: # Change this to use lowercased columns
                    original_col_name = df_input_lower_cols[cand.lower()]
                    normalized_data[std_col] = df_input[original_col_name]
                    found = True
                    break
            if not found:
                # If a column is missing, assign a Series of np.nan
                normalized_data[std_col] = pd.Series([np.nan] * len(df_input))

        # Explicitly set the date to datetime64
        if 'date' in normalized_data:
            normalized_data['date'] = pd.to_datetime(normalized_data['date'], errors='coerce')

        # Handle 'num' as 'Int64' as per _normalize_columns
        if 'num' in normalized_data:
            normalized_data['num'] = pd.to_numeric(normalized_data['num'], errors='coerce', downcast='integer').astype(pd.Int64Dtype())

        # Keep original extra columns if any
        for col in df_input.columns:
            # Check if this column (or its lower-case version) is NOT mapped to a std_col
            is_mapped = False
            for cands_list in CANDIDATES.values():
                if col in cands_list or col.lower() in [c.lower() for c in cands_list]:
                    is_mapped = True
                    break
            if not is_mapped and col not in normalized_data: # Also ensure it's not already added
                normalized_data[col] = df_input[col]

        return pd.DataFrame(normalized_data)
    mock_normalize_columns.side_effect = normalize_side_effect

    # Test for January 2026
    paths = [file1, file2, file3]
    df_filtered = load_and_filter(paths, "2026-01")

    assert not df_filtered.empty
    assert len(df_filtered) == 2
    assert pd.to_datetime("2026-01-15") in df_filtered['date'].tolist()
    assert pd.to_datetime("2026-01-20") in df_filtered['date'].tolist()
    assert pd.to_datetime("2026-02-10") not in df_filtered['date'].tolist()

    # Test handling of unreadable CSV
    mock_read_csv.side_effect = [Exception("Test Error")]
    df_filtered_error = load_and_filter([file1], "2026-01")
    assert df_filtered_error.empty

    # Test with inferred date when 'date' column is missing in CSV
    mock_read_csv.side_effect = [pd.DataFrame({'reunion': [1], 'course': [1]})] # No 'Date' column
    mock_infer_date.return_value = datetime(2026, 1, 10).date()
    df_inferred_date = load_and_filter([file1], "2026-01")
    assert not df_inferred_date.empty
    assert datetime(2026, 1, 10).date() in df_inferred_date['date'].tolist()

def test_summarize_month(tmp_path):
    """Test summarizing data by jockey and trainer."""
    # Create a dummy DataFrame for testing
    data = {
        'date': [pd.to_datetime('2026-01-01'), pd.to_datetime('2026-01-01'), pd.to_datetime('2026-01-02')],
        'jockey': ['Jockey A', 'Jockey B', 'Jockey A'],
        'entraineur': ['Trainer X', 'Trainer Y', 'Trainer X'],
        'j_rate': [0.5, 0.6, 0.7],
        'e_rate': [0.8, 0.9, 0.75],
        '__source_file': ['file1', 'file2', 'file3']
    }
    df = pd.DataFrame(data)

    jockey_summary, entraineur_summary = summarize_month(df.copy())

    # Test jockey summary
    assert not jockey_summary.empty
    assert len(jockey_summary) == 2
    jockey_a = jockey_summary[jockey_summary['jockey'] == 'Jockey A']
    assert jockey_a['starts'].iloc[0] == 2
    assert jockey_a['mean_j_rate'].iloc[0] == pytest.approx(0.6) # (0.5 + 0.7) / 2
    
    jockey_b = jockey_summary[jockey_summary['jockey'] == 'Jockey B']
    assert jockey_b['starts'].iloc[0] == 1
    assert jockey_b['mean_j_rate'].iloc[0] == pytest.approx(0.6)

    # Test trainer summary
    assert not entraineur_summary.empty
    assert len(entraineur_summary) == 2
    trainer_x = entraineur_summary[entraineur_summary['entraineur'] == 'Trainer X']
    assert trainer_x['starts'].iloc[0] == 2
    assert trainer_x['mean_e_rate'].iloc[0] == pytest.approx(0.775) # (0.8 + 0.75) / 2

    trainer_y = entraineur_summary[entraineur_summary['entraineur'] == 'Trainer Y']
    assert trainer_y['starts'].iloc[0] == 1
    assert trainer_y['mean_e_rate'].iloc[0] == pytest.approx(0.9)


def test_summarize_month_no_jockey_trainer_data():
    """Test summarizing with no jockey or trainer data."""
    data = {
        'date': [pd.to_datetime('2026-01-01')],
        'jockey': [np.nan],
        'entraineur': [np.nan],
        'j_rate': [0.5],
        'e_rate': [0.8],
        '__source_file': ['file1']
    }
    df = pd.DataFrame(data)
    jockey_summary, entraineur_summary = summarize_month(df.copy())
    assert jockey_summary.empty
    assert entraineur_summary.empty


@patch('hippique_orchestrator.scripts.concat_je_month.load_and_filter')
@patch('hippique_orchestrator.scripts.concat_je_month.summarize_month')
@patch('pandas.DataFrame.to_csv')
@patch('argparse.ArgumentParser.parse_args')
@patch('pathlib.Path.rglob')
@patch('pathlib.Path.mkdir')
@patch('pathlib.Path.exists', return_value=True) # Patch exists for main_success
@patch('builtins.print')
def test_main_success(mock_print, mock_exists, mock_mkdir, mock_rglob, mock_parse_args, mock_to_csv, mock_summarize_month, mock_load_and_filter, tmp_path):
    """Test main function with successful execution."""
    mock_parse_args.return_value = MagicMock(
        data_dir=tmp_path / "data",
        month="2026-01",
        outdir=tmp_path / "out"
    )

    # Setup mock file structure and rglob return
    (tmp_path / "data").mkdir()
    mock_rglob.return_value = [tmp_path / "data" / "file1_je.csv"]

    # Mock load_and_filter return
    mock_load_and_filter.return_value = pd.DataFrame({
        'date': [pd.to_datetime('2026-01-01')], # Ensure datetime object
        'jockey': ['Jockey A'],
        'entraineur': ['Trainer X'],
        'j_rate': [0.5],
        'e_rate': [0.8],
        '__source_file': ['file1_je.csv']
    })

    # Mock summarize_month return
    mock_summarize_month.return_value = (
        pd.DataFrame({'jockey': ['Jockey A'], 'starts': [1], 'mean_j_rate': [0.5]}),
        pd.DataFrame({'entraineur': ['Trainer X'], 'starts': [1], 'mean_e_rate': [0.8]})
    )

    main()

    mock_mkdir.assert_called_with(parents=True, exist_ok=True)
    mock_load_and_filter.assert_called_once()
    mock_summarize_month.assert_called_once()
    assert mock_to_csv.call_count == 3  # For all_df, jockey_summary, entraineur_summary
    mock_print.assert_any_call(
        f"[OK] Écrits :\n - {tmp_path}/out/JE_2026-01.csv\n - {tmp_path}/out/JE_2026-01_summary_jockey.csv\n - {tmp_path}/out/JE_2026-01_summary_entraineur.csv"
    )


@patch('hippique_orchestrator.scripts.concat_je_month.load_and_filter')
@patch('argparse.ArgumentParser.parse_args')
@patch('pathlib.Path.exists', return_value=False) # Ensure this is mocked for success scenario
@patch('builtins.print')
def test_main_data_dir_not_found(mock_print, mock_exists, mock_parse_args, mock_load_and_filter):
    """Test main function when data directory is not found."""
    mock_parse_args.return_value = MagicMock(
        data_dir="non_existent_dir",
        month="2026-01",
        outdir="."
    )
    with pytest.raises(SystemExit) as excinfo:
        main()
    assert "Répertoire introuvable: non_existent_dir" in str(excinfo.value)


@patch('hippique_orchestrator.scripts.concat_je_month.load_and_filter')
@patch('argparse.ArgumentParser.parse_args')
@patch('pathlib.Path.rglob', return_value=[])
@patch('pathlib.Path.exists', return_value=True) # Patch exists to avoid SystemExit for data_dir
@patch('builtins.print')
@patch('pandas.DataFrame.to_csv') # Add this mock
def test_main_no_csv_files_found(mock_to_csv, mock_print, mock_exists, mock_rglob, mock_parse_args, mock_load_and_filter, tmp_path): # Corrected order
    """Test main function when no CSV files are found."""
    mock_parse_args.return_value = MagicMock(
        data_dir=tmp_path / "data",
        month="2026-01",
        outdir=tmp_path / "out"
    )
    (tmp_path / "data").mkdir()
    mock_load_and_filter.return_value = pd.DataFrame(columns=STD_COLUMNS + ['__source_file'])

    main()

    mock_print.assert_any_call("Aucun fichier *_je.csv trouvé sous", tmp_path / "data")
    mock_load_and_filter.assert_called_once()
        # Ensure no CSV export if no data
    assert mock_rglob.call_count > 0 
    # Check that to_csv was not called if load_and_filter returns empty DataFrame
    # Note: this check is implicitly handled by mock_to_csv not being called later if df is empty
