"""Load the repository's provider catalogue (backend/providers) into config_manager for a test.

The API container reads provider YAML files from /app/backend/providers; test runs
outside the container have no such directory, so model lookups return nothing.
Tests that check routing against real model and server entries use this fixture.
The previous catalogue is restored by monkeypatch after the test.
"""

from __future__ import annotations

from pathlib import Path

import pytest

PROVIDERS_DIR = Path(__file__).resolve().parents[1] / "providers"


@pytest.fixture
def repo_provider_catalogue(monkeypatch):
    from backend.core.api.app.utils.config_manager import config_manager

    monkeypatch.setattr(config_manager, "_provider_configs", {})
    config_manager._load_provider_configs_from_dir(str(PROVIDERS_DIR))
    assert config_manager.get_provider_config("mistral"), "repository provider catalogue did not load"
    return config_manager
