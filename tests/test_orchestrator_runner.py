from unittest.mock import AsyncMock, patch

import pytest

from hippique_orchestrator.runner import _extract_rc_from_url, run_course


# Tests for _extract_rc_from_url
@pytest.mark.parametrize(
    "url, expected_r, expected_c",
    [
        ("https://www.boturfers.fr/courses/2025-01-01/r2c3-race-name", "R2", "C3"),
        ("https://www.boturfers.fr/courses/2025-01-01/R2C3-race-name", "R2", "C3"),
        ("https://www.zeturf.fr/fr/course/2025-12-25/R1C2-test", "R1", "C2"),
        ("https://zeturf.com/R12C5/details", "R12", "C5"),
    ],
)
def test_extract_rc_from_url_success(url, expected_r, expected_c):
    r, c = _extract_rc_from_url(url)
    assert r == expected_r
    assert c == expected_c


def test_extract_rc_from_url_no_match_raises_value_error():
    with pytest.raises(ValueError, match="Cannot extract R/C from URL: http://invalid.url/xyz"):
        _extract_rc_from_url("http://invalid.url/xyz")


# Tests for run_course
@pytest.mark.asyncio
@patch(
    "hippique_orchestrator.runner._extract_rc_from_url",
    side_effect=ValueError("Invalid URL format"),
)
async def test_run_course_extract_rc_error(mock_extract_rc, caplog):
    caplog.set_level("ERROR")
    result = await run_course("http://invalid.url", "H-5", "2025-01-01")
    assert not result["ok"]
    assert "Invalid URL format" in result["error"]
    assert "Invalid URL format" in caplog.text


@pytest.mark.asyncio
@patch("hippique_orchestrator.analysis_pipeline.run_analysis_for_phase", new_callable=AsyncMock)
@patch("hippique_orchestrator.runner._extract_rc_from_url", return_value=("R1", "C1"))
async def test_run_course_analysis_pipeline_success(mock_extract_rc, mock_run_analysis, caplog):
    caplog.set_level("INFO")
    mock_run_analysis.return_value = {
        "success": True,
        "race_doc_id": "doc_id",
        "analysis_result": {"status": "GREEN"},
    }

    result = await run_course(
        "http://valid.url/R1C1",
        "H-5",
        "2025-01-01",
        correlation_id="test-corr",
        trace_id="test-trace",
    )

    mock_extract_rc.assert_called_once_with("http://valid.url/R1C1")
    mock_run_analysis.assert_called_once_with(
        course_url="http://valid.url/R1C1",
        phase="H5",
        date="2025-01-01",
        correlation_id="test-corr",
        trace_id="test-trace",
    )
    assert result["success"]
    assert result["analysis_result"]["status"] == "GREEN"
    assert "Starting Firestore-native course analysis" in caplog.text
    assert "Course analysis completed successfully." in caplog.text


@pytest.mark.asyncio
@patch("hippique_orchestrator.analysis_pipeline.run_analysis_for_phase", new_callable=AsyncMock)
@patch("hippique_orchestrator.runner._extract_rc_from_url", return_value=("R1", "C1"))
async def test_run_course_analysis_pipeline_failure(mock_extract_rc, mock_run_analysis, caplog):
    caplog.set_level("ERROR")
    mock_run_analysis.return_value = {
        "success": False,
        "race_doc_id": "doc_id",
        "message": "Pipeline error",
    }

    result = await run_course(
        "http://valid.url/R1C1",
        "H-5",
        "2025-01-01",
        correlation_id="test-corr",
        trace_id="test-trace",
    )

    assert not result["success"]
    assert "Pipeline error" in result["message"]


@pytest.mark.asyncio
@patch(
    "hippique_orchestrator.analysis_pipeline.run_analysis_for_phase",
    side_effect=Exception("Unexpected error"),
)
@patch("hippique_orchestrator.runner._extract_rc_from_url", return_value=("R1", "C1"))
async def test_run_course_unexpected_exception(mock_extract_rc, mock_run_analysis, caplog):
    caplog.set_level("ERROR")

    result = await run_course(
        "http://valid.url/R1C1",
        "H-5",
        "2025-01-01",
        correlation_id="test-corr",
        trace_id="test-trace",
    )

    assert not result["ok"]
    assert result["phase"] == "H5"
    assert "An unexpected exception occurred: Unexpected error" in result["error"]
    assert "Course analysis failed." in caplog.text
    assert "Unexpected error" in caplog.text  # Ensure exception message is logged
