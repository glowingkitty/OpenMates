"""Hosted sandbox executor and write-back: fall-through rules, two-device merge, authorization scope."""
import json
import logging
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from backend.apps.ai.processing import project_sandbox_executor as executor
from backend.core.api.app.services import project_sandbox_writeback as writeback
from backend.core.api.app.services.project_sandbox_service import ProjectSandboxUnavailable
from backend.core.api.app.services.project_write_authorization_service import (
    ProjectWriteAuthorizationError,
    ProjectWriteAuthorizationService,
    PROJECT_WRITE_APPROVAL_TTL_SECONDS,
)

SECRET_TEXT = "SECRET-FILE-CONTENT-123"
GRANT = "GRANT-SYNTHETIC-777"


class FakeCache:
    def __init__(self):
        self.store = {}
        self.events = []

    @property
    async def client(self):
        return SimpleNamespace(publish=self._publish)

    async def _publish(self, channel, message):
        self.events.append((channel, json.loads(message)))

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value, ttl=None):
        self.store[key] = value
        return True

    async def get_and_delete(self, key):
        return self.store.pop(key, None)


class FakeDirectus:
    """Stands in for the Directus extension: commits only when expected_revision equals the stored head."""

    base_url = "http://directus.example.org"

    def __init__(self):
        self.revisions = {"e1": 1}
        self.commits = []

    async def _make_api_request(self, method, url, headers=None, json=None):
        embed_id, expected = json["embed_id"], json["expected_revision"]
        current = self.revisions.get(embed_id, 0)
        if current != expected:
            body = {"data": {"status": "conflict", "embed_id": embed_id, "current_revision": current}}
        else:
            self.revisions[embed_id] = current + 1
            self.commits.append(json)
            body = {"data": {"status": "committed", "embed_id": embed_id, "current_revision": current + 1}}
        return SimpleNamespace(status_code=200, json=lambda: body)


class FakeClient:
    def __init__(self, merge_status="merged", directus=None):
        self.calls = []
        self.merge_status = merge_status
        self.directus = directus

    async def call(self, endpoint, body=None, timeout=None):
        self.calls.append((endpoint, body))
        if endpoint == "/v1/merge":
            if self.merge_status == "conflict":
                return {"status": "conflict", "conflict_text": "<<<<<<< ours\nline\n>>>>>>> theirs"}
            head_version = body["head"]["version"]
            return {"status": "merged", "revision": {"path": body["path"], "embed_id": "e1",
                    "transaction": {"expected_revision": head_version, "head": {"c": "merged"},
                                    "proposal_digest": "b" * 64}}}
        if endpoint == "/v1/op":
            return {"result": {"status": "completed", "message": "ok"}, "revisions": [self.rev(1)]}
        return {"ok": True}

    @staticmethod
    def rev(expected):
        return {"path": "a.txt", "embed_id": "e1", "base_version": expected, "kind": "update",
                "transaction": {"expected_revision": expected, "head": {"c": "ours"},
                                "proposal_digest": "a" * 64}}


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("INTERNAL_API_SHARED_TOKEN", "token")

    async def decision(self, *, user_id, chat_id, project_id, team_id):
        if chat_id != "chat-1":
            raise ProjectWriteAuthorizationError("PROJECT_FOCUS_REQUIRED")
        return {"write_mode": "apply_and_show", "focus_id_hash": "f", "settings_revision": "s"}

    monkeypatch.setattr(ProjectWriteAuthorizationService, "_current_write_decision", decision)


def make_head_loader(directus):
    async def loader(**kwargs):
        return {"version": directus.revisions[kwargs["embed_id"]]}
    return loader


async def run_commit(client, directus, cache, revs):
    return await writeback.commit_revisions(
        SimpleNamespace(client=client), revs, user_id="u1", chat_id="chat-1", project_id="p1", team_id=None,
        operation_id="op-1", directus_service=directus, cache_service=cache,
        head_loader=make_head_loader(directus))


