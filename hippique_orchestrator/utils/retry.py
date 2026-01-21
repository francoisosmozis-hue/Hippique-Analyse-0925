"""
Standardized retry mechanism for live data fetching.
"""

import logging
import os
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, RetryError
from tenacity.wait import wait_base

# --- Configuration from Environment Variables ---

# Total number of attempts (1 initial + RETRIES)
RETRIES = int(os.getenv("RETRIES", 2))
TOTAL_ATTEMPTS = RETRIES + 1

# Request timeout in seconds
TIMEOUT_S = int(os.getenv("TIMEOUT_S", 8))

# Base for exponential backoff in seconds
BACKOFF_BASE_S = float(os.getenv("BACKOFF_BASE_S", 1.0))

# --- Custom Exception Classes for Error Classification ---

class FetchError(Exception):
    """Base exception for fetch-related errors."""
    pass

class FetchTimeoutError(FetchError):
    """Raised for request timeouts."""
    pass

class FetchForbiddenError(FetchError):
    """Raised for 403 Forbidden errors."""
    pass

class FetchTooManyRequestsError(FetchError):
    """Raised for 429 Too Many Requests errors."""
    pass

class ParsingError(FetchError):
    """Raised when the fetched content cannot be parsed."""
    pass

class AntiBotError(FetchError):
    """Raised when anti-bot mechanisms are detected."""
    pass


# --- Retry Decorator ---

def http_retry(func):
    """
    A decorator that provides a standardized retry mechanism for functions
    making HTTP requests.

    It handles common HTTP errors, classifies them into custom exceptions,
    and implements an exponential backoff with jitter.
    """
    
    @retry(
        stop=stop_after_attempt(TOTAL_ATTEMPTS),
        wait=wait_exponential(multiplier=BACKOFF_BASE_S, min=2, max=30),
        reraise=True  # Reraise the last exception after all retries fail
    )
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except httpx.TimeoutException as e:
            logging.warning(f"Request timed out after {TIMEOUT_S}s. Retrying... Details: {e}")
            raise FetchTimeoutError(f"Request timed out: {e}") from e
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 403:
                logging.error(f"Access forbidden (403). Possible anti-bot. Details: {e}")
                raise FetchForbiddenError(f"Access forbidden: {e}") from e
            if e.response.status_code == 429:
                logging.warning(f"Too many requests (429). Retrying... Details: {e}")
                raise FetchTooManyRequestsError(f"Too many requests: {e}") from e
            # Reraise other HTTP errors to be handled by the caller or fail
            raise
        except Exception as e:
            # Broad exception to catch potential parsing errors or other issues
            # This part might need refinement based on actual parsing libraries used
            logging.error(f"An unexpected error occurred during fetch/parse. Details: {e}")
            # Heuristic for anti-bot detection
            if "Cloudflare" in str(e) or "captcha" in str(e).lower():
                 raise AntiBotError(f"Anti-bot mechanism detected: {e}") from e
            # Assuming other errors could be parsing related
            raise ParsingError(f"Failed to process or parse content: {e}") from e

    return wrapper
