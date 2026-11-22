"""Hosted Project sandbox service, key relay and reaper against a fake E2B and a fake daemon."""
import asyncio
import json
import logging
import time
from types import SimpleNamespace

import httpx
import pytest

from backend.core.api.app.routes.handlers.websocket_handlers import project_sandbox_key_grant_handler as handler
from backend.core.api.app.services import project_sandbox_service as svc
from backend.shared.providers import e2b_project_sandbox as provider
from backend.shared.providers.e2b_project_sandbox import ProjectSandboxError

SEALED = "SEALED-GRANT-SYNTHETIC-9f3a7c1d"


class FakePubSub:
    def __init__(self, redis):
        self.redis, self.queue, self.channels = redis, asyncio.Queue(), set()

    async def subscribe(self, channel):
        self.channels.add(channel)
        self.redis.subscribers.append((channel, self))

    async def unsubscribe(self, channel):
        self.channels.discard(channel)

    async def aclose(self):
        return None

    async def get_message(self, ignore_subscribe_messages=True, timeout=0.0):
        try:
            return await asyncio.wait_for(self.queue.get(), timeout)
        except asyncio.TimeoutError:
            return None


class FakeRedis:
    def __init__(self, store, device_answer=None):
        self.store, self.subscribers, self.published, self.device_answer = store, [], [], device_answer

    def pubsub(self):
        return FakePubSub(self)

    async def publish(self, channel, message):
        self.published.append((channel, message))
        for name, sub in self.subscribers:
            if name == channel:
                sub.queue.put_nowait({"data": message})
        if channel.startswith("user_cache_events:") and self.device_answer:
            request = json.loads(message)["payload"]
            await self.publish(svc.key_grant_channel(request["request_id"]), json.dumps(self.device_answer))

    async def scan_iter(self, match):
        prefix = match.rstrip("*")
        for key in list(self.store):
            if key.startswith(prefix):
                yield key


class FakeCache:
    def __init__(self, device_answer=None):
        self.store, self.writes = {}, []
        self.redis = FakeRedis(self.store, device_answer)

    @property
    async def client(self):
        return self.redis

    async def get(self, key):
        value = self.store.get(key)
        return json.loads(value) if value else None

    async def set(self, key, value, ttl=None):
        self.writes.append((key, json.dumps(value)))
        self.store[key] = json.dumps(value)
        return True

    async def delete(self, key):
        return self.store.pop(key, None) is not None


class FakeProject:
    async def list_items(self, project_id, user_id, team_id=None):
        return [{"project_item_id": "i1"}]


