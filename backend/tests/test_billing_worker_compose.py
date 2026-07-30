"""
Billing worker Compose guardrails.

The July 2026 billing incident was caused by production task-worker drift: the
worker could start without the Vault setup data and with the wrong environment.
This test keeps source and self-host task-worker definitions aligned before a
deploy can reintroduce silent billing/invoice failures.
"""

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
CORE_TASK_QUEUES = "email,user_init,persistence,health_check,server_stats,demo,e2e_tests,reminder,push"
COMPOSE_FILES = (
    ROOT / "backend/core/docker-compose.yml",
    ROOT / "backend/core/docker-compose.selfhost.yml",
    ROOT / "frontend/packages/openmates-cli/templates/core/docker-compose.selfhost.yml",
)


def test_task_worker_keeps_billing_safe_environment_and_mounts() -> None:
    for compose_path in COMPOSE_FILES:
        compose = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
        task_worker = compose["services"]["task-worker"]
        environment = task_worker["environment"]
        volumes = task_worker["volumes"]
        command = task_worker["command"]

        assert environment["SERVER_ENVIRONMENT"] == "${SERVER_ENVIRONMENT}", compose_path
        assert environment["CELERY_QUEUES"] == CORE_TASK_QUEUES, compose_path
        assert CORE_TASK_QUEUES in command, compose_path
        assert "SERVER_ENVIRONMENT=development" not in command, compose_path
        assert any(volume.endswith(":/vault-data") for volume in volumes), compose_path
        if "selfhost" in compose_path.name:
            assert any(volume.endswith(":/app_config") for volume in volumes), compose_path
        assert any(volume.endswith(":/app/logs") for volume in volumes), compose_path
