"""Pure ASGI and shared-inventory proofs for archive client admission."""
import json
import time
from types import SimpleNamespace

import httpx
import pytest
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from backend.core.api.app.services import storage_archive_client_compatibility as guard

SOURCE = "a" * 40
INVENTORY_ID = "f5e1ee09-2dc5-4476-bf1a-079635fa8bfb"


class Redis:
    def __init__(self, instances=("api:1",)):
        now = int(time.time())
        self.values = {guard.DEPLOYMENT_INVENTORY_KEY: json.dumps({
            "inventory_id": INVENTORY_ID, "source_commit": SOURCE, "instance_ids": list(instances),
            "observed_at": now, "expires_at": now + 180,
        })}
        for instance in instances:
            self.values[guard.PROOF_PREFIX + instance] = json.dumps({
                "inventory_id": INVENTORY_ID, "source_commit": SOURCE, "guard_revision": guard.GUARD_REVISION,
                "instance_id": instance, "observed_at": now, "incompatible_sessions": 0,
            })

    async def get(self, key):
        return self.values.get(key)

    async def scan_iter(self, **kwargs):
        for key in self.values:
            if key.startswith(guard.PROOF_PREFIX):
                yield key

    async def mget(self, keys):
        return [self.values.get(key) for key in keys]

    async def delete(self, key):
        self.values.pop(key, None)

    async def set(self, key, value, **kwargs):
        assert kwargs == {"ex": 45}
        self.values[key] = value


class Directus:
    def __init__(self, redis=None, row=None):
        self.cache = SimpleNamespace(client=redis or Redis())
        self.row = row or {}

    async def get_items(self, collection, **kwargs):
        assert collection in guard.ROLLOUT_COLLECTIONS
        assert kwargs["raise_on_error"] is True
        return [self.row] if self.row else []


# contract-test: direct surface=rest_api assertions=storage.surface.semantic-parity
@pytest.mark.asyncio
@pytest.mark.parametrize("row,capability,status", [
    ({}, "", 200), ({"read_enabled": True}, "", 426),
    ({"read_enabled": False, "reader_receipt": "retained"}, "", 426),
    ({"read_enabled": True}, "agentic-storage-v2", 200),
])
async def test_http_preserves_unmigrated_and_capable_reads(row, capability, status):
    async def endpoint(request):
        return JSONResponse({"authorized_route": True})
    app = Starlette(routes=[Route("/v1/chats", endpoint)])
    app.state.directus_service = Directus(row=row)
    app.add_middleware(guard.StorageArchiveClientCompatibilityMiddleware)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/v1/chats", headers={guard.CAPABILITY_HEADER: capability})
    assert response.status_code == status
    if status == 426:
        assert response.json() == {"detail": "update_required", "required_capability": "agentic-storage-v2"}


# contract-test: direct surface=rest_api assertions=storage.surface.semantic-parity
@pytest.mark.asyncio
async def test_inventory_requires_every_current_live_api_and_counts_legacy_connections():
    redis = Redis(("api:1", "api:2"))
    key = guard.PROOF_PREFIX + "api:2"
    proof = json.loads(redis.values[key])
    proof["incompatible_sessions"] = 3
    redis.values[key] = json.dumps(proof)
    status = await guard.runtime_compatibility_status(Directus(redis), source_commit=SOURCE)
    assert status["enforced"] is True
    assert status["incompatible_sessions"] == 3
    del redis.values[key]
    assert (await guard.runtime_compatibility_status(Directus(redis), source_commit=SOURCE))["enforced"] is False


