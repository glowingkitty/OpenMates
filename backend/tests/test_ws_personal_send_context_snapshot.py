"""Combined Personal send context remains fresh, scoped and one-use."""

import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.core.api.app.routes import websockets
from backend.core.api.app.services.directus.project_methods import hash_id
from backend.core.api.app.services.personal_send_context_snapshot import fresh_personal_project_candidates
from backend.tests.test_ws_personal_memory_snapshot import (
    REQUEST_ID, FakeCache, FakeDirectus, FakeSocket, auth_data, install_authority,
)


class ProjectDirectus:
    def __init__(self, rows, settings=None):
        self.rows = rows
        self.get_items = AsyncMock(side_effect=self._get_items)
        self.project = SimpleNamespace(get_project_settings_for_projects=AsyncMock(return_value=settings or {}))

    async def _get_items(self, collection, *, params, no_cache, raise_on_error):
        assert collection == "projects" and no_cache is True and raise_on_error is True
        assert params["filter[hashed_user_id][_eq]"] == hash_id("owner")
        assert params["filter[hashed_team_id][_null]"] is True
        assert params["filter[archived][_neq]"] is True
        assert params["limit"] == 40
        return self.rows


def project(project_id="p1", **changes):
    return {"project_id": project_id, "hashed_user_id": hash_id("owner"), "hashed_team_id": None,
            "archived": False, "encrypted_project_key": "key", "encrypted_name": "name",
            "encrypted_description": "description", **changes}


# contract-test: direct surface=rest_api assertions=auth.session.authoritative-enforcement,auth.session.isolation
def test_project_directory_filters_disabled_before_ciphertext_output():
    directus = ProjectDirectus([project("p1"), project("p2")], {
        "p1": {"auto_selection": False}, "p2": {"auto_selection": True, "focus_activation_policy": "approval"},
    })
    result = asyncio.run(fresh_personal_project_candidates(directus, "owner"))
    assert result == [{"project_id": "p2", "encrypted_project_key": "key", "encrypted_name": "name",
                       "encrypted_description": "description", "auto_selection": True,
                       "focus_activation_policy": "approval"}]
    directus.project.get_project_settings_for_projects.assert_awaited_once_with(["p1", "p2"], "owner", team_id=None)


# contract-test: direct surface=rest_api assertions=auth.session.isolation
@pytest.mark.parametrize("bad", [
    project("p1", hashed_team_id=hash_id("team")),
    project("p1", hashed_user_id=hash_id("other")),
    project("p1", archived=True),
    project("p1", encrypted_project_key=None),
])
def test_project_directory_rejects_invalid_scope_or_ciphertext(bad):
    directus = ProjectDirectus([bad])
    with pytest.raises(RuntimeError):
        asyncio.run(fresh_personal_project_candidates(directus, "owner"))
    directus.project.get_project_settings_for_projects.assert_not_awaited()


# contract-test: direct surface=rest_api assertions=auth.session.authoritative-enforcement,auth.session.isolation
def test_combined_snapshot_fresh_same_socket(monkeypatch):
    cache, directus, socket = FakeCache(), FakeDirectus(), FakeSocket()
    install_authority(monkeypatch)
    memories = AsyncMock(return_value=SimpleNamespace(model_dump=lambda mode: {
        "encrypted_settings": "opaque", "memories": [{"id": "memory"}],
    }))
    candidates = AsyncMock(return_value=[{"project_id": "p1", "encrypted_name": "opaque"}])
    monkeypatch.setattr(websockets, "_load_fresh_personal_memories", memories)
    monkeypatch.setattr(websockets, "fresh_personal_project_candidates", candidates)
    asyncio.run(websockets.handle_personal_send_context_snapshot(
        websocket=socket, payload={"request_id": REQUEST_ID}, auth_data=auth_data(),
        cache_service=cache, directus_service=directus,
    ))
    assert socket.frames == [{"type": "personal_send_context_snapshot_result", "payload": {
        "request_id": REQUEST_ID, "success": True,
        "personal_memories": {"encrypted_settings": "opaque", "memories": [{"id": "memory"}]},
        "project_candidates": [{"project_id": "p1", "encrypted_name": "opaque"}],
    }}]
    memories.assert_awaited_once_with(directus, "owner")
    candidates.assert_awaited_once_with(directus, "owner")


# contract-test: direct surface=rest_api assertions=auth.session.authoritative-enforcement
@pytest.mark.parametrize("mode", ["already_used", "malformed", "rate_limited", "limiter_unavailable", "expired", "revoked"])
def test_combined_snapshot_fails_before_private_reads(monkeypatch, mode):
    cache, directus, socket = FakeCache(), FakeDirectus(), FakeSocket()
    ledger, _ = install_authority(monkeypatch)
    memories, candidates = AsyncMock(), AsyncMock()
    monkeypatch.setattr(websockets, "_load_fresh_personal_memories", memories)
    monkeypatch.setattr(websockets, "fresh_personal_project_candidates", candidates)
    if mode == "rate_limited":
        cache.redis.counts[f"personal-memory:snapshot:session:{'a' * 64}"] = 30
    if mode == "limiter_unavailable":
        cache.redis.error = RuntimeError("down")
    if mode == "revoked":
        ledger.return_value = None
    data = auth_data(session_expires_at=int(time.time()) - 1) if mode == "expired" else auth_data()
    payload = {"request_id": REQUEST_ID, "team_id": "team"} if mode == "malformed" else {"request_id": REQUEST_ID}
    asyncio.run(websockets.handle_personal_send_context_snapshot(
        websocket=socket, payload=payload, auth_data=data, cache_service=cache, directus_service=directus,
        already_used=mode == "already_used",
    ))
    assert socket.frames[0]["payload"]["success"] is False
    assert socket.frames[0]["payload"]["error"]["code"] == {
        "already_used": "already_used", "malformed": "invalid_request", "rate_limited": "rate_limited",
        "limiter_unavailable": "unavailable", "expired": "unauthorized", "revoked": "unauthorized",
    }[mode]
    memories.assert_not_awaited()
    candidates.assert_not_awaited()
