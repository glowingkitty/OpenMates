"""Development API and Celery registries must use identical feature gates."""

# contract-test-file: tooling

from pathlib import Path

import yaml


def test_all_development_workers_use_api_feature_config():
    root = Path(__file__).parents[1] / "core"
    base = yaml.safe_load((root / "docker-compose.yml").read_text())["services"]
    overrides = yaml.safe_load((root / "docker-compose.override.yml").read_text())["services"]
    api_config = overrides["api"]["environment"]["BACKEND_CONFIG_FILE"]
    workers = {name for name, service in base.items() if "CELERY_QUEUES" in service.get("environment", {})}
    workers.add("task-scheduler")
    assert "core-worker" in workers and "app-ai-worker" in workers
    for name in workers:
        assert overrides[name]["environment"]["BACKEND_CONFIG_FILE"] == api_config, name
    assert api_config == "/app/backend/config/backend_config.dev.yml"
