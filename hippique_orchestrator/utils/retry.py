"""
Standardized retry helpers for HTTP fetch operations (sync and async).
"""
import asyncio
import functools
import logging
import random
import time
from typing import Any, Callable

import httpx
import requests

from hippique_orchestrator import config

logger = logging.getLogger(__name__)

# --- Custom Exceptions ---
class RetriableError(Exception):
    """Base exception for any error that should be retried."""
    pass

class RetriableHTTPError(RetriableError):
    """Custom exception for HTTP errors that should be retried (e.g., 429, 403)."""
    pass

class AntiBotError(RetriableError):
    """Raised when a request is blocked by anti-bot measures."""
    pass

class ParsingError(RetriableError):
    """Raised when page content is malformed or unexpected, suggesting a retry might help."""
    pass


# --- Async Retry (for httpx) ---

def async_http_retry(func: Callable) -> Callable:
    """
    A decorator to retry an async function that makes an HTTP request upon failure.
    Works with httpx.
    """
    @functools.wraps(func)
    async def wrapper(*args, **kwargs) -> Any:
        last_exception = None
        for attempt in range(config.RETRIES + 1):
            try:
                return await func(*args, **kwargs)
            except (
                RetriableError,
                httpx.TimeoutException,
                httpx.ConnectError,
                httpx.NetworkError,
            ) as e:
                last_exception = e
                if attempt == config.RETRIES:
                    logger.error(
                        "Final attempt failed for async func %s. No more retries.",
                        func.__name__,
                    )
                    break

                backoff_time = config.BACKOFF_BASE_S * (2 ** attempt)
                jitter = random.uniform(0, backoff_time * 0.1)
                sleep_duration = backoff_time + jitter

                logger.warning(
                    "Attempt %d/%d for %s failed with %s. Retrying in %.2fs.",
                    attempt + 1,
                    config.RETRIES + 1,
                    func.__name__,
                    type(e).__name__,
                    sleep_duration,
                )
                await asyncio.sleep(sleep_duration)

        raise last_exception
    return wrapper

def check_for_retriable_status(response: httpx.Response | requests.Response):
    """
    Checks response status and raises RetriableHTTPError if applicable.
    Works for both httpx.Response and requests.Response.
    """
    if response.status_code in [403, 429]: # Forbidden, Too Many Requests
        raise RetriableHTTPError(f"Received retriable status code: {response.status_code}")
    if response.status_code == 503: # Service Unavailable
        raise RetriableHTTPError("Received 503 Service Unavailable")

def check_for_antibot(html_content: str):
    """
    Raises AntiBotError if common anti-bot patterns are found in the HTML.
    """
    if "Attention Required! | Cloudflare" in html_content or "incapsula" in html_content.lower():
        raise AntiBotError("Request blocked by anti-bot service (Cloudflare/Incapsula).")


# --- Sync Retry (for requests) ---

def sync_http_retry(func: Callable) -> Callable:
    """
    A decorator to retry a sync function that makes an HTTP request upon failure.
    Works with requests.
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs) -> Any:
        last_exception = None
        for attempt in range(config.RETRIES + 1):
            try:
                return func(*args, **kwargs)
            except (
                RetriableError,
                requests.exceptions.Timeout,
                requests.exceptions.ConnectionError,
            ) as e:
                last_exception = e
                if attempt == config.RETRIES:
                    logger.error(
                        "Final attempt failed for sync func %s. No more retries.",
                        func.__name__,
                    )
                    break

                backoff_time = config.BACKOFF_BASE_S * (2 ** attempt)
                jitter = random.uniform(0, backoff_time * 0.1)
                sleep_duration = backoff_time + jitter

                logger.warning(
                    "Attempt %d/%d for %s failed with %s. Retrying in %.2fs.",
                    attempt + 1,
                    config.RETRIES + 1,
                    func.__name__,
                    type(e).__name__,
                    sleep_duration,
                )
                time.sleep(sleep_duration)
        
        raise last_exception
    return wrapper