@pytest.fixture
def world(monkeypatch):
    state = SimpleNamespace(created=0, killed=[], calls=[], has_key=False, running={}, charges=[])

    def daemon(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        body = json.loads(request.content) if request.content else None
        state.calls.append((path, body))
        if path == "/v1/hello":
            return httpx.Response(200, json={"sandbox_public_key": "pk", "has_key": state.has_key})
        if path == "/v1/key":
            state.has_key = True
            return httpx.Response(200, json={"ok": True})
        if path == "/v1/file-ids":
            return httpx.Response(200, json={"embed_ids": ["e1", "e2"]})
        if path == "/v1/sync-in":
            return httpx.Response(200, json={"written": len(body["heads"]), "failed": [
                {"embed_id": "e2", "reason": "unknown_embed"}]})
        return httpx.Response(200, json={"files": 2})

    async def create(**kwargs):
        state.created += 1
        sandbox_id = f"sb{state.created}"
        state.running[sandbox_id] = time.time() - 3600
        conn = provider.ProjectSandboxConnection(sandbox_id, "host.example.org", "traffic", "bearer")
        return conn, {"sandbox_public_key": "pk", "has_key": False}

    async def kill(sandbox_id, secrets_manager=None):
        state.killed.append(sandbox_id)
        state.running.pop(sandbox_id, None)
        return True

    async def listing(secrets_manager=None):
        return dict(state.running)

    async def head(**kwargs):
        return {"embed": {"embed_id": kwargs["embed_id"]}, "embed_keys": []}

    async def charge(payload, *, team_id, event_id):
        state.charges.append(payload)

    monkeypatch.setattr(provider, "create_project_sandbox", create)
    monkeypatch.setattr(provider, "kill_project_sandbox", kill)
    monkeypatch.setattr(provider, "list_project_sandbox_ids", listing)

    async def connect(sandbox_id, secrets_manager=None):
        return object()

    async def extend(sandbox):
        return None

    monkeypatch.setattr(provider, "connect_project_sandbox", connect)
    monkeypatch.setattr(provider, "extend_idle", extend)
    state.head = head
    monkeypatch.setattr("backend.shared.python_utils.metered_author_billing.post_skill_charge", charge)
    state.transport = httpx.MockTransport(daemon)
    return state


def make_service(world, device_answer=None, wait=2.0):
    cache = FakeCache(device_answer)
    directus = SimpleNamespace(project=FakeProject())
    return svc.ProjectSandboxService(cache, directus, None, transport=world.transport, grant_wait_seconds=wait, head_loader=world.head), cache


KWARGS = dict(user_id="u1", chat_id="c1", project_id="p1", team_id=None)


# contract-test: direct surface=rest_api assertions=projects.sandbox.jobs,projects.keys.sandbox-sealed-handover
@pytest.mark.asyncio
async def test_ensure_ready_creates_requests_key_relays_syncs_and_baselines(world):
    service, cache = make_service(world, {"kind": "grant", "sealed_grant": SEALED})
    handle = await service.ensure_ready(**KWARGS)
    paths = [path for path, _ in world.calls]
    assert handle.sandbox_id == "sb1"
    assert paths[-4:] == ["/v1/key", "/v1/file-ids", "/v1/sync-in", "/v1/baseline"]
    assert dict(world.calls)["/v1/key"] == {"sealed_grant": SEALED}
    request = json.loads(next(m for c, m in cache.redis.published if c.startswith("user_cache_events:")))
    assert request["event_type"] == "send_project_sandbox_key_request"
    assert request["payload"]["expires_at"] > time.time()
    # reuse: same live sandbox, no second create
    again = await service.ensure_ready(**KWARGS)
    assert again.sandbox_id == "sb1" and world.created == 1


# contract-test: direct surface=rest_api assertions=projects.sandbox.device-fallback
@pytest.mark.asyncio
async def test_no_grant_in_time_is_no_device_and_kills(world):
    service, _ = make_service(world, None, wait=0.6)
    with pytest.raises(svc.ProjectSandboxUnavailable) as err:
        await service.ensure_ready(**KWARGS)
    assert err.value.reason == "no_device" and world.killed == ["sb1"]


# contract-test: direct surface=rest_api assertions=projects.sandbox.lifetime,projects.sandbox.device-fallback
@pytest.mark.asyncio
async def test_decline_and_lifetime_limit(world):
    service, _ = make_service(world, {"kind": "decline", "reason": "expired"})
    with pytest.raises(svc.ProjectSandboxUnavailable) as err:
        await service.ensure_ready(**KWARGS)
    assert err.value.reason == "declined"
    with pytest.raises(ValueError):
        await service.ensure_ready(**KWARGS, max_lifetime_seconds=24 * 3600 + 1)


# contract-test: direct surface=rest_api assertions=projects.sandbox.jobs
@pytest.mark.asyncio
async def test_template_missing_is_clear(monkeypatch):
    monkeypatch.delenv(provider.PROJECT_SANDBOX_TEMPLATE_ENV, raising=False)
    with pytest.raises(ProjectSandboxError) as err:
        await provider.create_project_sandbox(project_id="p", job_id="j", chat_id="c")
    assert err.value.code == "template_missing"


# contract-test: direct surface=rest_api assertions=projects.sandbox.jobs
@pytest.mark.asyncio
async def test_client_raises_daemon_error_code():
    transport = httpx.MockTransport(lambda r: httpx.Response(409, json={"error": "binding_mismatch"}))
    client = provider.ProjectSandboxClient("https://h.example.org", "t", "b", transport=transport)
    with pytest.raises(ProjectSandboxError) as err:
        await client.call("/v1/key", {"sealed_grant": "x"})
    assert err.value.code == "binding_mismatch"


# contract-test: direct surface=rest_api assertions=projects.sandbox.lifetime
@pytest.mark.asyncio
async def test_reaper_kills_expired_and_orphaned_and_bills(world):
    service, cache = make_service(world, {"kind": "grant", "sealed_grant": SEALED})
    await service.ensure_ready(**KWARGS, max_lifetime_seconds=60)
    world.running["orphan"] = time.time() - 3600
    world.running["fresh"] = time.time()
    result = await svc.reap_project_sandboxes(cache, now=time.time() + 120)
    assert result["killed_expired"] == 1 and result["killed_orphaned"] == 1
    assert "sb1" in world.killed and "orphan" in world.killed and "fresh" not in world.killed
    assert world.charges and world.charges[0]["credits"] >= 1
    assert not [k for k in cache.store if k.startswith(svc.SANDBOX_RECORD_PREFIX)]


# contract-test: direct surface=rest_api assertions=projects.keys.sandbox-sealed-handover
@pytest.mark.asyncio
async def test_key_safety_grant_never_stored_logged_or_traced(world, caplog, monkeypatch):
    caplog.set_level(logging.DEBUG)
    service, cache = make_service(world, {"kind": "grant", "sealed_grant": SEALED})
    await service.ensure_ready(**KWARGS)
    await service.kill(user_id="u1", chat_id="c1", project_id="p1", reason="test")
    assert all(SEALED not in value for _, value in cache.writes)
    assert all(SEALED not in value for value in cache.store.values())
    assert all(SEALED not in message for channel, message in cache.redis.published
               if not channel.startswith(svc.KEY_GRANT_CHANNEL_PREFIX))
    assert SEALED not in caplog.text
    assert all(SEALED not in json.dumps(p) for p in world.charges)
    record = json.loads(cache.writes[0][1])
    assert set(record) == set(svc.RECORD_FIELDS)

    # the WS handler: forwards over pub/sub only, and gives the span helper no payload
    cache2 = FakeCache()
    await cache2.set(svc.KEY_REQUEST_PREFIX + "r1", {"user_id": "u1", "job_id": "j1"})
    spans = []
    monkeypatch.setattr(handler, "start_ws_handler_span", lambda *a: spans.append(a) or (None, None))
    sent = []
    manager = SimpleNamespace(send_personal_message=lambda *a: asyncio.sleep(0, sent.append(a)))
    await handler.handle_project_sandbox_key_answer(
        manager, cache2, "u1", "dev", {"request_id": "r1", "job_id": "j1", "sealed_grant": SEALED}, granted=True)
    assert [c for c, m in cache2.redis.published] == [svc.key_grant_channel("r1")]
    assert SEALED not in json.dumps(spans, default=str) and SEALED not in caplog.text
    assert all(SEALED not in value for _, value in cache2.writes)
    # foreign user is rejected and nothing is published
    cache2.redis.published.clear()
    await handler.handle_project_sandbox_key_answer(
        manager, cache2, "other", "dev", {"request_id": "r1", "job_id": "j1", "sealed_grant": SEALED}, granted=True)
    assert not cache2.redis.published and sent


class FakeDaemonCommands:
    def __init__(self, probe_stdout="CONFINED\n"):
        self.calls = []
        self.probe_stdout = probe_stdout

    async def run(self, command, **kwargs):
        self.calls.append((command, kwargs))
        return SimpleNamespace(stdout=self.probe_stdout if command == provider.ESCALATION_PROBE else "")

    def daemon_starts(self):
        return [kwargs for command, kwargs in self.calls if command == "openmates-sandbox-host serve"]


# contract-test: direct surface=rest_api assertions=projects.keys.sandbox-sealed-handover
@pytest.mark.asyncio
async def test_daemon_starts_as_root_with_chat_and_team_env(monkeypatch):
    monkeypatch.setenv(provider.PROJECT_SANDBOX_TEMPLATE_ENV, "tmpl")
    commands = FakeDaemonCommands()
    sandbox = SimpleNamespace(sandbox_id="sb9", commands=commands, get_host=lambda port: "h.example.org",
                              traffic_access_token="t")

    async def create(**kwargs):
        return sandbox

    async def key(_):
        return "k"

    async def hello(client):
        return {"sandbox_public_key": "pk"}

    import sys
    import types

    fake_e2b = types.SimpleNamespace(AsyncSandbox=types.SimpleNamespace(create=create))
    monkeypatch.setitem(sys.modules, "e2b", fake_e2b)
    monkeypatch.setattr(provider, "get_e2b_api_key_async", key)
    monkeypatch.setattr(provider, "_wait_for_hello", hello)
    await provider.create_project_sandbox(project_id="p1", job_id="j1", chat_id="c1", team_id="t1")
    # Hardening as root, then the escalation probe as `user`, then the daemon: in that order.
    assert [c for c, _ in commands.calls] == [
        provider.HARDEN_COMMAND, provider.ESCALATION_PROBE, "openmates-sandbox-host serve"]
    assert commands.calls[0][1]["user"] == "root" and commands.calls[1][1]["user"] == "user"
    kwargs = commands.daemon_starts()[0]
    assert kwargs["user"] == "root" and kwargs["background"] is True
    assert kwargs["envs"]["OMSH_CHAT_ID"] == "c1" and kwargs["envs"]["OMSH_TEAM_ID"] == "t1"
    await provider.create_project_sandbox(project_id="p1", job_id="j1", chat_id="c1")
    assert "OMSH_TEAM_ID" not in commands.daemon_starts()[1]["envs"]


# contract-test: direct surface=rest_api assertions=projects.keys.sandbox-sealed-handover
@pytest.mark.asyncio
async def test_sandbox_where_user_can_still_become_root_is_killed_before_the_daemon(monkeypatch):
    monkeypatch.setenv(provider.PROJECT_SANDBOX_TEMPLATE_ENV, "tmpl")
    commands = FakeDaemonCommands(probe_stdout="ESCALATED\n")
    sandbox = SimpleNamespace(sandbox_id="sb9", commands=commands, get_host=lambda port: "h.example.org",
                              traffic_access_token="t")
    killed = []

    async def create(**kwargs):
        return sandbox

    async def key(_):
        return "k"

    async def kill(sandbox_id, **kwargs):
        killed.append(sandbox_id)

    import sys
    import types

    monkeypatch.setitem(sys.modules, "e2b", types.SimpleNamespace(AsyncSandbox=types.SimpleNamespace(create=create)))
    monkeypatch.setattr(provider, "get_e2b_api_key_async", key)
    monkeypatch.setattr(provider, "kill_project_sandbox", kill)
    monkeypatch.setattr(provider, "_sdk_errors", lambda: ())  # the fake e2b module has no exceptions
    with pytest.raises(provider.ProjectSandboxError) as refused:
        await provider.create_project_sandbox(project_id="p1", job_id="j1", chat_id="c1")
    assert refused.value.code == "escalation_possible" and killed == ["sb9"]
    assert commands.daemon_starts() == []


# contract-test: direct surface=rest_api assertions=projects.sandbox.device-fallback
@pytest.mark.asyncio
async def test_missing_e2b_key_is_a_sandbox_error_not_a_crash(monkeypatch):
    """No E2B key in Vault or env: creation fails with a sandbox error, so the caller keeps the device path."""
    monkeypatch.setenv(provider.PROJECT_SANDBOX_TEMPLATE_ENV, "tmpl")

    async def no_key(_):
        raise RuntimeError("E2B API key is not configured.")

    import sys
    import types

    monkeypatch.setitem(sys.modules, "e2b", types.SimpleNamespace(AsyncSandbox=types.SimpleNamespace()))
    monkeypatch.setattr(provider, "get_e2b_api_key_async", no_key)
    with pytest.raises(ProjectSandboxError) as err:
        await provider.create_project_sandbox(project_id="p1", job_id="j1", chat_id="c1")
    assert err.value.code == "api_key_unavailable"
    with pytest.raises(ProjectSandboxError) as err:
        await provider.kill_project_sandbox("sb1")
    assert err.value.code == "api_key_unavailable"
