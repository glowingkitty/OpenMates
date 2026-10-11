"""Fresh private-chat and workspace authority for internal recent-work IPC."""

# contract-test-file: infrastructure

from __future__ import annotations

import hashlib
import sys
import time
from types import ModuleType

import httpx
import pytest
from fastapi import FastAPI

from backend.core.api.app.routes import recent_work_internal
from backend.core.api.app.utils import internal_auth
from backend.shared.python_utils.recent_work_summary_cache import (
    RecentWorkSummaryCache, TransientContextHandoffStore,
)
from backend.shared.python_utils.recent_work_summary_client import RecentWorkSummaryClient


def hashed(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def direct_row(chat_id: str, *, team: str = "team-a", participants=("alice", "bob")) -> dict:
    hashes = [hashed(user) for user in participants]
    return {
        "id": chat_id, "hashed_user_id": hashed("bob"), "hashed_team_id": hashed(team),
        "chat_visibility": "direct", "participant_user_hashes": hashes,
        "participant_key_envelopes": {
            member: {"key_id": "key-1", "encrypted_chat_key": "OMDM1.abcdefghijklmnop"}
            for member in hashes
        },
        "encrypted_chat_key": None,
    }


class Encryption:
    def __init__(self):
        self.plaintext = {}
        self.decrypt_calls = []
        self.on_decrypt = None

    async def encrypt_with_user_key(self, text, key):
        cipher = f"vault:v1:cipher-{len(self.plaintext)}"
        self.plaintext[(cipher, key)] = text
        return cipher, "v1"

    async def decrypt_with_user_key(self, cipher, key):
        self.decrypt_calls.append(cipher)
        if self.on_decrypt:
            self.on_decrypt()
        return self.plaintext.get((cipher, key))


class Directus:
    def __init__(self):
        self.rows = {
            "personal-current": {"id": "personal-current", "hashed_user_id": hashed("alice"), "hashed_team_id": None},
            "personal": {"id": "personal", "hashed_user_id": hashed("alice"), "hashed_team_id": None},
            "other-personal": {"id": "other-personal", "hashed_user_id": hashed("bob"), "hashed_team_id": None},
            "team-a-current": {"id": "team-a-current", "hashed_user_id": hashed("bob"), "hashed_team_id": hashed("team-a")},
            "team-a": {"id": "team-a", "hashed_user_id": hashed("bob"), "hashed_team_id": hashed("team-a")},
            "team-b-current": {"id": "team-b-current", "hashed_user_id": hashed("bob"), "hashed_team_id": hashed("team-b")},
            "team-b": {"id": "team-b", "hashed_user_id": hashed("bob"), "hashed_team_id": hashed("team-b")},
            "direct": direct_row("direct"),
        }
        self.members = {("alice", "team-a"), ("alice", "team-b"), ("bob", "team-a"),
                        ("admin", "team-a")}
        self.active_teams = {"team-a", "team-b"}

    async def get_items(self, collection, params, **kwargs):
        assert kwargs == {"no_cache": True, "admin_required": True}
        if collection == "chats":
            return [self.rows[chat] for chat in params["filter[id][_in]"].split(",") if chat in self.rows]
        team_hashes = (params.get("filter[hashed_team_id][_in]") or
                       params.get("filter[hashed_team_id][_eq]")).split(",")
        if collection == "team_memberships":
            actor_hash = params["filter[hashed_user_id][_eq]"]
            matched = [team for actor, team in self.members
                       if hashed(actor) == actor_hash and hashed(team) in team_hashes]
        else:
            assert collection == "teams"
            matched = [team for team in self.active_teams if hashed(team) in team_hashes]
        return [{"hashed_team_id": hashed(team), "id": team} for team in matched]


class Cache:
    def __init__(self):
        self.tasks = {chat: f"task-{chat}" for chat in
                      ("personal-current", "personal", "other-personal", "team-a-current",
                       "team-a", "team-b-current", "team-b", "direct")}

    async def get_active_ai_task(self, chat):
        return self.tasks.get(chat)

    async def get_active_ai_tasks(self, chats):
        return {chat: self.tasks[chat] for chat in chats if chat in self.tasks}

    async def get_user_vault_key_id(self, owner):
        return f"key-{owner}"

    async def get(self, key):
        return "turn"


def runtime(monkeypatch):
    continuation = ModuleType("backend.apps.ai.tasks.async_skill_continuation")
    continuation.async_skill_latest_user_turn_key = lambda owner, chat: f"latest:{owner}:{chat}"
    monkeypatch.setitem(sys.modules, continuation.__name__, continuation)
    app = FastAPI()
    app.include_router(recent_work_internal.router)
    app.state.directus_service = Directus()
    app.state.cache_service = Cache()
    app.state.encryption_service = Encryption()
    monkeypatch.setattr(recent_work_internal, "recent_work_summary_cache", RecentWorkSummaryCache())
    monkeypatch.setattr(recent_work_internal, "transient_context_handoff_store", TransientContextHandoffStore())
    monkeypatch.setattr(internal_auth, "INTERNAL_API_SHARED_TOKEN", "service-token")
    client = RecentWorkSummaryClient(base_url="http://runtime", token="service-token",
                                     transport=httpx.ASGITransport(app=app))
    return app, client


async def put_sources(app):
    for chat in ("personal", "other-personal", "team-a", "team-b", "direct"):
        assert await recent_work_internal.recent_work_summary_cache.put(
            owner_id="alice", chat_id=chat, project_id=None, revision=f"r-{chat}",
            text=f"summary from {chat}", vault_key_id="key-alice",
            encryption=app.state.encryption_service, authorized=True,
            assistant_completed_at=time.time(),
        )


# contract-test: supporting surface=rest_api assertions=teams.direct-chat.participant-isolation,teams.context.full-switch-local
@pytest.mark.asyncio
async def test_related_work_never_decrypts_direct_source_and_stays_in_current_workspace(monkeypatch):
    app, client = runtime(monkeypatch)
    await put_sources(app)
    encryption = app.state.encryption_service

    for current, expected in (("personal-current", "personal"), ("team-a-current", "team-a"),
                              ("team-b-current", "team-b"), ("direct", "team-a")):
        encryption.decrypt_calls.clear()
        result = await client.read(owner_id="alice", current_chat_id=current, task_id=f"task-{current}",
                                   authorized_chat_ids=["personal", "other-personal", "team-a", "team-b", "direct"])
        assert [(item.source.chat_id, item.text) for item in result] == [(expected, f"summary from {expected}")]
        assert len(encryption.decrypt_calls) == 1


# contract-test: supporting surface=rest_api assertions=teams.direct-chat.participant-isolation,teams.context.full-switch-local
@pytest.mark.asyncio
async def test_noncreator_participant_can_use_current_direct_context_but_outsider_and_admin_cannot(monkeypatch):
    app, client = runtime(monkeypatch)
    assert await client.write(owner_id="alice", chat_id="direct", task_id="task-direct", revision="r1",
                              text="current direct work", assistant_completed_at=time.time())
    binding = dict(owner_id="alice", chat_id="direct", turn_id="turn", request_id="request")
    reference = await client.seal_context(**binding, fields={"related_task_candidates": []})
    assert reference and await client.open_context(**binding, reference=reference) == {"related_task_candidates": []}

    for actor in ("outsider", "admin"):
        app.state.cache_service.tasks["direct"] = "task-direct"
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://runtime") as raw:
            response = await raw.post("/internal/recent-work/read", headers={"X-Internal-Service-Token": "service-token"},
                                      json={"owner_id": actor, "current_chat_id": "direct", "task_id": "task-direct"})
        assert response.status_code == 403


# contract-test: supporting surface=rest_api assertions=teams.direct-chat.participant-isolation,teams.context.full-switch-local
@pytest.mark.asyncio
async def test_removed_member_inactive_team_and_malformed_private_metadata_fail_closed(monkeypatch):
    app, client = runtime(monkeypatch)
    directus = app.state.directus_service
    await put_sources(app)
    directus.members.remove(("alice", "team-a"))
    assert await client.read(owner_id="alice", current_chat_id="direct", task_id="task-direct",
                             authorized_chat_ids=["team-a"]) == []
    assert await client.read(owner_id="alice", current_chat_id="team-a", task_id="task-team-a",
                             authorized_chat_ids=["team-a"]) == []
    directus.members.add(("alice", "team-a"))
    directus.active_teams.remove("team-a")
    assert await client.read(owner_id="alice", current_chat_id="direct", task_id="task-direct",
                             authorized_chat_ids=["team-a"]) == []
    directus.active_teams.add("team-a")
    directus.rows["direct"]["participant_user_hashes"] = [hashed("alice"), hashed("alice")]
    assert await client.read(owner_id="alice", current_chat_id="direct", task_id="task-direct",
                             authorized_chat_ids=["team-a"]) == []
    assert app.state.encryption_service.decrypt_calls == []


# contract-test: supporting surface=rest_api assertions=teams.direct-chat.participant-isolation,teams.context.full-switch-local
@pytest.mark.asyncio
async def test_scope_change_during_vault_decrypt_discards_summary(monkeypatch):
    app, client = runtime(monkeypatch)
    await put_sources(app)
    def revoke_team():
        app.state.directus_service.members.remove(("alice", "team-a"))
        app.state.encryption_service.on_decrypt = None
    app.state.encryption_service.on_decrypt = revoke_team
    assert await client.read(owner_id="alice", current_chat_id="direct", task_id="task-direct",
                             authorized_chat_ids=["team-a"]) == []
