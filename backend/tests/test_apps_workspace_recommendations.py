"""Source-level contract tests for private Apps daily search retention/authority."""
from __future__ import annotations

import asyncio
import base64
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.core.api.app.services.apps_workspace_recommendations_service import (
    AppsWorkspaceRecommendationsService, DAY,
)
from backend.core.api.app.services.apps_workspace_recommendations_store import AppsRecommendationsStore


class Cipher:
    async def encrypt_with_user_key(self, value, key):
        assert key == "server-user-key"
        return "vault:v1:" + base64.b64encode(value.encode()).decode(), 1

    async def decrypt_with_user_key(self, value, key):
        assert key == "server-user-key"
        return base64.b64decode(value.removeprefix("vault:v1:")).decode()


class DurableDirectus:
    """Models the managed pg_dump/restore boundary, separate from disk store."""
    def __init__(self, profile):
        self.rows = {}
        self.profile = profile
        self.get_user_profile = AsyncMock(return_value=(True, profile, ""))
        self.team = SimpleNamespace(require_team_role=AsyncMock())

    async def get_items(self, collection, params, **kwargs):
        assert kwargs["admin_required"]
        assert kwargs["raise_on_error"] and kwargs["no_cache"]
        if collection == "users":
            assert params["fields"] == "id,last_online_timestamp,last_access"
            return [{"id": params["filter[id][_eq]"], **deepcopy(self.profile)}]
        assert collection == "apps_workspace_libraries"
        scope = params.get("filter[scope_hash][_eq]")
        return deepcopy([row for row in self.rows.values() if not scope or row["scope_hash"] == scope])

    async def create_item(self, collection, record, **kwargs):
        assert kwargs["admin_required"]
        assert not any(row["scope_hash"] == record["scope_hash"] for row in self.rows.values())
        self.rows[record["id"]] = deepcopy(record)
        return True, deepcopy(record)

    async def update_item_if_version(self, collection, identifier, data, version, **kwargs):
        assert kwargs["admin_required"]
        row = self.rows[identifier]
        if row["version"] != version or row["scope_hash"] != kwargs["extra_filters"]["scope_hash"]:
            return None
        row.update(deepcopy(data))
        return deepcopy(row)


@pytest.fixture
def setup_service(tmp_path, monkeypatch):
    now = 2_000_000_000
    monkeypatch.setattr("backend.core.api.app.services.apps_workspace_recommendations_service.time.time", lambda: now)
    profile = {"vault_key_id": "server-user-key", "status": "active", "last_access": now}
    directus = DurableDirectus(profile)
    adapter = SimpleNamespace(execute=AsyncMock(return_value={"results": [{"title": "private result"}]}))
    store = AppsRecommendationsStore(tmp_path)
    service = AppsWorkspaceRecommendationsService(directus, Cipher(), store=store, adapter=adapter)
    monkeypatch.setattr(service, "_validate_search", lambda *_: None)
    return service, store, adapter, profile, now


async def save(service, query="private query", team_id=None):
    return await service.save_search("alice", "jobs", {"skill_id": "search", "title": "Private title",
        "query": query, "parameters": {"requests": [{"query": query}]}, "team_id": team_id})


@pytest.mark.anyio
# contract-test: supporting surface=rest_api assertions=apps.recommendations.private-daily
async def test_all_saves_retained_only_latest_paid_and_first_notice_durable(setup_service):
    service, store, adapter, _, now = setup_service
    assert (await save(service, "older private query"))["first_save"] is True
    assert (await save(service, "newer private query"))["first_save"] is False
    scope = store.scope("alice", "jobs", None)
    assert await service.refresh_scope(scope, now=now)
    library = await service.library("alice", "jobs")
    assert [s["query"] for s in library["saved_searches"]] == ["newer private query", "older private query"]
    assert adapter.execute.await_args.args[2] == {"requests": [{"query": "newer private query"}]}
    billing = adapter.execute.await_args.kwargs["billing_context"]
    assert billing["max_credits_remaining"] == 100
    assert adapter.execute.await_args.kwargs["user_id"] == "alice"
    assert not await service.refresh_scope(scope, now=now + 1)
    assert adapter.execute.await_count == 1
    # Entire nested result is ciphertext, with no separate child payload cache.
    all_disk = "".join(p.read_text() for p in store.root.iterdir() if p.suffix != ".lock")
    assert "private query" not in all_disk and "private result" not in all_disk and "Private title" not in all_disk
    assert set(p.suffix for p in store.root.iterdir()) <= {".meta", ".batch", ".lock", ".activity"}


