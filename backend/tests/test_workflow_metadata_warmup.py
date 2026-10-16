"""Contract checks for the optional Workflow metadata focus hint.

Requests are scope-only and bounded per socket and user. Team membership is
checked before any cached metadata is read. A failed or duplicate hint must
not change the normal authorized cold discovery result.
"""
import pytest

from backend.core.api.app.routes.handlers.websocket_handlers.workflow_metadata_warmup_handler import (
    accept_workflow_warmup_request, warm_workflow_metadata,
)


# contract-test: supporting surface=rest_api assertions=workflows.chat.metadata-warmup
def test_warmup_rejects_text_and_limits_requests_per_socket():
    times = []
    assert accept_workflow_warmup_request(times, {"team_id": "team", "draft": "private"}) == ("invalid", None)
    assert accept_workflow_warmup_request(times, {"_traceparent": "private draft"}) == ("invalid", None)
    assert times == []
    valid_trace = "00-" + "a" * 32 + "-" + "b" * 16 + "-01"
    assert accept_workflow_warmup_request(times, {"_traceparent": valid_trace}) == ("accepted", None)
    assert [accept_workflow_warmup_request(times, {}) for _ in range(2)] == [("accepted", None)] * 2
    assert accept_workflow_warmup_request(times, {}) == ("rate_limited", None)


# contract-test: supporting surface=rest_api assertions=workflows.chat.metadata-warmup
@pytest.mark.asyncio
async def test_warmup_rechecks_team_membership_before_cache_access():
    class Team:
        async def require_team_role(self, team_id, user_id, roles):
            assert (team_id, user_id) == ("other-team", "alice")
            assert "viewer" in roles
            raise PermissionError("Team permission denied")
    class Cache:
        @property
        async def client(self):
            class Redis:
                async def set(self, key, value, **kwargs): return True
            return Redis()
        async def get_user_vault_key_id(self, user_id):
            pytest.fail("cache must not be consulted before Team authorization")
    from types import SimpleNamespace
    with pytest.raises(PermissionError):
        await warm_workflow_metadata(cache_service=Cache(), directus_service=SimpleNamespace(team=Team()),
                                     user_id="alice", team_id="other-team")


# contract-test: supporting surface=rest_api assertions=workflows.chat.metadata-warmup
@pytest.mark.asyncio
async def test_warmup_shared_rate_limit_precedes_team_lookup():
    class Redis:
        async def set(self, key, value, **kwargs): return False
        async def incr(self, key): return 7
    class Cache:
        @property
        async def client(self): return Redis()
        async def get_user_vault_key_id(self, user_id):
            pytest.fail("rate-limited warmup must not read a Vault key")
    from types import SimpleNamespace
    assert await warm_workflow_metadata(cache_service=Cache(), directus_service=SimpleNamespace(team=None),
                                        user_id="alice", team_id="other-team") == "rate_limited"


# contract-test: supporting surface=rest_api assertions=workflows.chat.metadata-warmup
@pytest.mark.asyncio
async def test_authorized_warm_hit_renews_two_hour_retention_without_discovery(monkeypatch):
    from unittest.mock import AsyncMock
    from types import SimpleNamespace
    from backend.core.api.app.routes.handlers.websocket_handlers import workflow_metadata_warmup_handler as handler
    redis = SimpleNamespace(set=AsyncMock(return_value=True), expire=AsyncMock(return_value=True))
    class Cache:
        @property
        async def client(self): return redis
        async def get_user_vault_key_id(self, user_id): return "vault"
        async def get(self, key): return {"ciphertext": "encrypted metadata"}
    monkeypatch.setattr(handler, "_versioned_workflow_metadata_key", AsyncMock(return_value="versioned-key"))
    monkeypatch.setattr(handler, "_cached_workflow_metadata", AsyncMock(return_value=[{"workflow_id": "saved"}]))
    discover = AsyncMock(side_effect=AssertionError("hit should reuse metadata"))
    monkeypatch.setattr(handler, "discover_workflow_metadata", discover)
    assert await warm_workflow_metadata(cache_service=Cache(), directus_service=SimpleNamespace(team=None),
                                       user_id="alice", team_id=None) == "ready"
    redis.expire.assert_awaited_once_with("versioned-key", 7200)
    discover.assert_not_awaited()


