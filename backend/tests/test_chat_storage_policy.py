"""Pure prefix eligibility for encrypted warm storage and child transcripts."""

from backend.core.api.app.services.chat_storage_policy import (
    WarmArchivePolicy,
    select_archive_prefix,
)


def _messages(count: int, size: int = 1):
    return [
        {"client_message_id": f"m-{number:04d}", "created_at": number,
         "encrypted_content": "x" * size, "encrypted_thinking_content": "y"}
        for number in range(count)
    ]


def _select(chat, messages, **kwargs):
    return select_archive_prefix(
        chat, messages, now_timestamp=40 * 86_400,
        window_complete=True, canonical_ciphertext_available=True, **kwargs,
    )


# contract-test: infrastructure
def test_recent_main_keeps_latest_100_or_2_mib_whichever_hits_first():
    messages = _messages(101)
    decision = _select({"last_edited_overall_timestamp": 40 * 86_400}, messages, recent_main_rank=0)
    assert decision.message_ids == ("m-0000",)
    assert decision.through_timestamp == 0
    assert decision.encrypted_payload_bytes == 2

    small_limits = WarmArchivePolicy(encrypted_message_bytes_per_chat=6)
    by_bytes = _select({"last_edited_overall_timestamp": 40 * 86_400}, _messages(5), policy=small_limits)
    assert by_bytes.message_ids == ("m-0000", "m-0001")


# contract-test: infrastructure
def test_outside_recent_or_inactive_includes_pinned_and_shared_with_same_limits():
    messages = _messages(3)
    pinned = _select({"pinned": True, "last_edited_overall_timestamp": 40 * 86_400}, messages, recent_main_rank=10)
    assert pinned.reason == "outside_recent_main"
    assert pinned.message_ids == ("m-0000", "m-0001", "m-0002")

    shared = _select({"is_shared": True, "last_edited_overall_timestamp": 1}, messages, recent_main_rank=0)
    assert shared.reason == "inactive"
    assert shared.message_ids == pinned.message_ids


# contract-test: infrastructure
def test_acknowledged_checkpoint_archives_only_newly_covered_stable_prefix():
    messages = _messages(6)
    checkpoint = {
        "encrypted_summary": "client-ciphertext", "compressed_up_to_timestamp": 3,
        "compressed_up_to_message_id": "m-0003",
    }
    decision = _select(
        {}, messages, checkpoint=checkpoint, checkpoint_canonical_ack=True,
        already_archived_message_ids={"m-0000", "m-0001"},
    )
    assert decision.reason == "acknowledged_compression"
    assert decision.message_ids == ("m-0002", "m-0003")
    assert decision.through_message_id == "m-0003"
    assert not _select({}, messages, checkpoint=checkpoint).eligible


# contract-test: infrastructure
def test_pending_and_inflight_rows_stop_prefix_without_skipping():
    messages = _messages(6)
    decision = _select(
        {}, messages, recent_main_rank=10,
        pending_message_ids={"m-0002"}, in_flight_message_ids={"m-0004"},
    )
    assert decision.message_ids == ("m-0000", "m-0001")
    assert decision.blocked_by_message_id == "m-0002"
    assert not _select({}, messages, recent_main_rank=10, pending_message_ids={"m-0000"}).eligible


# contract-test: infrastructure
def test_child_requires_delivery_parent_consumption_and_canonical_ack():
    messages = _messages(2)
    child = {"is_sub_chat": True, "parent_id": "parent"}
    assert not _select(child, messages, child_result_delivered=True, child_parent_consumed=True).eligible
    decision = _select(
        child, messages, child_result_delivered=True, child_parent_consumed=True,
        child_canonical_ack=True, child_key_ack=True,
    )
    assert decision.reason == "completed_child"
    assert decision.message_ids == ("m-0000", "m-0001")


# contract-test: infrastructure
def test_missing_canonical_data_or_incomplete_window_defers():
    messages = _messages(2)
    assert select_archive_prefix({}, messages, now_timestamp=0).reason == "incomplete_message_window"
    assert not select_archive_prefix({}, messages, now_timestamp=0, window_complete=True).eligible
    assert _select({}, [{"created_at": 1, "encrypted_content": "cipher"}]).reason == "missing_stable_message_identity"
    assert _select({}, [{"client_message_id": "id", "created_at": 1}], recent_main_rank=10).reason == "unsupported_canonical_ciphertext"
    assert _select({}, messages, recent_main_rank=10, required_inference_context=True).reason == "required_inference_context"
    assert _select({}, messages, recent_main_rank=10, has_pending_output=True).reason == "pending_output"


# contract-test: infrastructure
def test_archive_prefix_cannot_jump_an_existing_archive_gap():
    decision = _select({}, _messages(4), recent_main_rank=10, already_archived_message_ids={"m-0000", "m-0002"})
    assert decision.reason == "noncontiguous_archive_prefix"


# contract-test: infrastructure
def test_stable_boundary_uses_message_id_when_timestamps_tie():
    messages = [
        {"client_message_id": name, "created_at": 7, "encrypted_content": "cipher"}
        for name in ("c", "a", "b")
    ]
    decision = _select({}, messages, checkpoint={
        "encrypted_summary": "sealed", "compressed_up_to_timestamp": 7,
        "compressed_up_to_message_id": "b",
    }, checkpoint_canonical_ack=True)
    assert decision.message_ids == ("a", "b")
    assert decision.through_timestamp == 7
    assert decision.through_message_id == "b"