@pytest.mark.anyio
# contract-test: supporting surface=rest_api assertions=apps.recommendations.private-daily
async def test_disabled_preference_survives_save_and_blocks_paid_run(setup_service):
    service, store, adapter, _, now = setup_service
    await service.settings("alice", "jobs", False)
    result = await save(service)
    assert result["daily_searches_enabled"] is False
    assert not await service.refresh_scope(store.scope("alice", "jobs", None), now=now)
    adapter.execute.assert_not_awaited()


@pytest.mark.anyio
# contract-test: supporting surface=rest_api assertions=apps.recommendations.private-daily
async def test_expiry_read_gate_deletes_whole_batch_without_activity_or_decryption(setup_service, monkeypatch):
    service, store, _, _, now = setup_service
    await save(service)
    scope = store.scope("alice", "jobs", None)
    await service.refresh_scope(scope, now=now)
    batch_id = (await service.library("alice", "jobs"))["recommendations"][0]["id"]
    monkeypatch.setattr("backend.core.api.app.services.apps_workspace_recommendations_service.time.time", lambda: now + DAY)
    assert await service.detail("alice", "jobs", batch_id) is None
    assert not store.path(scope, "batch").exists()
    assert len((await service.library("alice", "jobs"))["saved_searches"]) == 1


@pytest.mark.anyio
# contract-test: supporting surface=rest_api assertions=apps.recommendations.private-daily
async def test_inactive_accounts_and_cross_owner_scope_cannot_refresh_or_read(setup_service):
    service, store, adapter, profile, now = setup_service
    await save(service)
    profile["last_access"] = now - 8 * DAY
    store.write(store.scope("alice", "activity", None), "activity", {"last_active_at": now - 8 * DAY})
    assert not await service.refresh_scope(store.scope("alice", "jobs", None), now=now)
    adapter.execute.assert_not_awaited()
    assert (await service.library("bob", "jobs"))["saved_searches"] == []


@pytest.mark.anyio
# contract-test: supporting surface=rest_api assertions=apps.recommendations.private-daily
async def test_failed_provider_or_crash_claim_never_repeats_paid_run(setup_service):
    service, store, adapter, _, now = setup_service
    await save(service)
    adapter.execute.side_effect = RuntimeError("sensitive provider request")
    scope = store.scope("alice", "jobs", None)
    with pytest.raises(RuntimeError):
        await service.refresh_scope(scope, now=now)
    assert not await service.refresh_scope(scope, now=now + 1)
    assert adapter.execute.await_count == 1
    assert not store.path(scope, "batch").exists()


@pytest.mark.anyio
# contract-test: supporting surface=rest_api assertions=apps.recommendations.private-daily
async def test_parallel_claims_publish_only_one_batch_and_preserve_last_success_on_failure(setup_service):
    service, store, adapter, _, now = setup_service
    await save(service)
    scope = store.scope("alice", "jobs", None)
    results = await asyncio.gather(service.refresh_scope(scope, now=now), service.refresh_scope(scope, now=now))
    assert sorted(results) == [False, True]
    before = store.read(scope, "batch")
    adapter.execute.side_effect = RuntimeError("failed")
    with pytest.raises(RuntimeError):
        await service.refresh_scope(scope, now=now + DAY)
    # Old success expires at24h even if the replacement failed.
    assert store.read(scope, "batch") is None
    assert before["expires_at"] == now + DAY


