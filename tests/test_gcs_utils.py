from hippique_orchestrator.scripts import gcs_utils

def test_is_gcs_enabled(monkeypatch):
    monkeypatch.setattr(gcs_utils.config, "GCS_ENABLED", True)
    assert gcs_utils.is_gcs_enabled() is True

def test_is_gcs_disabled(monkeypatch):
    monkeypatch.setattr(gcs_utils.config, "GCS_ENABLED", False)
    assert gcs_utils.is_gcs_enabled() is False
