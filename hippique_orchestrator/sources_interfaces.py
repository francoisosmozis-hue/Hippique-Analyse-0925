from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Protocol


class ProgrammeFetcher(Protocol):
    """
    Interface for fetching daily race programmes.
    """
    async def fetch_programme(
        self, url: str, correlation_id: str | None = None, trace_id: str | None = None
    ) -> list[dict[str, Any]]:
        """
        Fetches the daily race programme.
        Returns a list of race dictionaries.
        """
        ...


class SnapshotFetcher(Protocol):
    """
    Interface for fetching detailed race snapshots.
    """
    async def fetch_snapshot(
        self,
        race_url: str,
        *,
        phase: str = "H30",
        date: str | None = None,
        correlation_id: str | None = None,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Fetches detailed race snapshot data.
        Returns a dictionary representing the snapshot.
        """
        ...


class StatsFetcher(Protocol):
    """
    Interface for fetching statistics for a given runner.
    """
    async def fetch_stats_for_runner(
        self,
        runner_name: str,
        discipline: str,
        runner_data: dict[str, Any], # Additional data for context, e.g., jockey, trainer names
        correlation_id: str | None = None,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Fetches statistics for a specific runner.
        Returns a dictionary of statistics (e.g., win rate, place rate, chrono).
        """
        ...


class SourceProvider(ABC):
    """
    Abstract Base Class for a unified data source provider.
    Combines ProgrammeFetcher, SnapshotFetcher, and StatsFetcher interfaces.
    """

    @abstractmethod
    async def fetch_programme(
        self, url: str, correlation_id: str | None = None, trace_id: str | None = None
    ) -> list[dict[str, Any]]:
        """
        Fetches the daily race programme.
        Returns a list of race dictionaries.
        """
        pass

    @abstractmethod
    async def fetch_snapshot(
        self,
        race_url: str,
        *,
        phase: str = "H30",
        date: str | None = None,
        correlation_id: str | None = None,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Fetches detailed race snapshot data.
        Returns a dictionary representing the snapshot.
        """
        pass

    @abstractmethod
    async def fetch_stats_for_runner(
        self,
        runner_name: str,
        discipline: str,
        runner_data: dict[str, Any],
        correlation_id: str | None = None,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Fetches statistics for a specific runner.
        Returns a dictionary of statistics.
        """
        pass