@pytest.mark.anyio
# contract-test: supporting surface=rest_api assertions=apps.execution.direct-shared-contract
async def test_team_owner_scoping_and_revalidation(setup_service):
    service, store, adapter, _, now = setup_service
    await save(service, team_id="team-one")
    assert (await service.library("alice", "jobs"))["saved_searches"] == []
    scope = store.scope("alice", "jobs", "team-one")
    assert await service.refresh_scope(scope, now=now)
    assert adapter.execute.await_args.kwargs["billing_context"]["team_id"] == "team-one"
    service.directus.team.require_team_role.assert_any_await("team-one", "alice", {"owner", "admin", "member"})
    service.directus.team.require_team_role.side_effect = PermissionError("revoked")
    with pytest.raises(PermissionError):
        await service.library("alice", "jobs", "team-one")


@pytest.mark.anyio
# contract-test: supporting surface=rest_api assertions=apps.recommendations.private-daily
async def test_cleanup_deletes_inactive_batch_and_orphan_publish(setup_service):
    service, store, _, _, now = setup_service
    await save(service)
    scope = store.scope("alice", "jobs", None)
    await service.refresh_scope(scope, now=now)
    assert await store.cleanup(now=now + DAY) == 1
    assert (await service.repository.get(scope))["encrypted_config"].startswith("vault:")
    assert not (store.root / f"{scope}.searches").exists()


# contract-test: supporting surface=rest_api assertions=apps.recommendations.private-daily
def test_real_catalog_search_validation_accepts_read_and_rejects_invalid_and_generation(tmp_path):
    from pathlib import Path
    import yaml
    from backend.core.api.app.services.apps_workspace_recommendations_service import AppsLibraryUnavailable
    from backend.shared.python_schemas.app_metadata_schemas import AppSkillDefinition

    root = Path(__file__).resolve().parents[1]
    definition = yaml.safe_load((root / "apps/jobs/app.yml").read_text())
    skill = AppSkillDefinition.model_validate(next(s for s in definition["skills"] if s["id"] == "search"))
    registry = SimpleNamespace(is_skill_available=lambda *_: True,
                               get_metadata=lambda *_: SimpleNamespace(skills=[skill]))
    service = AppsWorkspaceRecommendationsService(None, Cipher(), store=AppsRecommendationsStore(tmp_path), registry=registry)
    service._validate_search("jobs", "search", {"requests": [{"query": "software engineer"}]})
    with pytest.raises(AppsLibraryUnavailable):
        service._validate_search("jobs", "search", {"requests": []})
    with pytest.raises(AppsLibraryUnavailable):
        service._validate_search("jobs", "search", {"requests": [{"query": "engineer"}], "_user_id": "forged"})
    with pytest.raises(AppsLibraryUnavailable):
        service._validate_search("images", "generate", {})


@pytest.mark.anyio
# contract-test: supporting surface=rest_api assertions=apps.recommendations.private-daily
async def test_failed_result_still_counts_toward_scanner_paid_work_limit(setup_service):
    service, store, adapter, _, now = setup_service
    await save(service)
    await service.save_search("alice", "news", {"skill_id": "search", "title": "News", "query": "private news",
        "parameters": {"requests": [{"query": "private news"}]}})
    adapter.execute.return_value = {"error": "unavailable"}
    result = await service.refresh_daily(limit=1)
    assert result["refreshed"] == 0
    assert adapter.execute.await_count == 1


