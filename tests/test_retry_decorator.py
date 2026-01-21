"""
Tests for the HTTP retry decorator.
"""

import httpx
import pytest
from unittest.mock import Mock, patch
import pytest
from hippique_orchestrator.utils.retry import (
    http_retry,
    FetchTimeoutError,
    FetchForbiddenError,
    FetchTooManyRequestsError,
    ParsingError,
    AntiBotError,
    TOTAL_ATTEMPTS
)

# --- Test Functions ---

def successful_function():
    """A function that succeeds on the first attempt."""
    return "Success"

def function_with_timeout():
    """A function that always raises a timeout error."""
    raise httpx.TimeoutException("Timeout", request=Mock())

def function_with_403():
    """A function that always raises a 403 error."""
    response = Mock()
    response.status_code = 403
    raise httpx.HTTPStatusError("Forbidden", request=Mock(), response=response)

def function_with_429():
    """A function that always raises a 429 error."""
    response = Mock()
    response.status_code = 429
    raise httpx.HTTPStatusError("Too Many Requests", request=Mock(), response=response)

def function_with_500():
    """A function that raises a generic 500 error."""
    response = Mock()
    response.status_code = 500
    raise httpx.HTTPStatusError("Server Error", request=Mock(), response=response)

def function_with_parsing_error():
    """A function that raises a generic exception, simulating a parsing error."""
    raise ValueError("Could not parse content")

def function_with_antibot_error():
    """A function that raises an exception with anti-bot keywords."""
    raise ConnectionError("Something something Cloudflare captcha")


# --- Test Cases ---

@patch("tenacity.nap.time.sleep", return_value=None)
def test_retry_succeeds_on_first_try(mock_sleep, mocker):
    """Tests that a successful function is not retried."""
    mocked_successful_function = mocker.patch(
        __name__ + ".successful_function", side_effect=successful_function
    )
    decorated_func = http_retry(mocked_successful_function)
    assert decorated_func() == "Success"
    assert mocked_successful_function.call_count == 1

@patch("tenacity.nap.time.sleep", return_value=None)
def test_retry_handles_timeout(mock_sleep, mocker):
    """Tests that a timeout is retried and eventually raises FetchTimeoutError."""
    mocked_function_with_timeout = mocker.patch(
        __name__ + ".function_with_timeout", side_effect=function_with_timeout
    )
    decorated_func = http_retry(mocked_function_with_timeout)
    with pytest.raises(FetchTimeoutError):
        decorated_func()
    assert mocked_function_with_timeout.call_count == TOTAL_ATTEMPTS

@patch("tenacity.nap.time.sleep", return_value=None)
def test_retry_handles_403_forbidden(mock_sleep, mocker):
    """Tests that a 403 error is retried and raises FetchForbiddenError."""
    mocked_function_with_403 = mocker.patch(
        __name__ + ".function_with_403", side_effect=function_with_403
    )
    decorated_func = http_retry(mocked_function_with_403)
    with pytest.raises(FetchForbiddenError):
        decorated_func()
    assert mocked_function_with_403.call_count == TOTAL_ATTEMPTS

@patch("tenacity.nap.time.sleep", return_value=None)
def test_retry_handles_429_too_many_requests(mock_sleep, mocker):
    """Tests that a 429 error is retried and raises FetchTooManyRequestsError."""
    mocked_function_with_429 = mocker.patch(
        __name__ + ".function_with_429", side_effect=function_with_429
    )
    decorated_func = http_retry(mocked_function_with_429)
    with pytest.raises(FetchTooManyRequestsError):
        decorated_func()
    assert mocked_function_with_429.call_count == TOTAL_ATTEMPTS

@patch("tenacity.nap.time.sleep", return_value=None)
def test_retry_reraises_other_http_errors(mock_sleep, mocker):
    """Tests that other HTTP errors (like 500) are not classified and are reraised."""
    mocked_function_with_500 = mocker.patch(
        __name__ + ".function_with_500", side_effect=function_with_500
    )
    decorated_func = http_retry(mocked_function_with_500)
    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        decorated_func()
    assert exc_info.value.response.status_code == 500
    assert mocked_function_with_500.call_count == TOTAL_ATTEMPTS

@patch("tenacity.nap.time.sleep", return_value=None)
def test_retry_handles_parsing_error(mock_sleep, mocker):
    """Tests that a generic exception is classified as ParsingError."""
    mocked_function_with_parsing_error = mocker.patch(
        __name__ + ".function_with_parsing_error", side_effect=function_with_parsing_error
    )
    decorated_func = http_retry(mocked_function_with_parsing_error)
    with pytest.raises(ParsingError):
        decorated_func()
    assert mocked_function_with_parsing_error.call_count == TOTAL_ATTEMPTS

@patch("tenacity.nap.time.sleep", return_value=None)
def test_retry_handles_antibot_error(mock_sleep, mocker):
    """Tests that an exception with anti-bot keywords is classified as AntiBotError."""
    mocked_function_with_antibot_error = mocker.patch(
        __name__ + ".function_with_antibot_error", side_effect=function_with_antibot_error
    )
    decorated_func = http_retry(mocked_function_with_antibot_error)
    with pytest.raises(AntiBotError):
        decorated_func()
    assert mocked_function_with_antibot_error.call_count == TOTAL_ATTEMPTS
