# backend/tests/test_workflow_runtime_directus_deployment.py
#
# Deployment guard for the Workflow runtime transaction endpoint and migration.
# It prevents a scheduler build from starting without its durable schema layer.
#
# Spec: docs/specs/workflows-v1/spec.yml (TASK-2)

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILES = (
    ROOT / "backend/core/docker-compose.yml",
    ROOT / "backend/core/docker-compose.selfhost.yml",
    ROOT / "frontend/packages/openmates-cli/templates/core/docker-compose.selfhost.yml",
)


def test_directus_images_and_development_setup_include_workflow_runtime_contract() -> None:
    directus_dockerfile = (ROOT / "backend/core/directus/Dockerfile").read_text(encoding="utf-8")
    setup_dockerfile = (ROOT / "backend/core/directus/Dockerfile.setup.selfhost").read_text(encoding="utf-8")
    assert (ROOT / "backend/core/directus/extensions/workflow-runtime-transaction/src/operations.js").is_file()
    assert "workflow-runtime-transaction/dist/" in directus_dockerfile
    assert "workflow-runtime-transaction" in directus_dockerfile
    assert "migrate_workflow_runtime_indexes.sql" in setup_dockerfile
    for compose_path in COMPOSE_FILES:
        compose = compose_path.read_text(encoding="utf-8")
        assert "WORKFLOW_RUNTIME_MIGRATION_PATH" in compose, compose_path
        assert "migrate_workflow_runtime_indexes.sql" in compose, compose_path
