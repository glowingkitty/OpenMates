"""Public Apps discovery funding, retention, publication and wiring contracts."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import yaml
from jsonschema import Draft202012Validator

from backend.core.api.app.services.apps_workspace_public_service import (
    AppsWorkspacePublicService, PUBLIC_QUERIES, QUERY_VERSION, DAY, public_search_input,
)
from backend.core.api.app.services.apps_workspace_recommendations_store import AppsRecommendationsStore


@pytest.fixture
def public_service(tmp_path):
    adapter = SimpleNamespace(execute=AsyncMock(return_value={"results": [{"title": "Public result"}]}))
    service = AppsWorkspacePublicService(store=AppsRecommendationsStore(tmp_path), adapter=adapter)
    return service, adapter


@pytest.mark.anyio
# contract-test: supporting surface=rest_api assertions=apps.recommendations.public-daily
async def test_public_refresh_has_fixed_input_without_user_or_billing_context(public_service):
    service, adapter = public_service
    now = 2_000_000_000
    assert await service.refresh("code", now=now)
    call = adapter.execute.await_args
    assert call.args == ("code", "search_repos", public_search_input("code", now))
    assert call.kwargs == {}
    en = await service.library("code", "en", now=now)
    de = await service.library("code", "de", now=now)
    assert en["query_version"] == QUERY_VERSION
    assert en["recommendations"][0]["result"] == de["recommendations"][0]["result"]
    assert en["recommendations"][0]["input"] == de["recommendations"][0]["input"]
    assert en["cta"]["label"] != de["cta"]["label"]
    assert de["recommendations"][0]["request_text"] == de["cta"]["query"]
    assert not await service.refresh("code", now=now + 1)
    assert adapter.execute.await_count == 1


@pytest.mark.anyio
# contract-test: supporting surface=rest_api assertions=apps.recommendations.public-daily
async def test_personal_and_sensitive_apps_have_no_public_content_or_cta(public_service):
    service, adapter = public_service
    for app in ("health", "jobs", "home", "fitness", "weather", "finance", "travel"):
        assert not await service.refresh(app)
        library = await service.library(app)
        assert library["recommendations"] == [] and library["cta"] is None
    adapter.execute.assert_not_awaited()


@pytest.mark.anyio
# contract-test: supporting surface=rest_api assertions=apps.recommendations.public-daily
async def test_public_batch_is_unencrypted_but_never_returned_after_24_hours(public_service):
    service, _ = public_service
    now = 2_000_000_000
    await service.refresh("models3d", now=now)
    scope = service.store.scope("public", "models3d", None)
    assert service.store.read(scope, "batch")["result"]["results"][0]["title"] == "Public result"
    assert (await service.library("models3d", now=now + DAY))["recommendations"] == []
    assert not service.store.path(scope, "batch").exists()


@pytest.mark.anyio
# contract-test: supporting surface=rest_api assertions=apps.recommendations.public-daily
async def test_public_provider_failure_is_not_replayed_same_day(public_service):
    service, adapter = public_service
    adapter.execute.side_effect = RuntimeError("unavailable")
    now = 2_000_000_000
    with pytest.raises(RuntimeError):
        await service.refresh("news", now=now)
    assert not await service.refresh("news", now=now + 1)
    assert adapter.execute.await_count == 1


@pytest.mark.anyio
# contract-test: supporting surface=rest_api assertions=apps.recommendations.public-daily
async def test_only_already_published_science_media_fields_reused_never_private_pool(public_service):
    service, adapter = public_service
    public_defaults = SimpleNamespace(get_defaults_for_date=AsyncMock(return_value=[
        {"content_type": "video", "category": "science", "youtube_id": "public-video", "video_title": "A science film",
         "phrase": "MUST NOT COPY", "assistant_response": "PRIVATE DERIVED TEXT"},
        {"content_type": "video", "category": "health", "youtube_id": "sensitive-topic"},
        {"content_type": "feature", "youtube_id": "feature"},
    ]))
    service.directus = SimpleNamespace(inspiration_defaults=public_defaults)
    assert await service.refresh("videos", now=2_000_000_000)
    batch = (await service.library("videos", now=2_000_000_001))["recommendations"][0]
    assert len(batch["result"]["results"]) == 1
    assert batch["result"]["results"][0]["video_id"] == "public-video"
    assert "MUST NOT COPY" not in str(batch) and "PRIVATE DERIVED TEXT" not in str(batch)
    adapter.execute.assert_not_awaited()


# contract-test: supporting surface=rest_api assertions=apps.recommendations.public-daily
def test_fixed_queries_match_current_catalog_and_have_localized_ctas():
    root = Path(__file__).resolve().parents[1]
    for app, definition in PUBLIC_QUERIES.items():
        document = yaml.safe_load((root / "apps" / app / "app.yml").read_text())
        skill = next(row for row in document["skills"] if row["id"] == definition["skill_id"])
        schema = skill.get("sdk_tool_schema") or skill["tool_schema"]
        Draft202012Validator(schema).validate(public_search_input(app, 2_000_000_000))
        assert all(definition[language][0] and definition[language][1] for language in ("en", "de"))
        assert "user_id" not in str(definition["parameters"])


# contract-test: supporting surface=rest_api assertions=apps.recommendations.public-daily
def test_compose_mounts_private_volume_only_api_and_task_worker_and_marks_backup_exclusion():
    root = Path(__file__).resolve().parents[2]
    for relative in ("backend/core/docker-compose.yml", "backend/core/docker-compose.selfhost.yml",
                     "frontend/packages/openmates-cli/templates/core/docker-compose.selfhost.yml"):
        document = yaml.safe_load((root / relative).read_text())
        assert document["volumes"]["apps-recommendations-data"]["labels"]["openmates.backup.exclude"] == "true"
        owners = []
        for name, service in document["services"].items():
            if "apps-recommendations-data:/app/data/apps-recommendations" in service.get("volumes", []):
                owners.append(name)
                assert service["environment"]["APPS_RECOMMENDATIONS_DIR"] == "/app/data/apps-recommendations"
        assert set(owners) == {"api", "task-worker"}
        command = str(document["services"]["task-worker"]["command"])
        assert "chmod 700 /app/data/apps-recommendations" in command
        assert "chown -R celeryuser:celeryuser /app/data/apps-recommendations" in command
    # Managed backup is an explicit env/config/Postgres allowlist, not a volume
    # archive. Do not add temporary payloads to that list or staging copy code.
    backup = (root / "frontend/packages/openmates-cli/src/serverPlanning.ts").read_text()
    plan = backup.split("export function planBackup", 1)[1].split("export function planRestore", 1)[0]
    assert "apps-recommendations" not in plan and '"postgres-dump"' in plan
    runtime = (root / "backend/core/api/app/tasks/celery_config.py").read_text()
    assert "'task': 'apps_workspace.cleanup_expired'" in runtime
    assert "'task': 'apps_workspace.refresh_public'" in runtime
