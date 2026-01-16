import asyncio
import logging
import os
import random
import time
from functools import wraps
from typing import Any, Callable, TypeVar, Coroutine, Union, Tuple

import requests

logger = logging.getLogger(__name__)

# Type variable for the decorated function's return type
R = TypeVar("R")
# Type variable for the decorated function
P = TypeVar("P", bound=Callable[..., Coroutine[Any, Any, R]])


# --- Configuration via Environment Variables ---
DEFAULT_RETRIES = 2  # Total 3 attempts (1 original + 2 retries)
DEFAULT_TIMEOUT_S = 8.0  # seconds
DEFAULT_BACKOFF_BASE_S = 1.0  # seconds

def _get_config_from_env() -> dict[str, Union[int, float]]:
    """Reads retry configuration from environment variables."""
    return {
        "retries": int(os.environ.get("RETRIES", str(DEFAULT_RETRIES))),
        "timeout": float(os.environ.get("TIMEOUT_S", str(DEFAULT_TIMEOUT_S))),
        "backoff_base": float(os.environ.get("BACKOFF_BASE_S", str(DEFAULT_BACKOFF_BASE_S))),
    }

# --- Error Classification ---
RETRYABLE_HTTP_STATUSES = {
    403,  # Forbidden (often rate limiting or temporary block)
    429,  # Too Many Requests
    500,  # Internal Server Error
    502,  # Bad Gateway
    503,  # Service Unavailable
    504,  # Gateway Timeout
}

RETRYABLE_EXCEPTIONS = (
    requests.exceptions.Timeout,
    requests.exceptions.ConnectionError,
)

# Custom exception for parsing/antibot errors
class RetryableParsingError(ValueError):
    """Raised when parsing fails in a retryable way (e.g., antibot HTML)."""
    pass

class NonRetryableError(Exception):
    """Raised when an error is encountered that should not be retried."""
    pass

def retry_async(max_attempts: int | None = None,
                timeout: float | None = None,
                backoff_base: float | None = None) -> Callable[[P], P]:
    """
    A decorator to retry an asynchronous function with exponential backoff and jitter.

    Args:
        max_attempts: Maximum number of attempts including the first one.
                      If None, uses RETRIES env var + 1, or DEFAULT_RETRIES + 1.
        timeout: Timeout for each individual call in seconds.
                 If None, uses TIMEOUT_S env var, or DEFAULT_TIMEOUT_S.
        backoff_base: Base for exponential backoff in seconds.
                      If None, uses BACKOFF_BASE_S env var, or DEFAULT_BACKOFF_BASE_S.
    """
    def decorator(func: P) -> P:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> R:
            config = _get_config_from_env()
            num_retries = (max_attempts - 1) if max_attempts is not None else config["retries"]
            current_timeout = timeout if timeout is not None else config["timeout"]
            current_backoff_base = backoff_base if backoff_base is not None else config["backoff_base"]

            for attempt in range(num_retries + 1):
                last_exception = None
                reason = "Unknown error" # Initialize reason here
                is_retryable = False # Default to not retry

                try:
                    # Add timeout to kwargs if the function supports it,
                    # or apply it using asyncio.wait_for if the function is a coroutine
                    # that does not directly support it.
                    # For requests calls, timeout is usually passed directly.
                    if 'timeout' not in kwargs and 'timeout' in func.__code__.co_varnames: # Basic check
                        kwargs['timeout'] = current_timeout
                    
                    result = await func(*args, **kwargs)
                    return result
                except RetryableParsingError as e:
                    reason = f"Parsing/antibot error: {e}"
                    is_retryable = True
                    last_exception = e
                except requests.exceptions.HTTPError as e:
                    status_code = e.response.status_code if e.response else None
                    reason = f"HTTP Error: {status_code} - {e}"
                    is_retryable = status_code in RETRYABLE_HTTP_STATUSES
                    last_exception = e
                except RETRYABLE_EXCEPTIONS as e:
                    reason = f"Network/timeout error: {e}"
                    is_retryable = True
                    last_exception = e
                except NonRetryableError as e:
                    reason = f"Non-retryable error: {e}"
                    is_retryable = False
                    last_exception = e
                except Exception as e:
                    reason = f"Unexpected error: {type(e).__name__} - {e}"
                    is_retryable = False # Default to not retry for unexpected errors
                    last_exception = e

                if not is_retryable or attempt == num_retries:
                    logger.error(f"[{func.__name__}] Failed after {attempt + 1} attempts due to {reason}. Not retrying further.")
                    if last_exception:
                        raise last_exception
                    else:
                        # If for some reason last_exception wasn't set (e.g., initial reason was "Unknown error")
                        raise RuntimeError(reason)
                
                delay = current_backoff_base * (2 ** attempt) + random.uniform(0, 0.1 * current_backoff_base)
                logger.warning(f"[{func.__name__}] Attempt {attempt + 1}/{num_retries + 1} failed due to {reason}. Retrying in {delay:.2f}s...")
                await asyncio.sleep(delay)
            
            # This part should ideally not be reached, as an exception would be re-raised
            # by the last 'raise' in the loop.
            raise RuntimeError(f"[{func.__name__}] Unexpected failure after {num_retries + 1} attempts.")

        return wrapper # type: ignore

    return decorator

