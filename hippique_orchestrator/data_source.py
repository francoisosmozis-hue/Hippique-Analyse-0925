"""
hippique_orchestrator/data_source.py - Data Source Abstraction Layer

This module provides a generic interface for fetching racing data,
decoupling the main analysis pipeline from specific scraper implementations.
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse

from hippique_orchestrator.scrapers.zeturf import fetch_zeturf_race_details

from .scrapers import boturfers

logger = logging.getLogger(__name__)


async def fetch_programme(
    url: str, correlation_id: str | None = None, trace_id: str | None = None
) -> dict[str, Any]:
    """
    Fetches the daily race programme from the configured data source.

    Args:
        url (str): The URL of the programme page.
        correlation_id (str, optional): Correlation ID for logging.
        trace_id (str, optional): Trace ID for logging.

    Returns:
        dict[str, Any]: The parsed programme data.
    """
    # Currently, this delegates to the boturfers scraper.
    # This is the single point to change if the data source is switched.
    logger.info(
        "Fetching programme from data source via URL: %s",
        url,
        extra={"correlation_id": correlation_id, "trace_id": trace_id},
    )
    return await boturfers.fetch_boturfers_programme(
        url, correlation_id=correlation_id, trace_id=trace_id
    )


async def fetch_race_details(
    race_url: str,
    *,
    phase: str = "H30",
    date: str | None = None,
    correlation_id: str | None = None,
    trace_id: str | None = None,
) -> dict[str, Any]:
    """Fetches race details and returns a normalized snapshot dict.

    Routes by domain:
      - zeturf.* -> ZEturf scraper (no /partant)
      - default  -> Boturfers scraper (existing behavior)
    """
    host = (urlparse(race_url).netloc or "").lower()
    logger.info(
        "Fetching race details from data source via URL: %s",
        race_url,
        extra={"correlation_id": correlation_id, "trace_id": trace_id},
    )
    if "zeturf" in host:
        return await fetch_zeturf_race_details(race_url, phase=phase, date=date)
    return await boturfers.fetch_boturfers_race_details(
        race_url, correlation_id=correlation_id, trace_id=trace_id
    )