# contract-test: supporting surface=rest_api assertions=apps.recommendations.private-daily
def test_store_replace_failure_preserves_previous_ciphertext_without_backup(tmp_path, monkeypatch):
    import os
    store = AppsRecommendationsStore(tmp_path)
    scope = store.scope("alice", "jobs", None)
    old = {"ciphertext": "vault:previous", "expires_at": 5}
    store.write(scope, "batch", old)
    monkeypatch.setattr(os, "replace", lambda *_: (_ for _ in ()).throw(OSError("disk failure")))
    with pytest.raises(OSError):
        store.write(scope, "batch", {"ciphertext": "vault:new", "expires_at": 6})
    assert store.read(scope, "batch") == old
    assert not list(tmp_path.glob(".publish-*"))


@pytest.mark.anyio
# contract-test: supporting surface=rest_api assertions=apps.recommendations.private-daily
async def test_supported_backup_restore_preserves_saved_searches_and_optout_without_temp_batch(setup_service, tmp_path):
    service, store, adapter, profile, now = setup_service
    await save(service, "older private query")
    await save(service, "newer private query")
    scope = store.scope("alice", "jobs", None)
    await service.refresh_scope(scope, now=now)
    await service.settings("alice", "jobs", False)
    # Managed server backup copies PostgreSQL, never this volume. Restore only
    # DB rows into a fresh runtime with no metadata/claims/batches/activity files.
    database_backup = deepcopy(service.directus.rows)
    assert "private result" not in str(database_backup)
    assert "private query" not in str(database_backup)
    restored_db = DurableDirectus(profile)
    restored_db.rows = deepcopy(database_backup)
    fresh_store = AppsRecommendationsStore(tmp_path / "restored-empty-ephemeral-volume")
    restored = AppsWorkspaceRecommendationsService(restored_db, Cipher(), store=fresh_store, adapter=adapter)
    restored._validate_search = lambda *_: None
    library = await restored.library("alice", "jobs")
    assert [row["query"] for row in library["saved_searches"]] == ["newer private query", "older private query"]
    assert library["daily_searches_enabled"] is False
    assert library["recommendations"] == []
    assert not (await restored.refresh_daily())["refreshed"]
    assert adapter.execute.await_count == 1
    # Optout survives another save, without re-showing first-save notice.
    later = await save(restored, "a restored save")
    assert later["daily_searches_enabled"] is False and later["first_save"] is False
    assert not list(fresh_store.root.glob("*.searches"))
    # Even explicit reenable cannot duplicate a paid claim restored from DB.
    await restored.settings("alice", "jobs", True)
    assert not await restored.refresh_scope(scope, now=now + 1)
    assert adapter.execute.await_count == 1


@pytest.mark.anyio
@pytest.mark.parametrize("general_timestamp", [2_000_000_000, "2000000000"])
# contract-test: supporting surface=rest_api assertions=apps.recommendations.private-daily
async def test_recent_general_session_activity_qualifies_without_recent_apps_visit(setup_service, general_timestamp):
    service, store, adapter, profile, now = setup_service
    await save(service)
    # No Apps use or Directus last_access update during the last eight days.
    # Existing web/CLI session validation is the only fresh account activity.
    store.write(store.scope("alice", "activity", None), "activity", {"last_active_at": now - 8 * DAY})
    profile["last_access"] = now - 8 * DAY
    profile["last_online_timestamp"] = general_timestamp
    assert await service.refresh_scope(store.scope("alice", "jobs", None), now=now)
    assert adapter.execute.await_count == 1


@pytest.mark.anyio
# contract-test: supporting surface=rest_api assertions=apps.recommendations.private-daily
async def test_stale_general_and_apps_activity_never_dispatches_paid_search(setup_service):
    service, store, adapter, profile, now = setup_service
    await save(service)
    store.write(store.scope("alice", "activity", None), "activity", {"last_active_at": now - 8 * DAY})
    profile["last_access"] = now - 8 * DAY
    profile["last_online_timestamp"] = str(now - 8 * DAY)
    assert not await service.refresh_scope(store.scope("alice", "jobs", None), now=now)
    adapter.execute.assert_not_awaited()


