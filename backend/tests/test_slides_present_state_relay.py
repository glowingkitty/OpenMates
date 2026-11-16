"""Contract tests for the private slides presentation-remote WebSocket relay."""

import hashlib

import pytest

from backend.core.api.app.routes.handlers.websocket_handlers import (
    slides_present_state_handler as handler,
)


def _h(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class FakeManager:
    def __init__(self):
        self.personal = []
        self.broadcasts = []

    async def send_personal_message(self, message, user_id, device):
        self.personal.append((message, user_id, device))

    async def broadcast_to_user(self, message, user_id, exclude_device_hash=None):
        self.broadcasts.append((message, user_id, exclude_device_hash))


class FakeEmbeds:
    def __init__(self, owner_hash):
        self.owner_hash = owner_hash

    async def get_embed_by_id(self, embed_id):
        return {"embed_id": embed_id, "hashed_user_id": self.owner_hash}


class FakeDirectus:
    """Records any write attempt so tests can prove the relay stays read-only."""

    def __init__(self, owner_hash):
        self.embed = FakeEmbeds(owner_hash)
        self.writes = []

    def __getattr__(self, name):
        if name.startswith(("create", "update", "delete", "set")):
            def record(*args, **kwargs):
                self.writes.append(name)
            return record
        raise AttributeError(name)


@pytest.fixture(autouse=True)
def _reset():
    handler._frames.clear()
    handler._allowed.clear()


async def _send(manager, directus, payload, user="user-1"):
    await handler.handle_slides_present_state(
        manager=manager, directus_service=directus, user_id=user,
        device_fingerprint_hash="dev-a", payload=payload,
    )


# contract-test: direct surface=rest_api assertions=slides.present.remote-relay-private
@pytest.mark.asyncio
async def test_relay_excludes_sender_and_keeps_payload_identical():
    manager, directus = FakeManager(), FakeDirectus(_h("user-1"))
    payload = {"embed_id": "embed-1", "ciphertext": "AbC+/=opaque"}
    await _send(manager, directus, payload)
    assert manager.broadcasts == [
        ({"type": "slides_present_state", "payload": payload}, "user-1", "dev-a")
    ]
    assert manager.personal == []
    assert directus.writes == []


# contract-test: direct surface=rest_api assertions=slides.present.remote-relay-private
@pytest.mark.asyncio
async def test_other_users_embed_is_forbidden_and_not_relayed():
    manager, directus = FakeManager(), FakeDirectus(_h("someone-else"))
    await _send(manager, directus, {"embed_id": "embed-1", "ciphertext": "x"})
    assert manager.broadcasts == []
    assert manager.personal[0][0] == {
        "type": "slides_present_state_rejected",
        "payload": {"embed_id": "embed-1", "code": "forbidden"},
    }
    assert manager.personal[0][2] == "dev-a"


# contract-test: direct surface=rest_api assertions=slides.present.remote-relay-private
@pytest.mark.asyncio
async def test_oversize_and_invalid_frames_are_refused():
    manager, directus = FakeManager(), FakeDirectus(_h("user-1"))
    await _send(manager, directus, {"embed_id": "embed-1", "ciphertext": "x" * 1025})
    await _send(manager, directus, {"embed_id": "bad id!", "ciphertext": "x"})
    assert manager.broadcasts == []
    assert [m[0]["payload"]["code"] for m in manager.personal] == ["too_large", "invalid"]


# contract-test: direct surface=rest_api assertions=slides.present.remote-relay-private
@pytest.mark.asyncio
async def test_burst_over_limit_is_rate_limited():
    manager, directus = FakeManager(), FakeDirectus(_h("user-1"))
    for _ in range(handler.BURST_FRAMES + 1):
        await _send(manager, directus, {"embed_id": "embed-1", "ciphertext": "x"})
    assert len(manager.broadcasts) == handler.BURST_FRAMES
    assert manager.personal[-1][0]["payload"]["code"] == "rate_limited"


# contract-test: direct surface=rest_api assertions=slides.present.remote-relay-private
@pytest.mark.asyncio
async def test_relay_writes_nothing():
    manager, directus = FakeManager(), FakeDirectus(_h("user-1"))
    for _ in range(3):
        await _send(manager, directus, {"embed_id": "embed-1", "ciphertext": "x"})
    assert directus.writes == []
    assert not hasattr(handler, "cache_service")
