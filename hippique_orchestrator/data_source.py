"""
hippique_orchestrator/data_source.py - Data Source Abstraction Layer

This module provides a generic interface for fetching racing data,
decoupling the main analysis pipeline from specific scraper implementations.
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse

from hippique_orchestrator.source_registry import source_registry

logger = logging.getLogger(__name__)


async def fetch_programme(
    url: str, correlation_id: str | None = None, trace_id: str | None = None
) -> list[dict[str, Any]]:
    """
    Fetches the daily race programme from the configured data source via the SourceRegistry.
    """
    logger.info(
        "Fetching programme via SourceRegistry using URL: %s",
        url,
        extra={"correlation_id": correlation_id, "trace_id": trace_id},
    )
    return await source_registry.fetch_programme(
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
    """Fetches race details and returns a normalized snapshot dict via the SourceRegistry.
    The SourceRegistry handles routing to the appropriate scraper (e.g., Boturfers, ZEturf).
    """
    logger.info(
        "Fetching race details via SourceRegistry using URL: %s",
        race_url,
        extra={"correlation_id": correlation_id, "trace_id": trace_id},
    )
    return await source_registry.get_snapshot(
        race_url, phase=phase, date=date, correlation_id=correlation_id, trace_id=trace_id
    )