@pytest.mark.anyio
# contract-test: supporting surface=rest_api assertions=apps.recommendations.private-daily
async def test_first_optout_and_save_use_real_directus_and_vault_method_boundaries(tmp_path):
    """Exercise real service adapters; only their outbound HTTP is doubled."""
    import json
    from pathlib import Path
    import httpx
    import yaml
    from backend.core.api.app.services.directus.directus import DirectusService
    from backend.core.api.app.utils.encryption import EncryptionService

    owner = "00000000-0000-4000-8000-000000000001"
    key = "server-user-key"
    persisted, vault_payloads, requests = {}, {}, []
    directus = DirectusService.__new__(DirectusService)
    directus.base_url = "http://cms.test"
    directus.ensure_auth_token = AsyncMock(return_value="unit-admin-token")
    directus.get_user_profile = AsyncMock(return_value=(True, {"vault_key_id": key, "status": "active"}, ""))

    async def cms_request(method, url, **kwargs):
        assert url == "http://cms.test/items/apps_workspace_libraries"
        assert kwargs["headers"]["Authorization"] == "Bearer unit-admin-token"
        requests.append((method, deepcopy(kwargs)))
        if method == "GET":
            assert kwargs["params"]["filter[scope_hash][_eq]"]
            assert kwargs["headers"]["Cache-Control"] == "no-store"
            rows = list(persisted.values())
            return httpx.Response(200, json={"data": rows})
        if method == "POST":
            row = deepcopy(kwargs["json"])
            persisted[row["id"]] = row
            return httpx.Response(201, json={"data": row})
        assert method == "PATCH"
        body, params = kwargs["json"], kwargs["params"]
        assert set(body) == {"keys", "data"} and len(body["keys"]) == 1
        row = persisted[body["keys"][0]]
        assert params["filter[id][_eq]"] == row["id"]
        assert params["filter[version][_eq]"] == row["version"]
        assert params["filter[scope_hash][_eq]"] == row["scope_hash"]
        row.update(deepcopy(body["data"]))
        return httpx.Response(200, json={"data": [row]})

    directus._make_api_request = cms_request
    encryption = EncryptionService.__new__(EncryptionService)
    encryption.transit_mount = "transit"

    async def vault_request(method, path, payload):
        assert method == "post"
        assert payload["context"] == base64.b64encode(key.encode()).decode()
        if path == "transit/encrypt/" + key:
            ciphertext = "vault:v1:unit-" + str(len(vault_payloads))
            vault_payloads[ciphertext] = payload["plaintext"]
            return {"data": {"ciphertext": ciphertext}}
        assert path == "transit/decrypt/" + key
        return {"data": {"plaintext": vault_payloads[payload["ciphertext"]]}}

    encryption._vault_request = vault_request
    service = AppsWorkspaceRecommendationsService(directus, encryption, store=AppsRecommendationsStore(tmp_path))
    service._validate_search = lambda *_: None
    # This is the exact failing E2E order: optout before any saved search, then
    # first search create/update/reload. Real adapters verify HTTP shapes too.
    assert (await service.settings(owner, "web", False))["daily_searches_enabled"] is False
    saved = await service.save_search(owner, "web", {"skill_id": "search", "title": "Private search",
        "query": "private search text", "parameters": {"requests": [{"query": "private search text"}]}})
    assert saved["first_save"] is True and saved["daily_searches_enabled"] is False
    assert (await service.library(owner, "web"))["saved_searches"][0]["query"] == "private search text"
    assert any(method == "POST" for method, _ in requests)
    assert any(method == "PATCH" for method, _ in requests)
    assert "private search text" not in json.dumps(requests)
    schema_path = Path(__file__).resolve().parents[1] / "core/directus/schemas/apps_workspace_libraries.yml"
    fields = yaml.safe_load(schema_path.read_text())["apps_workspace_libraries"]["fields"]
    assert set(next(iter(persisted.values()))) <= set(fields)