# contract-test: direct surface=rest_api assertions=projects.sandbox.jobs
@pytest.mark.asyncio
async def test_clean_commit_tells_daemon_and_devices():
    directus, cache, client = FakeDirectus(), FakeCache(), FakeClient()
    result = await run_commit(client, directus, cache, [client.rev(1)])
    assert result.committed == ["a.txt"] and directus.revisions["e1"] == 2
    assert ("/v1/committed", {"path": "a.txt", "embed_id": "e1", "version_number": 2}) in client.calls
    channel, event = cache.events[0]
    assert channel == "user_cache_events:u1" and event["event_type"] == "send_embed_revision_committed"
    assert event["payload"] == {"embed_id": "e1", "current_revision": 2, "operation_id": "op-1",
                                "chat_id": "chat-1", "kind": "update", "source": "project_sandbox"}
    assert "a.txt" not in json.dumps(event)  # paths are private
    assert directus.commits[0]["chat_id"] == "chat-1" and directus.commits[0]["operation_id"] == "op-1"
    assert directus.commits[0]["proposal_digest"] == "a" * 64  # the sandbox's digest, not recomputed
    assert directus.commits[0]["origin"] == "project_sandbox"  # Project-wrapper-only creates allowed


# contract-test: direct surface=rest_api assertions=projects.sandbox.write-back
@pytest.mark.asyncio
async def test_two_devices_stale_base_is_merged_on_top_and_other_edit_kept():
    directus, cache, client = FakeDirectus(), FakeCache(), FakeClient()
    directus.revisions["e1"] = 2  # another device committed meanwhile
    result = await run_commit(client, directus, cache, [client.rev(1)])
    assert result.merged == ["a.txt"] and not result.conflicts
    assert [c[0] for c in client.calls][0] == "/v1/merge"
    assert directus.commits == [directus.commits[0]] and directus.commits[0]["expected_revision"] == 2
    assert directus.revisions["e1"] == 3  # the other device's revision 2 stays underneath


# contract-test: direct surface=rest_api assertions=projects.sandbox.write-back
@pytest.mark.asyncio
async def test_real_conflict_commits_nothing_and_is_returned():
    directus, cache, client = FakeDirectus(), FakeCache(), FakeClient(merge_status="conflict")
    directus.revisions["e1"] = 2
    result = await run_commit(client, directus, cache, [client.rev(1)])
    assert directus.commits == [] and directus.revisions["e1"] == 2
    assert result.conflicts[0]["path"] == "a.txt" and "ours" in result.conflicts[0]["conflict_text"]
    assert cache.events == []


# contract-test: direct surface=rest_api assertions=projects.sandbox.write-back
@pytest.mark.asyncio
async def test_authorization_record_not_consumable_from_another_chat():
    cache = FakeCache()
    auth = ProjectWriteAuthorizationService(FakeDirectus(), cache)
    digest = "a" * 64
    await auth.authorize_sandbox_write(user_id="u1", chat_id="chat-1", project_id="p1",
                                       operation_id="op-1", proposal_digest=digest)
    with pytest.raises(ProjectWriteAuthorizationError):
        await auth.consume_sandbox_write(user_id="u1", chat_id="chat-2", project_id="p1",
                                         operation_id="op-1", proposal_digest=digest)
    with pytest.raises(ProjectWriteAuthorizationError):
        await auth.consume_sandbox_write(user_id="u2", chat_id="chat-1", project_id="p1",
                                         operation_id="op-1", proposal_digest=digest)
    await auth.consume_sandbox_write(user_id="u1", chat_id="chat-1", project_id="p1",
                                     operation_id="op-1", proposal_digest=digest)
    with pytest.raises(ProjectWriteAuthorizationError):  # single use
        await auth.consume_sandbox_write(user_id="u1", chat_id="chat-1", project_id="p1",
                                         operation_id="op-1", proposal_digest=digest)
    assert PROJECT_WRITE_APPROVAL_TTL_SECONDS > 0