# contract-test: supporting surface=rest_api assertions=workflows.chat.metadata-warmup
@pytest.mark.asyncio
async def test_unreadable_workflow_cache_is_not_renewed_or_reported_ready(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from backend.core.api.app.routes.handlers.websocket_handlers import workflow_metadata_warmup_handler as handler

    redis = SimpleNamespace(
        set=AsyncMock(return_value=True),
        expire=AsyncMock(return_value=True),
        eval=AsyncMock(return_value=1),
    )
    class Cache:
        @property
        async def client(self): return redis
        async def get_user_vault_key_id(self, user_id): return "vault"

    monkeypatch.setattr(handler, "_versioned_workflow_metadata_key", AsyncMock(return_value="versioned-key"))
    monkeypatch.setattr(handler, "_cached_workflow_metadata", AsyncMock(return_value=None))
    discover = AsyncMock(return_value=[])
    monkeypatch.setattr(handler, "discover_workflow_metadata", discover)
    assert await warm_workflow_metadata(
        cache_service=Cache(), directus_service=SimpleNamespace(team=None),
        user_id="alice", team_id=None,
    ) == "unavailable"
    redis.expire.assert_not_awaited()
    discover.assert_awaited_once()


# contract-test: supporting surface=rest_api assertions=workflows.chat.metadata-warmup
@pytest.mark.asyncio
async def test_generation_change_during_discovery_does_not_report_ready(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from backend.core.api.app.routes.handlers.websocket_handlers import workflow_metadata_warmup_handler as handler

    redis = SimpleNamespace(set=AsyncMock(return_value=True), eval=AsyncMock(return_value=1))
    class Cache:
        @property
        async def client(self): return redis
        async def get_user_vault_key_id(self, user_id): return "vault"

    monkeypatch.setattr(handler, "_versioned_workflow_metadata_key", AsyncMock(side_effect=["old-key", "new-key"]))
    monkeypatch.setattr(handler, "_cached_workflow_metadata", AsyncMock(return_value=None))
    monkeypatch.setattr(handler, "discover_workflow_metadata", AsyncMock(return_value=[{"workflow_id": "old"}]))
    assert await warm_workflow_metadata(
        cache_service=Cache(), directus_service=SimpleNamespace(team=None),
        user_id="alice", team_id=None,
    ) == "unavailable"


# contract-test: supporting surface=rest_api assertions=workflows.chat.metadata-warmup
@pytest.mark.asyncio
async def test_personal_warmup_primes_versioned_ciphertext_project_index(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from backend.core.api.app.routes.handlers.websocket_handlers import workflow_metadata_warmup_handler as handler

    class Redis:
        def __init__(self):
            self.expired = []
        async def set(self, key, value, **kwargs):
            return True
        async def expire(self, key, ttl):
            self.expired.append((key, ttl))

    class Cache:
        def __init__(self):
            self.redis = Redis()
            self.entries = {}
            self.vault_key_id = "vault-epoch-1"
        @property
        async def client(self):
            return self.redis
        async def get_user_vault_key_id(self, user_id):
            assert user_id == "alice"
            return self.vault_key_id
        async def get(self, key):
            return self.entries.get(key)
        async def set(self, key, value, ttl):
            assert ttl == 7200
            self.entries[key] = value

    class Directus:
        def __init__(self):
            self.rows = [{
                "project_id": "p1", "version": 1, "updated_at": "r1",
                "archived": False, "encrypted_name": "ciphertext-name",
                "encrypted_project_key": "fresh-wrapper", "private_body": "private-body",
            }]
            self.project = SimpleNamespace(list_projects=self.list_projects)
            self.list_count = 0
        async def list_projects(self, user_id, team_id=None):
            assert (user_id, team_id) == ("alice", None)
            self.list_count += 1
            return [row.copy() for row in self.rows]
        async def get_items(self, collection, params, **kwargs):
            assert kwargs == {"no_cache": True, "raise_on_error": True}
            assert "filter[hashed_user_id][_eq]" in params
            assert params["filter[hashed_team_id][_null]"] is True
            if collection == "projects":
                return [row.copy() for row in self.rows]
            assert collection == "project_items"
            return []

    cache, directus = Cache(), Directus()
    monkeypatch.setattr(handler, "_versioned_workflow_metadata_key", AsyncMock(return_value="workflow-key"))
    monkeypatch.setattr(handler, "_cached_workflow_metadata", AsyncMock(return_value=[{"workflow_id": "saved"}]))
    monkeypatch.setattr(handler, "discover_workflow_metadata", AsyncMock(side_effect=AssertionError("workflow hit")))

    async def warm():
        return await warm_workflow_metadata(
            cache_service=cache, directus_service=directus, user_id="alice", team_id=None,
        )

    assert await warm() == "ready"
    project_entries = {key: value for key, value in cache.entries.items() if key.startswith("project:discovery:encrypted:v1:") and ":focus:" not in key}
    assert len(project_entries) == 1
    assert next(iter(project_entries.values()))["rows"] == [{
        "project_id": "p1", "version": 1, "updated_at": "r1", "archived": False,
        "encrypted_name": "ciphertext-name",
    }]
    assert "fresh-wrapper" not in str(cache.entries)
    assert "private-body" not in str(cache.entries)

    # A second hint reads the fresh scoped watermark and extends the index TTL.
    assert await warm() == "ready"
    assert directus.list_count == 1
    project_key = next(iter(project_entries))
    assert (project_key, 7200) in cache.redis.expired

    # A revision changes the watermark; a new Vault epoch cannot reuse old entries.
    directus.rows[0].update(version=2, updated_at="r2", encrypted_name="new-ciphertext")
    assert await warm() == "ready"
    assert directus.list_count == 2
    assert cache.entries[project_key]["rows"][0]["encrypted_name"] == "new-ciphertext"
    cache.vault_key_id = "vault-epoch-2"
    assert await warm() == "ready"
    assert directus.list_count == 3
    assert len([key for key in cache.entries if key.startswith("project:discovery:encrypted:v1:") and ":focus:" not in key]) == 2


# contract-test: supporting surface=rest_api assertions=workflows.chat.metadata-warmup
@pytest.mark.asyncio
async def test_project_warm_failure_does_not_block_workflow_metadata(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from backend.core.api.app.routes.handlers.websocket_handlers import workflow_metadata_warmup_handler as handler

    redis = SimpleNamespace(set=AsyncMock(return_value=True), expire=AsyncMock(return_value=True))
    class Cache:
        @property
        async def client(self): return redis
        async def get_user_vault_key_id(self, user_id): return "vault"
        async def get(self, key): return None
    class Project:
        async def list_projects(self, user_id, team_id=None):
            raise RuntimeError("Project discovery unavailable")
    monkeypatch.setattr(handler, "_versioned_workflow_metadata_key", AsyncMock(return_value="workflow-key"))
    monkeypatch.setattr(handler, "_cached_workflow_metadata", AsyncMock(return_value=[{"workflow_id": "saved"}]))
    assert await warm_workflow_metadata(
        cache_service=Cache(), directus_service=SimpleNamespace(team=None, project=Project()),
        user_id="alice", team_id=None,
    ) == "ready"
    redis.expire.assert_awaited_once_with("workflow-key", 7200)
