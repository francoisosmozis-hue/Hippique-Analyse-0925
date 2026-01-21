"""Unit tests for the SourceRegistry."""

import unittest
from unittest.mock import MagicMock, patch
import yaml
import datetime # Added
from datetime import time # Added

from hippique_orchestrator.source_registry import SourceRegistry
from hippique_orchestrator.providers.base_provider import (
    BaseProgrammeProvider,
    BaseSnapshotProvider,
)


class MockPrimaryProgrammeProvider(BaseProgrammeProvider):
    def get_programme(self, date_str: str):
        return {"races": [{"name": "Primary Race"}]}


class MockFallbackProgrammeProvider(BaseProgrammeProvider):
    def get_programme(self, date_str: str):
        return {"races": [{"name": "Fallback Race"}]}


class MockSnapshotProvider(BaseSnapshotProvider):
    def fetch_snapshot(self, meeting_id: str, race_id: str, course_id: str) -> str:
        return f"<html><body>Mock snapshot for {course_id}</body></html>"

    def parse_snapshot(self, snapshot_content: str) -> dict:
        return {
            "metadata": {"source": "mock_snapshot", "content": snapshot_content},
            "runners": [{"name": "Mock Runner Snap", "odds": "2.0"}],
        }

    async def fetch_stats_for_runner(
        self,
        runner_name: str,
        discipline: str,
        runner_data: dict,
        correlation_id: str | None = None,
        trace_id: str | None = None,
    ) -> dict:
        return {"mock_stat": "snap_value"}


class MockBrokenProvider:
    pass


# A mock that implements both capabilities
class MockDualProvider(BaseProgrammeProvider, BaseSnapshotProvider):
    def get_programme(self, date_str: str) -> dict:
        # Return a dictionary that matches the Programme Pydantic model
        return {
            "date": datetime.date(2024, 1, 1),
            "races": [
                {
                    "race_id": "DR1",
                    "reunion_id": 1,
                    "course_id": 1,
                    "hippodrome": "DUAL TRACK",
                    "date": datetime.date(2024, 1, 1),
                    "start_time": datetime.time(15, 0),
                    "name": "Dual Race",
                    "discipline": "Plat",
                    "country_code": "FR",
                    "url": "http://dual.com/dr1",
                }
            ],
        }

    def fetch_snapshot(self, meeting_id: str, race_id: str, course_id: str) -> str:
        return f"<html><body>Mock dual snapshot for {course_id}</body></html>"

    def parse_snapshot(self, snapshot_content: str) -> dict:
        return {
            "metadata": {"source": "mock_dual_snapshot", "content": snapshot_content},
            "runners": [{"name": "Mock Runner Dual", "odds": "3.0"}],
        }

    async def fetch_stats_for_runner(
        self,
        runner_name: str,
        discipline: str,
        runner_data: dict,
        correlation_id: str | None = None,
        trace_id: str | None = None,
    ) -> dict:
        return {"mock_stat": "dual_value"}