# contract-test: direct surface=rest_api assertions=projects.sandbox.write-back
@pytest.mark.asyncio
async def test_always_ask_mode_refuses_sandbox_write(monkeypatch):
    async def decision(self, **kwargs):
        return {"write_mode": "always_ask", "focus_id_hash": "f", "settings_revision": "s"}
    monkeypatch.setattr(ProjectWriteAuthorizationService, "_current_write_decision", decision)
    directus, cache, client = FakeDirectus(), FakeCache(), FakeClient()
    result = await run_commit(client, directus, cache, [client.rev(1)])
    assert directus.commits == [] and result.rejected[0]["code"] == "PROJECT_WRITE_APPROVAL_REQUIRED"


# -- executor ---------------------------------------------------------------------------

class FakeService:
    def __init__(self, client=None, error=None):
        self.client, self.error, self.touched = client, error, 0

    async def ensure_ready(self, **kwargs):
        if self.error:
            raise self.error
        return SimpleNamespace(client=self.client)

    async def touch(self, **kwargs):
        self.touched += 1


def request():
    return SimpleNamespace(user_id="u1", chat_id="chat-1")


async def run_exec(monkeypatch, decision, service, focus=None, directus=None, cache=None):
    async def get_decision(user_id, directus_service=None):
        if isinstance(decision, Exception):
            raise decision
        return {"decision": decision}
    monkeypatch.setattr(executor.e2b_upload_consent, "get_decision", get_decision)
    directus = directus or FakeDirectus()
    return await executor.run_project_tool_in_sandbox(
        request_data=request(), operation="update_file", operation_arguments={"path": "a.txt", "content": SECRET_TEXT},
        dispatch_focus=focus or {"project_id": "p1"}, cache_service=cache or FakeCache(),
        directus_service=directus, log_prefix="[t]", sandbox_service=service,
        head_loader=make_head_loader(directus))


# contract-test: direct surface=rest_api assertions=projects.sandbox.device-fallback
@pytest.mark.asyncio
@pytest.mark.parametrize("decision", ["declined", None])
async def test_falls_through_without_allowed_consent(monkeypatch, decision):
    assert await run_exec(monkeypatch, decision, FakeService(FakeClient())) is None


# contract-test: direct surface=rest_api assertions=projects.sandbox.device-fallback
@pytest.mark.asyncio
async def test_falls_through_when_consent_unavailable(monkeypatch):
    assert await run_exec(monkeypatch, HTTPException(503), FakeService(FakeClient())) is None


# contract-test: direct surface=rest_api assertions=projects.sandbox.device-fallback
@pytest.mark.asyncio
async def test_falls_through_for_remote_source(monkeypatch):
    assert await run_exec(monkeypatch, "allowed", FakeService(FakeClient()),
                          focus={"project_id": "p1", "source_id": "s1"}) is None


