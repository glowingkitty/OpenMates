"""Camera ingress remains bounded and tools use the exact owned source upload."""
import asyncio
import base64
from io import BytesIO
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

from PIL import Image
import pytest

from backend.shared.python_utils.voice_call_visuals import VoiceCallVisuals, MAX_SOURCE_FRAMES
from backend.apps.ai.processing.voice_call_broker_runtime import visual_tool_messages


def frame(width=1280, height=720, frame_id="frame-1"):
    output = BytesIO()
    Image.new("RGB", (width, height), "green").save(output, format="JPEG")
    return {"frame_id": frame_id, "data": base64.b64encode(output.getvalue()).decode(),
            "captured_at": int(time.time() * 1000)}


# contract-test: supporting surface=gui.web assertions=video-call.video.source-frame-provenance,video-call.privacy
@pytest.mark.asyncio
async def test_camera_requires_explicit_state_and_rate_dimension_bounds_and_off_clears_latest():
    visuals = VoiceCallVisuals()
    with pytest.raises(ValueError):
        visuals.accept(frame(), now=1)
    visuals.set_enabled(True)
    accepted = visuals.accept(frame(), now=1)
    assert visuals.accept(frame(), now=1.99) is None
    with pytest.raises(ValueError):
        visuals.accept(frame(1281, 720), now=2)
    assert visuals.accept(frame(frame_id="frame-2"), now=2).frame_id == "frame-2"
    visuals.set_enabled(False)
    assert visuals.latest is None and visuals.freeze("new-user") is None
    assert accepted.data


# contract-test: supporting surface=gui.web assertions=video-call.video.input-and-output,video-call.video.source-frame-provenance,video-call.privacy
@pytest.mark.asyncio
async def test_transport_jitter_and_camera_restart_drop_excess_samples_without_replacing_provider_source():
    visuals = VoiceCallVisuals()
    visuals.set_enabled(True)
    first = visuals.accept(frame(frame_id="accepted-first"), now=10)
    received_at = visuals.latest_received_at
    # One-second sender emissions can arrive less than a second apart. A
    # discarded observation must neither reach the provider nor become a source.
    assert visuals.accept(frame(frame_id="jitter"), now=10.999) is None
    assert visuals.latest == first and visuals.latest_received_at == received_at
    assert visuals.freeze("first-turn") == first
    visuals.set_enabled(False)
    visuals.set_enabled(True)
    assert visuals.accept(frame(frame_id="rapid-camera-restart"), now=10.9999) is None
    assert visuals.latest is None and visuals.freeze("before-next-admission") is None
    second = visuals.accept(frame(frame_id="accepted-second"), now=11)
    assert second.frame_id == "accepted-second" and visuals.freeze("second-turn") == second
    assert visuals.accept(frame(frame_id="burst"), now=11.001) is None
    assert visuals.latest == second and visuals.last_frame_at == 11
    with pytest.raises(ValueError, match="JPEG"):
        visuals.accept(frame(1281, 720), now=11.5)
    visuals.set_enabled(False)
    with pytest.raises(ValueError):
        visuals.accept(frame(), now=12)
    visuals.close()


# contract-test: supporting surface=gui.web assertions=video-call.video.source-frame-provenance,video-call.privacy
@pytest.mark.asyncio
async def test_source_upload_matches_frozen_bytes_owner_and_mime_before_multimodal_tool_context():
    visuals = VoiceCallVisuals()
    visuals.set_enabled(True)
    original = visuals.accept(frame(), now=1)
    assert visuals.freeze("user-turn") == original
    assert visuals.freeze("user-turn") is None
    visuals.accept(frame(frame_id="later-frame"), now=2)
    visuals.set_enabled(False)
    row = {"embed_id": "source-uuid", "user_id": "owner", "content_hash": original.content_hash,
           "content_type": "image/jpeg"}
    directus = SimpleNamespace(get_items=AsyncMock(return_value=[row]))
    await visuals.acknowledge({"type": "source_frame_saved", "user_message_id": "user-turn",
        "frame_id": original.frame_id, "embed_reference": {"type": "image", "embed_id": "source-uuid"}},
        directus=directus, user_id="owner")
    source = await visuals.source("user-turn")
    assert source["data"] == original.data and source["frame_id"] != "later-frame"
    filters = directus.get_items.call_args.kwargs["params"]["filter"]["_and"]
    assert {"content_hash": {"_eq": original.content_hash}} in filters
    assert {"user_id": {"_eq": "owner"}} in filters
    messages = visual_tool_messages({"context": {"messages": []}, "request": "find this", "visual_source": source})
    assert messages[-1]["content"][1]["image_url"]["url"] == "data:image/jpeg;base64," + original.data
    visuals.close()
    assert not visuals.sources and visuals.latest is None


