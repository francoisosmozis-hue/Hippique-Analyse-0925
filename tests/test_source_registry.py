import pytest
import yaml
from unittest.mock import patch, mock_open

from hippique_orchestrator.source_registry import SourceRegistry
from hippique_orchestrator.providers.base_provider import BaseProgrammeProvider, BaseSnapshotProvider
from hippique_orchestrator.providers.mock_provider import MockProvider

# Sample YAML config for testing
SAMPLE_CONFIG = {
    "strategy": {"primary": "mock"},
    "providers": {
        "mock": {
            "class": "hippique_orchestrator.providers.mock_provider.MockProvider",
            "config": {}
        },
        "boturfers": {
            "class": "hippique_orchestrator.providers.boturfers_provider.BoturfersProvider",
            "config": {"base_url": "https://example.com", "timeout_seconds": 5}
        }
    }
}

@pytest.fixture(autouse=True)
def clear_registry_singleton():
    """Ensures the SourceRegistry singleton is reset before each test."""
    SourceRegistry._instance = None
    yield
    SourceRegistry._instance = None

def test_registry_loads_providers_correctly():
    """Tests that the registry correctly loads and instantiates providers from config."""
    m = mock_open(read_data=yaml.dump(SAMPLE_CONFIG))
    with patch("builtins.open", m):
        registry = SourceRegistry()
        
        assert "mock" in registry.providers
        assert "boturfers" in registry.providers
        assert isinstance(registry.providers["mock"], MockProvider)
        # The BoturfersProvider will raise NotImplementedError, so we just check its existence
        assert registry.get_provider("boturfers") is not None

def test_get_primary_programme_provider():
    """Tests that the correct primary programme provider is returned."""
    m = mock_open(read_data=yaml.dump(SAMPLE_CONFIG))
    with patch("builtins.open", m):
        registry = SourceRegistry()
        provider = registry.get_primary_programme_provider()
        assert isinstance(provider, BaseProgrammeProvider)
        assert isinstance(provider, MockProvider)

def test_get_primary_snapshot_provider():
    """Tests that the correct primary snapshot provider is returned."""
    m = mock_open(read_data=yaml.dump(SAMPLE_CONFIG))
    with patch("builtins.open", m):
        registry = SourceRegistry()
        provider = registry.get_primary_snapshot_provider()
        assert isinstance(provider, BaseSnapshotProvider)
        assert isinstance(provider, MockProvider)

def test_raises_error_if_primary_provider_missing():
    """Tests that a ValueError is raised if the strategy.primary key is missing."""
    config_missing_primary = {"strategy": {}, "providers": {}}
    m = mock_open(read_data=yaml.dump(config_missing_primary))
    with patch("builtins.open", m):
        with pytest.raises(ValueError, match="Primary programme provider not defined in strategy."):
            SourceRegistry().get_primary_programme_provider()

def test_raises_error_if_provider_class_not_found():
    """Tests that an ImportError is raised for a non-existent provider class."""
    config_bad_class = {
        "strategy": {"primary": "bad"},
        "providers": {
            "bad": {"class": "non.existent.ClassName", "config": {}}
        }
    }
    m = mock_open(read_data=yaml.dump(config_bad_class))
    with patch("builtins.open", m):
        with pytest.raises(ImportError, match="Could not load provider 'bad'"):
            SourceRegistry()

def test_raises_type_error_for_wrong_provider_type():
    """
    Tests that a TypeError is raised if the configured primary provider
    does not implement the correct base class.
    """
    # Create a dummy class that doesn't inherit from the base classes
    class WrongProvider:
        pass

    config_wrong_type = {
        "strategy": {"primary": "wrong"},
        "providers": {
            "wrong": {"class": "tests.test_source_registry.WrongProvider", "config": {}}
        }
    }
    # This test needs the WrongProvider class to be importable
    m = mock_open(read_data=yaml.dump(config_wrong_type))
    with patch("builtins.open", m), patch("importlib.import_module") as mock_import:
        # Mock the import system to return our dummy class
        mock_module = mock_import.return_value
        setattr(mock_module, "WrongProvider", WrongProvider)

        registry = SourceRegistry() # Instantiation should work

        with pytest.raises(TypeError, match="Primary provider 'wrong' does not implement BaseProgrammeProvider."):
            registry.get_primary_programme_provider()
        
        with pytest.raises(TypeError, match="Primary provider 'wrong' does not implement BaseSnapshotProvider."):
            registry.get_primary_snapshot_provider()