# contract-test: direct surface=rest_api assertions=storage.surface.semantic-parity
@pytest.mark.asyncio
@pytest.mark.parametrize("defect", ["inventory_missing", "source_mismatch", "expired_inventory", "extra_api", "stale_proof", "wrong_guard", "boolean_count"])
async def test_inventory_fails_closed_on_incomplete_or_untrusted_proofs(defect):
    redis = Redis()
    inventory_key = guard.DEPLOYMENT_INVENTORY_KEY
    proof_key = guard.PROOF_PREFIX + "api:1"
    if defect == "inventory_missing":
        del redis.values[inventory_key]
    elif defect in {"source_mismatch", "expired_inventory"}:
        inventory = json.loads(redis.values[inventory_key])
        inventory["source_commit" if defect == "source_mismatch" else "expires_at"] = "b" * 40 if defect == "source_mismatch" else int(time.time()) - 1
        redis.values[inventory_key] = json.dumps(inventory)
    elif defect == "extra_api":
        redis.values[guard.PROOF_PREFIX + "api:2"] = redis.values[proof_key]
    else:
        proof = json.loads(redis.values[proof_key])
        proof[{"stale_proof": "observed_at", "wrong_guard": "guard_revision", "boolean_count": "incompatible_sessions"}[defect]] = {
            "stale_proof": int(time.time()) - 45, "wrong_guard": "not-installed", "boolean_count": True,
        }[defect]
        redis.values[proof_key] = json.dumps(proof)
    status = await guard.runtime_compatibility_status(Directus(redis), source_commit=SOURCE)
    assert status["enforced"] is False
    assert status["incompatible_sessions"] is None


# contract-test: direct surface=rest_api assertions=storage.surface.semantic-parity
@pytest.mark.asyncio
async def test_proof_requires_actual_guards_and_records_actual_connections(monkeypatch):
    monkeypatch.setenv("BUILD_COMMIT_SHA", SOURCE)
    redis = Redis((f"{guard.socket.gethostname()}:{guard.os.getpid()}",))
    manager = SimpleNamespace(active_connections={"owner": {"legacy": object(), "new": object()}},
                              storage_archive_capability={("owner", "new"): True},
                              storage_archive_dispatch_guard_installed=False)
    app = Starlette()
    app.state.directus_service = Directus(redis)
    app.state.connection_manager = manager
    app.add_middleware(guard.StorageArchiveClientCompatibilityMiddleware)
    with pytest.raises(RuntimeError, match="Actual HTTP"):
        await guard.publish_runtime_proof(app)
    manager.storage_archive_dispatch_guard_installed = True
    await guard.publish_runtime_proof(app)
    key = guard.PROOF_PREFIX + f"{guard.socket.gethostname()}:{guard.os.getpid()}"
    assert json.loads(redis.values[key])["incompatible_sessions"] == 1


# contract-test: direct surface=rest_api assertions=storage.surface.semantic-parity
@pytest.mark.asyncio
async def test_authoritative_phase_failure_does_not_return_partial_legacy_content():
    class BrokenDirectus:
        async def get_items(self, *args, **kwargs):
            raise RuntimeError("database unavailable")
    async def endpoint(request):
        pytest.fail("Legacy request must not enter an archive route during phase uncertainty")
    app = Starlette(routes=[Route("/v1/chats", endpoint)])
    app.state.directus_service = BrokenDirectus()
    app.add_middleware(guard.StorageArchiveClientCompatibilityMiddleware)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/v1/chats")
    assert response.status_code == 503


# contract-test: supporting surface=rest_api assertions=storage.surface.semantic-parity
def test_public_previews_and_project_metadata_do_not_need_archive_capability():
    assert not guard.archive_http_path("/v1/share/chat/id/og-image.png")
    assert not guard.archive_http_path("/v1/share/embed/id/og-metadata")
    assert not guard.archive_http_path("/v1/projects/id/settings")
    assert guard.archive_http_path("/v1/projects/id/items")
    assert guard.archive_http_path("/v1/share/chat/id/messages")