# contract-test: direct surface=rest_api assertions=projects.sandbox.device-fallback
@pytest.mark.asyncio
async def test_falls_through_when_unavailable_and_logs_no_content(monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    service = FakeService(error=ProjectSandboxUnavailable("no_device"))
    assert await run_exec(monkeypatch, "allowed", service) is None
    assert "no_device" in caplog.text and SECRET_TEXT not in caplog.text


# contract-test: direct surface=rest_api assertions=projects.sandbox.jobs
@pytest.mark.asyncio
async def test_happy_path_returns_envelope_with_write_back(monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    directus, cache, client = FakeDirectus(), FakeCache(), FakeClient()
    service = FakeService(client)
    result = await run_exec(monkeypatch, "allowed", service, directus=directus, cache=cache)
    assert result["status"] == "completed" and result["operation"] == "update_file" and result["operation_id"]
    assert result["write_back"]["committed"] == ["a.txt"] and directus.revisions["e1"] == 2
    assert service.touched == 1
    assert ("/v1/op", {"operation": "update_file", "arguments": {"path": "a.txt", "content": SECRET_TEXT}}) in client.calls
    assert SECRET_TEXT not in caplog.text and GRANT not in caplog.text


def rev_for(embed, path, expected, digest="c"):
    return {"path": path, "embed_id": embed, "base_version": expected, "kind": "update",
            "transaction": {"expected_revision": expected, "head": {"c": path}, "proposal_digest": digest * 64}}


# contract-test: direct surface=rest_api assertions=projects.sandbox.write-back
@pytest.mark.asyncio
async def test_revisions_are_committed_in_order_each_followed_by_committed():
    directus, cache, client = FakeDirectus(), FakeCache(), FakeClient()
    directus.revisions["e1"] = 1
    first, second = rev_for("e1", "a.txt", 1, "a"), rev_for("e1", "a.txt", 2, "b")
    result = await run_commit(client, directus, cache, [first, second])
    assert result.committed == ["a.txt", "a.txt"] and directus.revisions["e1"] == 3
    assert [c["expected_revision"] for c in directus.commits] == [1, 2]
    assert [c[1]["version_number"] for c in client.calls if c[0] == "/v1/committed"] == [2, 3]


# contract-test: direct surface=rest_api assertions=projects.sandbox.write-back
@pytest.mark.asyncio
async def test_later_revisions_of_a_failed_path_are_skipped():
    directus, cache, client = FakeDirectus(), FakeCache(), FakeClient()
    bad = rev_for("e1", "a.txt", 1)
    del bad["transaction"]["proposal_digest"]
    result = await run_commit(client, directus, cache, [bad, rev_for("e1", "a.txt", 2)])
    assert [r["code"] for r in result.rejected] == ["invalid_revision", "skipped_after_failure"]
    assert directus.commits == []


# contract-test: direct surface=rest_api assertions=projects.sandbox.write-back
@pytest.mark.asyncio
async def test_merge_with_no_revision_counts_as_merged_and_commits_nothing():
    directus, cache, client = FakeDirectus(), FakeCache(), FakeClient()
    directus.revisions["e1"] = 2
    original = client.call

    async def call(endpoint, body=None, timeout=None):
        if endpoint == "/v1/merge":
            client.calls.append((endpoint, body))
            return {"status": "merged", "revision": None}
        return await original(endpoint, body, timeout)

    client.call = call
    result = await run_commit(client, directus, cache, [client.rev(1)])
    assert result.merged == ["a.txt"] and directus.commits == [] and cache.events == []


class ItemDirectus(FakeDirectus):
    """Records Project-item operations; Project and item ownership as in the routes."""

    def __init__(self, role="owner", own_item=True, project=True):
        super().__init__()
        self.ops = []
        self.project = SimpleNamespace(get_project=self._project, get_item=self._item)
        self.team = SimpleNamespace(require_team_role=self._role)
        self._have_project, self._own, self._role_name = project, own_item, role

    async def _project(self, project_id, user_id, team_id=None):
        return {"id": project_id} if self._have_project and user_id == "u1" else None

    async def _item(self, project_id, item_id, user_id, team_id=None):
        from backend.core.api.app.routes.project_item_links import hash_id
        return {"attached_by_user_hash": hash_id("u1" if self._own else "someone-else")}

    async def _role(self, team_id, user_id, roles):
        return {"role": self._role_name}

    async def _make_api_request(self, method, url, headers=None, json=None):
        self.ops.append((url.rsplit("/", 1)[-1], json))
        return SimpleNamespace(status_code=200, json=lambda: {"data": {"operation_id": json["operation_id"]}})


def item_rev(kind, action, body):
    return {"path": "a.txt", "embed_id": "e1", "kind": kind, "base_version": 1,
            "transaction": {"action": action, "item_id": "item-1", "body": body, "proposal_digest": "d" * 64}}


DELETE_BODY = {"operation_id": "op-del"}
RENAME_BODY = {"operation_id": "op-mv", "new_project_item_id": "5b9f6d52-3c1c-5a4e-8f0a-0a1b2c3d4e5f",
               "encrypted_display_name": "ct1", "encrypted_metadata": "ct2"}


async def run_items(directus, cache, revs, user_id="u1", team_id=None):
    pytest.importorskip("google.genai", reason="the route module needs the backend image dependencies")
    client = FakeClient()
    result = await writeback.commit_revisions(
        SimpleNamespace(client=client), revs, user_id=user_id, chat_id="chat-1", project_id="p1",
        team_id=team_id, operation_id="op-1", directus_service=directus, cache_service=cache)
    return result, client


# contract-test: direct surface=rest_api assertions=projects.sandbox.write-back
@pytest.mark.asyncio
async def test_delete_and_move_call_the_item_service_and_broadcast_kind():
    directus, cache = ItemDirectus(), FakeCache()
    result, _ = await run_items(directus, cache, [item_rev("delete", "delete", DELETE_BODY),
                                                  item_rev("move", "rename", RENAME_BODY)])
    assert result.committed == ["a.txt", "a.txt"] and [op[0] for op in directus.ops] == ["delete", "rename"]
    assert directus.ops[0][1]["project_item_id"] == "item-1" and directus.ops[0][1]["project_id"] == "p1"
    kinds = [event["payload"]["kind"] for _channel, event in cache.events]
    assert kinds == ["delete", "move"]
    assert all(e["payload"]["source"] == "project_sandbox" for _c, e in cache.events)


# contract-test: direct surface=rest_api assertions=projects.sandbox.write-back
@pytest.mark.asyncio
async def test_delete_refused_for_foreign_user_and_for_team_member_not_owning_the_item():
    cache = FakeCache()
    result, _ = await run_items(ItemDirectus(), cache, [item_rev("delete", "delete", DELETE_BODY)], user_id="u2")
    assert result.committed == [] and result.rejected[0]["code"] in {"project_not_found", "forbidden"}
    team = ItemDirectus(role="member", own_item=False)
    result, _ = await run_items(team, cache, [item_rev("delete", "delete", DELETE_BODY)], team_id="t1")
    assert result.rejected[0]["code"] == "forbidden" and team.ops == []


# contract-test: direct surface=rest_api assertions=projects.sandbox.write-back
@pytest.mark.asyncio
async def test_item_transaction_needs_matching_action_digest_and_valid_body():
    directus, cache = ItemDirectus(), FakeCache()
    wrong = item_rev("delete", "rename", DELETE_BODY)
    nodigest = item_rev("delete", "delete", DELETE_BODY)
    del nodigest["transaction"]["proposal_digest"]
    badbody = item_rev("move", "rename", {"operation_id": "op-x"})
    result, _ = await run_items(directus, cache, [wrong, nodigest, badbody])
    assert directus.ops == [] and len(result.rejected) == 3



# contract-test: direct surface=rest_api assertions=projects.sandbox.jobs
@pytest.mark.asyncio
async def test_client_commit_payload_cannot_claim_sandbox_origin():
    """Only the server's sandbox write-back may mark an origin; a relayed client payload is refused unsent."""
    from backend.core.api.app.services.embed_version_transaction_service import (
        EmbedVersionTransactionError,
        EmbedVersionTransactionService,
    )

    directus = FakeDirectus()
    service = EmbedVersionTransactionService(directus)
    with pytest.raises(EmbedVersionTransactionError) as refused:
        await service.commit({"embed_id": "e1", "origin": "project_sandbox"}, user_id="u1")
    assert refused.value.code == "invalid_origin" and directus.commits == []


# contract-test: direct surface=rest_api assertions=projects.sandbox.jobs
@pytest.mark.asyncio
async def test_operations_the_sandbox_does_not_run_keep_the_device_path():
    """A Project Timeline commit is not a sandbox op: the executor answers None before touching consent."""

    class NoDirectus:
        def __getattr__(self, name):
            raise AssertionError("consent must not be read for a device-path operation")

    request = SimpleNamespace(user_id="u1", chat_id="chat-1")
    for operation in ("commit", "apply_changes"):
        assert await executor.run_project_tool_in_sandbox(
            request_data=request, operation=operation, operation_arguments={},
            dispatch_focus={"project_id": "p1"}, cache_service=None, directus_service=NoDirectus(),
            log_prefix="t",
        ) is None
    assert executor.SANDBOX_OPERATIONS >= {"read_text", "update_file", "create_file"}
