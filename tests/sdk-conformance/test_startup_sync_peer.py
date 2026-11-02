"""Pure wire-fixture controls. Never SDK, product or network acceptance."""

from types import SimpleNamespace

import pytest

from startup_sync_server import StartupPeer


class Wire:
    def __init__(self, frames):
        self.frames = iter(frames)
        self.sent = []
        self.handler = SimpleNamespace(
            connection=SimpleNamespace(settimeout=lambda _: None)
        )

    def receive(self):
        return next(self.frames, None)

    def send(self, kind, payload):
        self.sent.append((kind, payload))


def peer(mode="startup_expand", total=1234):
    value = StartupPeer.__new__(StartupPeer)
    value.identity, value.mode = "rust", mode
    value.vector = {"total_chat_count": total}
    value.counts = dict(
        connections=0,
        startup_requests=0,
        metadata_requests=0,
        startup_terminals=0,
        unexpected_frames=0,
        monitor_disconnects=0,
    )
    value.checks = set()
    value.row = lambda: {
        "id": "22222222-2222-4222-8222-222222222222",
        "encrypted_title": "opaque",
    }
    return value


def frame(kind, **payload):
    return {"type": kind, "payload": payload}


# contract-test: supporting surface=sdks.rust assertions=sync.startup.bounded-phases,sync.client.shared-rust-policy
def test_wire_requires_actual_terminal_before_metadata_and_preserves_original_epoch():
    value = peer()
    wire = Wire(
        [
            frame("phased_sync_request", phase="all", context_epoch=9),
            frame("sync_metadata_chats", existing_chat_ids=[], context_epoch=9),
        ]
    )
    value.websocket(wire)
    assert [kind for kind, _ in wire.sent] == [
        "phase_2_last_20_chats_ready",
        "phase_3_chunk_ready",
        "phased_sync_complete",
        "sync_metadata_chats_response",
    ]
    assert all(payload["context_epoch"] == 9 for _, payload in wire.sent)
    assert value.counts["metadata_requests"] == value.counts["startup_terminals"] == 1
    with pytest.raises(AssertionError):
        peer().websocket(
            Wire([frame("sync_metadata_chats", existing_chat_ids=[], context_epoch=9)])
        )
    with pytest.raises(AssertionError):
        peer().websocket(
            Wire(
                [
                    frame("phased_sync_request", phase="all", context_epoch=9),
                    frame(
                        "sync_metadata_chats", existing_chat_ids=[], context_epoch=10
                    ),
                ]
            )
        )


# contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,sync.startup.bounded-phases
@pytest.mark.parametrize("mode", ["startup_cancel_inflight", "startup_foreign_context"])
def test_wire_never_supplies_a_matching_response_in_cancel_or_foreign_context(mode):
    value = peer(mode)
    wire = Wire(
        [
            frame("phased_sync_request", phase="all", context_epoch=9),
            frame("sync_metadata_chats", existing_chat_ids=[], context_epoch=9),
        ]
    )
    value.websocket(wire)
    responses = [
        payload for kind, payload in wire.sent if kind == "sync_metadata_chats_response"
    ]
    assert all(payload["context_epoch"] != 9 for payload in responses)
    assert len(responses) == (1 if mode == "startup_foreign_context" else 0)


# contract-test: supporting surface=sdks.rust assertions=sync.startup.bounded-phases,sync.deletion.partial-window-not-authoritative
def test_small_count_extra_request_and_full_hint_ack_are_fixture_failures():
    with pytest.raises(AssertionError):
        peer(total=100).websocket(
            Wire(
                [
                    frame("phased_sync_request", phase="all", context_epoch=9),
                    frame("sync_metadata_chats", existing_chat_ids=[], context_epoch=9),
                ]
            )
        )
    with pytest.raises(AssertionError):
        peer().websocket(Wire([frame("sync_complete", full_sync=True)]))