# contract-test: supporting surface=gui.web assertions=video-call.video.source-frame-provenance,video-call.privacy
@pytest.mark.asyncio
@pytest.mark.parametrize("bad_field", ["user_id", "content_hash", "content_type"])
async def test_forged_or_transcoded_source_cannot_authorize_tool(bad_field):
    visuals = VoiceCallVisuals()
    visuals.set_enabled(True)
    frozen = visuals.accept(frame(), now=1)
    visuals.freeze("turn")
    row = {"embed_id": "source", "user_id": "owner", "content_hash": frozen.content_hash,
           "content_type": "image/jpeg"}
    row[bad_field] = "foreign"
    with pytest.raises(PermissionError):
        await visuals.acknowledge({"type": "source_frame_saved", "user_message_id": "turn",
            "frame_id": frozen.frame_id, "embed_reference": {"type": "image", "embed_id": "source"}},
            directus=SimpleNamespace(get_items=AsyncMock(return_value=[row])), user_id="owner")
    assert await visuals.source("turn") is None


# contract-test: supporting surface=gui.web assertions=video-call.video.source-frame-provenance,video-call.privacy
@pytest.mark.asyncio
async def test_source_ring_is_bounded_pending_eviction_and_timeout_release_memory(monkeypatch):
    from backend.shared.python_utils import voice_call_visuals as module
    monkeypatch.setattr(module, "SOURCE_SAVE_TIMEOUT", 0.001)
    visuals = VoiceCallVisuals()
    visuals.set_enabled(True)
    visuals.accept(frame(), now=1)
    for index in range(MAX_SOURCE_FRAMES):
        visuals.freeze(str(index))
    old_future = visuals.sources["0"][1]
    visuals.freeze("overflow")
    assert len(visuals.sources) == MAX_SOURCE_FRAMES and old_future.result() is None
    assert await visuals.source("overflow") is None
    assert visuals.sources["overflow"][1].done()
    visuals.close()


# contract-test: supporting surface=gui.web assertions=video-call.video.source-frame-provenance,video-call.usage.provider-metering
@pytest.mark.asyncio
@pytest.mark.parametrize("expired_clock", ["received", "captured"])
async def test_stale_latest_camera_frame_never_becomes_new_turn_source(expired_clock):
    from dataclasses import replace
    visuals = VoiceCallVisuals()
    visuals.set_enabled(True)
    visuals.accept(frame(), now=1)
    assert visuals.camera_active
    frozen = visuals.freeze("already-admitted")
    if expired_clock == "received":
        visuals.latest_received_at -= 61
    else:
        visuals.latest = replace(visuals.latest, captured_at=visuals.latest.captured_at - 61_000)
    assert not visuals.camera_active
    assert visuals.freeze("new-turn") is None and visuals.latest is None
    assert visuals.sources["already-admitted"][0] == frozen
    visuals.close()


# contract-test: supporting surface=gui.web assertions=video-call.video.source-frame-provenance,video-call.lifecycle.recovery-and-billing,video-call.privacy
@pytest.mark.asyncio
@pytest.mark.parametrize("matching_upload", [True, False])
async def test_upload_ack_after_source_timeout_is_ignored_without_changing_camera_or_authority(monkeypatch, matching_upload):
    from backend.shared.python_utils import voice_call_visuals as module
    monkeypatch.setattr(module, "SOURCE_SAVE_TIMEOUT", 0.001)
    visuals = VoiceCallVisuals()
    visuals.set_enabled(True)
    frozen = visuals.accept(frame(), now=1)
    visuals.freeze("turn")
    lookup_started, release_lookup = asyncio.Event(), asyncio.Event()
    async def delayed_lookup(*args, **kwargs):
        lookup_started.set()
        await release_lookup.wait()
        return [{"embed_id": "source", "user_id": "owner" if matching_upload else "foreign",
                 "content_hash": frozen.content_hash, "content_type": "image/jpeg"}]
    acknowledgement = asyncio.create_task(visuals.acknowledge({"type": "source_frame_saved",
        "user_message_id": "turn", "frame_id": frozen.frame_id,
        "embed_reference": {"type": "image", "embed_id": "source"}},
        directus=SimpleNamespace(get_items=delayed_lookup), user_id="owner"))
    try:
        await asyncio.wait_for(lookup_started.wait(), 1)
        assert await visuals.source("turn") is None
        release_lookup.set()
        await asyncio.wait_for(acknowledgement, 1)
        assert visuals.sources["turn"][1].result() is None
        assert visuals.camera_active
    finally:
        release_lookup.set()
        await asyncio.gather(acknowledgement, return_exceptions=True)
        visuals.close()