# contract-test: direct surface=rest_api assertions=storage.surface.semantic-parity
@pytest.mark.asyncio
async def test_legacy_full_chat_handler_keeps_authorization_and_rejects_hot_only_reads():
    from backend.core.api.app.routes.handlers.websocket_handlers.get_chat_messages_handler import handle_get_chat_messages
    from unittest.mock import AsyncMock
    directus = Directus(row={"reader_receipt": "already-pruned"})
    directus.chat = SimpleNamespace(check_chat_ownership=AsyncMock(return_value=True),
                                    get_all_messages_for_chat=AsyncMock())
    manager = SimpleNamespace(send_personal_message=AsyncMock())
    await handle_get_chat_messages(None, manager, directus, None, "owner", "device", {"chat_id": "chat"})
    directus.chat.check_chat_ownership.assert_awaited_once_with("chat", "owner")
    directus.chat.get_all_messages_for_chat.assert_not_awaited()
    assert manager.send_personal_message.await_args.kwargs["message"]["type"] == "update_required"
    directus.chat.check_chat_ownership.return_value = False
    manager.send_personal_message.reset_mock()
    await handle_get_chat_messages(None, manager, directus, None, "owner", "device", {"chat_id": "chat"})
    assert manager.send_personal_message.await_args.kwargs["message"]["type"] == "error"
    directus.chat.get_all_messages_for_chat.assert_not_awaited()


# contract-test: direct surface=rest_api assertions=storage.surface.semantic-parity
@pytest.mark.asyncio
async def test_new_inventory_epoch_invalidates_old_process_proofs():
    redis = Redis()
    inventory = json.loads(redis.values[guard.DEPLOYMENT_INVENTORY_KEY])
    inventory["inventory_id"] = "bf74326c-cc69-454e-ab18-ecc8d2a6cda9"
    redis.values[guard.DEPLOYMENT_INVENTORY_KEY] = json.dumps(inventory)
    status = await guard.runtime_compatibility_status(Directus(redis), source_commit=SOURCE)
    assert status["enforced"] is False


# contract-test: direct surface=rest_api assertions=storage.surface.semantic-parity
@pytest.mark.asyncio
async def test_legacy_admission_invalidates_previous_zero_connection_proof():
    instance = f"{guard.socket.gethostname()}:{guard.os.getpid()}"
    redis = Redis((instance,))
    app = SimpleNamespace(state=SimpleNamespace(directus_service=Directus(redis)))
    assert (await guard.runtime_compatibility_status(app.state.directus_service, source_commit=SOURCE))["enforced"] is True
    await guard.invalidate_runtime_proof(app)
    assert (await guard.runtime_compatibility_status(app.state.directus_service, source_commit=SOURCE))["enforced"] is False


# contract-test: direct surface=rest_api assertions=storage.surface.semantic-parity
@pytest.mark.asyncio
@pytest.mark.parametrize("method,status", [("GET", 426), ("POST", 403), ("DELETE", 403)])
async def test_mutations_keep_route_authorization_when_archive_readers_are_active(method, status):
    async def authorized_endpoint(request):
        return JSONResponse({"detail": "route_authorization_required"}, status_code=403)
    app = Starlette(routes=[Route("/v1/share/chat/metadata", authorized_endpoint, methods=["GET", "POST", "DELETE"])])
    app.state.directus_service = Directus(row={"read_enabled": True})
    app.add_middleware(guard.StorageArchiveClientCompatibilityMiddleware)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.request(method, "/v1/share/chat/metadata")
    assert response.status_code == status
    if method != "GET":
        assert response.json() == {"detail": "route_authorization_required"}


# contract-test: supporting surface=rest_api assertions=storage.surface.semantic-parity
def test_snapshot_export_and_metadata_mutations_do_not_need_read_capability():
    for path in ["/v1/embeds/id/versions/1/snapshot", "/v1/account-exports/id/complete",
                 "/v1/share/chat/unshare", "/v1/projects/id/items"]:
        assert not guard.archive_http_path(path, "POST")
        assert not guard.archive_http_path(path, "DELETE")
