"""
Billing worker Compose guardrails.

The July 2026 billing incident was caused by production task-worker drift: the
worker could start without the Vault setup data and with the wrong environment.
This test keeps source and self-host task-worker definitions aligned before a
deploy can reintroduce silent billing/invoice failures.
"""

# contract-test-file: infrastructure

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
EMAIL_QUEUE = "email"
USER_INIT_QUEUE = "user_init"
REMINDER_QUEUE = "reminder"
CORE_TASK_QUEUES = "persistence,health_check,server_stats,demo,e2e_tests,push"
USER_TASK_QUEUE = "user_tasks"
COMPOSE_FILES = (
    ROOT / "backend/core/docker-compose.yml",
    ROOT / "backend/core/docker-compose.selfhost.yml",
    ROOT / "frontend/packages/openmates-cli/templates/core/docker-compose.selfhost.yml",
)
API_DOCKERFILE = ROOT / "backend/core/api/Dockerfile"
SELFHOST_API_DOCKERFILE = ROOT / "backend/core/api/Dockerfile.selfhost"
SELFHOST_IMAGE_WORKFLOW = ROOT / ".github/workflows/publish-selfhost-images.yml"
RELEASE_PREPARATION = ROOT / "scripts/prepare_release_candidate.py"
CLI_SERVER_PLANNING = ROOT / "frontend/packages/openmates-cli/src/serverPlanning.ts"
CLOUD_BOOT_SMOKE = ROOT / "scripts/api_tests/test_cloud_overlay_boot.py"
PROMETHEUS_CONFIG = ROOT / "backend/core/monitoring/prometheus/prometheus.yml"


def test_task_worker_keeps_billing_safe_environment_and_mounts() -> None:
    for compose_path in COMPOSE_FILES:
        compose = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
        task_worker = compose["services"]["task-worker"]
        environment = task_worker["environment"]
        volumes = task_worker["volumes"]
        command = task_worker["command"]

        assert environment["SERVER_ENVIRONMENT"] == "${SERVER_ENVIRONMENT}", compose_path
        assert environment["CELERY_QUEUES"] == EMAIL_QUEUE, compose_path
        assert "--queues=email " in command, compose_path
        assert "SERVER_ENVIRONMENT=development" not in command, compose_path
        assert any(volume.endswith(":/vault-data") for volume in volumes), compose_path
        if "selfhost" in compose_path.name:
            assert any(volume.endswith(":/app_config") for volume in volumes), compose_path
        assert any(volume.endswith(":/app/logs") for volume in volumes), compose_path

        core_worker = compose["services"]["core-worker"]
        assert core_worker["environment"]["CELERY_QUEUES"] == CORE_TASK_QUEUES, compose_path
        assert f"--queues={CORE_TASK_QUEUES} " in core_worker["command"], compose_path
        assert USER_INIT_QUEUE not in core_worker["environment"]["CELERY_QUEUES"].split(","), compose_path
        assert REMINDER_QUEUE not in core_worker["environment"]["CELERY_QUEUES"].split(","), compose_path
        assert "email" not in core_worker["environment"]["CELERY_QUEUES"].split(","), compose_path
        if compose_path == COMPOSE_FILES[0]:
            assert core_worker["extends"] == {"service": "task-worker"}, compose_path

        user_tasks_worker = compose["services"].get("user-tasks-worker")
        assert user_tasks_worker is not None, compose_path
        assert user_tasks_worker["environment"]["CELERY_QUEUES"] == USER_TASK_QUEUE, compose_path
        assert f"--queues={USER_TASK_QUEUE} " in user_tasks_worker["command"], compose_path
        assert user_tasks_worker["environment"]["CELERY_METRICS_PORT"] == "9112", compose_path
        if compose_path == COMPOSE_FILES[0]:
            assert user_tasks_worker["extends"] == {"service": "task-worker"}, compose_path

        reminder_worker = compose["services"].get("reminder-worker")
        assert reminder_worker is not None, compose_path
        assert reminder_worker["environment"]["CELERY_QUEUES"] == REMINDER_QUEUE, compose_path
        assert f"--queues={REMINDER_QUEUE} " in reminder_worker["command"], compose_path
        assert reminder_worker["environment"]["CELERY_METRICS_PORT"] == "9111", compose_path
        if compose_path == COMPOSE_FILES[0]:
            assert reminder_worker["extends"] == {"service": "task-worker"}, compose_path

        user_init_worker = compose["services"].get("user-init-worker")
        assert user_init_worker is not None, compose_path
        assert user_init_worker["environment"]["CELERY_QUEUES"] == USER_INIT_QUEUE, compose_path
        assert f"--queues={USER_INIT_QUEUE} " in user_init_worker["command"], compose_path
        assert "persistence" not in user_init_worker["environment"]["CELERY_QUEUES"].split(","), compose_path


def test_api_image_packages_worker_and_billing_translation_runtime() -> None:
    dockerfile = API_DOCKERFILE.read_text(encoding="utf-8")

    assert "gosu" in dockerfile
    assert "groupadd --system celeryuser" in dockerfile
    assert "useradd --system --gid celeryuser" in dockerfile
    assert "frontend/packages/ui/src/i18n/locales" in dockerfile


def test_selfhost_api_image_builds_and_requires_generated_locales() -> None:
    dockerfile = SELFHOST_API_DOCKERFILE.read_text(encoding="utf-8")
    workflow = SELFHOST_IMAGE_WORKFLOW.read_text(encoding="utf-8")

    assert "RUN test -s /app/frontend/packages/ui/src/i18n/locales/en.json" in dockerfile
    assert "pnpm --filter @repo/ui build:translations" in workflow


def test_core_worker_is_in_every_runtime_control_plane() -> None:
    for service in ('"core-worker"', '"user-init-worker"', '"user-tasks-worker"', '"reminder-worker"'):
        assert service in RELEASE_PREPARATION.read_text(encoding="utf-8")
        assert service in CLI_SERVER_PLANNING.read_text(encoding="utf-8")
        assert service in CLOUD_BOOT_SMOKE.read_text(encoding="utf-8")
    assert '"core-worker:9109"' in PROMETHEUS_CONFIG.read_text(encoding="utf-8")
    assert '"user-init-worker:9110"' in PROMETHEUS_CONFIG.read_text(encoding="utf-8")
    assert '"user-tasks-worker:9112"' in PROMETHEUS_CONFIG.read_text(encoding="utf-8")
    assert '"reminder-worker:9111"' in PROMETHEUS_CONFIG.read_text(encoding="utf-8")