def retry(max_attempts: int | None = None,
          timeout: float | None = None,
          backoff_base: float | None = None) -> Callable[[Callable[..., R]], Callable[..., R]]:
    """
    A decorator to retry a synchronous function with exponential backoff and jitter.

    Args:
        max_attempts: Maximum number of attempts including the first one.
                      If None, uses RETRIES env var + 1, or DEFAULT_RETRIES + 1.
        timeout: Timeout for each individual call in seconds.
                 If None, uses TIMEOUT_S env var, or DEFAULT_TIMEOUT_S.
        backoff_base: Base for exponential backoff in seconds.
                      If None, uses BACKOFF_BASE_S env var, or DEFAULT_BACKOFF_BASE_S.
    """
    def decorator(func: Callable[..., R]) -> Callable[..., R]:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> R:
            config = _get_config_from_env()
            num_retries = (max_attempts - 1) if max_attempts is not None else config["retries"]
            current_timeout = timeout if timeout is not None else config["timeout"]
            current_backoff_base = backoff_base if backoff_base is not None else config["backoff_base"]

            for attempt in range(num_retries + 1):
                last_exception = None
                reason = "Unknown error" # Initialize reason here
                is_retryable = False # Default to not retry

                try:
                    # Add timeout to kwargs if the function supports it
                    if 'timeout' not in kwargs and 'timeout' in func.__code__.co_varnames:
                        kwargs['timeout'] = current_timeout
                    
                    result = func(*args, **kwargs)
                    return result
                except RetryableParsingError as e:
                    reason = f"Parsing/antibot error: {e}"
                    is_retryable = True
                    last_exception = e
                except requests.exceptions.HTTPError as e:
                    status_code = e.response.status_code if e.response else None
                    reason = f"HTTP Error: {status_code} - {e}"
                    is_retryable = status_code in RETRYABLE_HTTP_STATUSES
                    last_exception = e
                except RETRYABLE_EXCEPTIONS as e:
                    reason = f"Network/timeout error: {e}"
                    is_retryable = True
                    last_exception = e
                except NonRetryableError as e:
                    reason = f"Non-retryable error: {e}"
                    is_retryable = False
                    last_exception = e
                except Exception as e:
                    reason = f"Unexpected error: {type(e).__name__} - {e}"
                    is_retryable = False # Default to not retry for unexpected errors
                    last_exception = e

                if not is_retryable or attempt == num_retries:
                    logger.error(f"[{func.__name__}] Failed after {attempt + 1} attempts due to {reason}. Not retrying further.")
                    if last_exception:
                        raise last_exception
                    else:
                        # If for some reason last_exception wasn't set (e.g., initial reason was "Unknown error")
                        raise RuntimeError(reason)
                
                delay = current_backoff_base * (2 ** attempt) + random.uniform(0, 0.1 * current_backoff_base)
                logger.warning(f"[{func.__name__}] Attempt {attempt + 1}/{num_retries + 1} failed due to {reason}. Retrying in {delay:.2f}s...")
                time.sleep(delay)
            
            raise RuntimeError(f"[{func.__name__}] Unexpected failure after {num_retries + 1} attempts.")

        return wrapper # type: ignore

    return decorator