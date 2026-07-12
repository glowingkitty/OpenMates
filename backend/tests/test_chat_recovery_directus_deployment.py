"""
Deployment guards for the Directus chat-recovery transaction extension.

These tests ensure source and image-mode installs bake the extension into the
same reproducible Directus image, keep protocol epoch zero, and verify endpoint
plus database-index health before dependent services become ready.
"""

from pathlib import Path
import re

import yaml


ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILES = (
    ROOT / "backend/core/docker-compose.yml",
    ROOT / "backend/core/docker-compose.selfhost.yml",
    ROOT / "frontend/packages/openmates-cli/templates/core/docker-compose.selfhost.yml",
)


def test_directus_image_bakes_extension_and_fails_closed() -> None:
    dockerfile = (ROOT / "backend/core/directus/Dockerfile").read_text(encoding="utf-8")
    migration = (
        ROOT / "backend/core/directus/setup/migrate_chat_recovery_unique_indexes.sql"
    ).read_text(encoding="utf-8")
    required_indexes = re.findall(
        r"CREATE UNIQUE INDEX IF NOT EXISTS ([a-z0-9_]+)", migration
    )

    assert "FROM directus/directus:11.5" in dockerfile
    assert "COPY --chown=node:node extensions /directus/extensions" in dockerfile
    assert "chat-recovery-transaction/src/*.js" in dockerfile
    assert "chat-recovery-transaction/dist/" in dockerfile
    assert (ROOT / "backend/core/directus/extensions/chat-recovery-transaction/src/operations.js").is_file()
    assert "INTERNAL_API_SHARED_TOKEN" in dockerfile
    assert "chat-recovery-transaction" in dockerfile
    assert "openmates-directus-health" in dockerfile
    assert "pg_indexes" in dockerfile
    assert len(required_indexes) == 11
    assert all(index_name in dockerfile for index_name in required_indexes)


def test_all_cms_services_use_custom_image_and_do_not_mask_extensions() -> None:
    for path in COMPOSE_FILES:
        compose = path.read_text(encoding="utf-8")
        cms = yaml.safe_load(compose)["services"]["cms"]
        assert "openmates-directus" in cms.get("image", ""), path
        assert "INTERNAL_API_SHARED_TOKEN" in cms["environment"], path
        assert "openmates-directus-health" in " ".join(cms["healthcheck"]["test"]), path
        assert all("/directus/extensions" not in volume for volume in cms.get("volumes", [])), path
        assert 'CHAT_RECOVERY_PROTOCOL_EPOCH: "1"' not in compose, path


def test_publish_and_smoke_workflows_build_directus_image() -> None:
    publish = (ROOT / ".github/workflows/publish-selfhost-images.yml").read_text(encoding="utf-8")
    smoke = (ROOT / ".github/workflows/selfhost-smoke.yml").read_text(encoding="utf-8")

    assert "image: openmates-directus" in publish
    assert "file: backend/core/directus/Dockerfile" in publish
    assert "openmates-directus:${IMAGE_TAG}" in smoke
    assert "for container in api webapp cms" in smoke