class TestSourceRegistry(unittest.TestCase):
    """Test suite for the SourceRegistry."""

    def setUp(self):
        """Reset the singleton instance before each test."""
        SourceRegistry._instance = None

    def test_get_providers_by_capability_returns_correct_order(self):
        """
        Tests that providers are returned in the correct primary -> fallback order.
        """
        mock_config = {
            "strategy": {"primary": "primary_prog", "fallback": ["fallback_prog"]},
            "providers": {
                "primary_prog": {
                    "class": "tests.test_source_registry.MockPrimaryProgrammeProvider"
                },
                "fallback_prog": {
                    "class": "tests.test_source_registry.MockFallbackProgrammeProvider"
                },
            },
        }
        with patch("builtins.open", unittest.mock.mock_open(read_data=yaml.dump(mock_config))):
            registry = SourceRegistry(config_path="dummy_path")
            
            providers = registry.get_providers_by_capability(BaseProgrammeProvider)
            
            self.assertEqual(len(providers), 2)
            self.assertIsInstance(providers[0], MockPrimaryProgrammeProvider)
            self.assertIsInstance(providers[1], MockFallbackProgrammeProvider)

    def test_get_providers_filters_by_capability(self):
        """
        Tests that only providers implementing the specified capability are returned.
        """
        mock_config = {
            "strategy": {"primary": "prog_provider", "fallback": ["snap_provider"]},
            "providers": {
                "prog_provider": {
                    "class": "tests.test_source_registry.MockPrimaryProgrammeProvider"
                },
                "snap_provider": {
                    "class": "tests.test_source_registry.MockSnapshotProvider"
                },
            },
        }
        with patch("builtins.open", unittest.mock.mock_open(read_data=yaml.dump(mock_config))):
            registry = SourceRegistry(config_path="dummy_path")
            
            programme_providers = registry.get_providers_by_capability(BaseProgrammeProvider)
            snapshot_providers = registry.get_providers_by_capability(BaseSnapshotProvider)

            self.assertEqual(len(programme_providers), 1)
            self.assertIsInstance(programme_providers[0], MockPrimaryProgrammeProvider)
            
            self.assertEqual(len(snapshot_providers), 1)
            self.assertIsInstance(snapshot_providers[0], MockSnapshotProvider)

    def test_get_providers_handles_dual_capability_provider(self):
        """
        Tests that a single provider implementing multiple capabilities is returned for each.
        """
        mock_config = {
            "strategy": {"primary": "dual"},
            "providers": {
                "dual": {"class": "tests.test_source_registry.MockDualProvider"}
            },
        }
        with patch("builtins.open", unittest.mock.mock_open(read_data=yaml.dump(mock_config))):
            registry = SourceRegistry(config_path="dummy_path")
            
            programme_providers = registry.get_providers_by_capability(BaseProgrammeProvider)
            snapshot_providers = registry.get_providers_by_capability(BaseSnapshotProvider)

            self.assertEqual(len(programme_providers), 1)
            self.assertIsInstance(programme_providers[0], MockDualProvider)
            
            self.assertEqual(len(snapshot_providers), 1)
            self.assertIsInstance(snapshot_providers[0], MockDualProvider)

    def test_get_providers_skips_misconfigured_providers(self):
        """
        Tests that the registry gracefully skips providers that don't match the capability.
        """
        mock_config = {
            "strategy": {"primary": "good_provider", "fallback": ["broken_provider"]},
            "providers": {
                "good_provider": {
                    "class": "tests.test_source_registry.MockPrimaryProgrammeProvider"
                },
                "broken_provider": {
                    "class": "tests.test_source_registry.MockBrokenProvider"
                },
            },
        }
        with patch("builtins.open", unittest.mock.mock_open(read_data=yaml.dump(mock_config))):
            with self.assertLogs('hippique_orchestrator.source_registry', level='WARNING') as cm:
                registry = SourceRegistry(config_path="dummy_path")
                providers = registry.get_providers_by_capability(BaseProgrammeProvider)
                
                self.assertEqual(len(providers), 1)
                self.assertIsInstance(providers[0], MockPrimaryProgrammeProvider)
                # Check that a warning was logged for the broken provider
                self.assertIn(
                    "WARNING:hippique_orchestrator.source_registry:Provider 'broken_provider' from strategy does not implement the required capability 'BaseProgrammeProvider'.",
                    cm.output
                )

    def test_get_providers_handles_empty_strategy(self):
        """
        Tests that an empty list is returned if the strategy is missing or empty.
        """
        mock_config = {"strategy": {}, "providers": {}}
        with patch("builtins.open", unittest.mock.mock_open(read_data=yaml.dump(mock_config))):
             with self.assertLogs('hippique_orchestrator.source_registry', level='WARNING') as cm:
                registry = SourceRegistry(config_path="dummy_path")
                providers = registry.get_providers_by_capability(BaseProgrammeProvider)
                self.assertEqual(len(providers), 0)
                self.assertIn("No provider strategy defined", cm.output[0])


if __name__ == "__main__":
    unittest.main()