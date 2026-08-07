"""Deterministic root usage backfill resolution contracts.

Only metadata-backed ancestry may assign a root. Conflicting or malformed chat
chains remain unmatched so historical usage is never guessed into a billing tree.
"""

import uuid

from backend.scripts.backfill_root_chat_usage import Attribution, resolve_usage_row


ROOT_CHAT = {
    "root-1": {"id": "root-1", "parent_id": None, "is_sub_chat": False, "hashed_user_id": "owner"},
    "root-2": {"id": "root-2", "parent_id": None, "is_sub_chat": False, "hashed_user_id": "owner"},
}


def test_operation_evidence_resolves_deleted_child() -> None:
    attribution = Attribution("root-1", "child-1", "turn-1", "orch-1", 1, "operation", "owner")
    resolved, reason = resolve_usage_row(
        {"id": "usage-1", "operation_id": "operation-1", "chat_id": "child-1", "user_id_hash": "owner"},
        operations={"operation-1": attribution}, children={}, chats=ROOT_CHAT, mappings={},
    )

    assert resolved == attribution
    assert reason == "operation"


def test_conflicting_evidence_is_not_applied() -> None:
    resolved, reason = resolve_usage_row(
        {"id": "usage-1", "operation_id": "operation-1", "chat_id": "child-1", "user_id_hash": "owner"},
        operations={"operation-1": Attribution("root-1", "child-1", None, "orch-1", 1, "operation", "owner")},
        children={"child-1": Attribution("root-2", "child-1", None, "orch-2", 1, "orchestration_child", "owner")},
        chats=ROOT_CHAT, mappings={},
    )

    assert resolved is None
    assert reason == "conflict"


def test_valid_grandchild_chain_resolves_at_depth_two() -> None:
    chats = {
        "root-1": {"id": "root-1", "parent_id": None, "is_sub_chat": False, "hashed_user_id": "owner"},
        "child-1": {"id": "child-1", "parent_id": "root-1", "is_sub_chat": True, "hashed_user_id": "owner"},
        "grandchild-1": {"id": "grandchild-1", "parent_id": "child-1", "is_sub_chat": True, "hashed_user_id": "owner"},
    }
    resolved, reason = resolve_usage_row(
        {"id": "usage-1", "chat_id": "grandchild-1", "user_id_hash": "owner"},
        operations={}, children={}, chats=chats, mappings={},
    )

    assert resolved is not None
    assert (resolved.root_chat_id, resolved.actual_chat_id, resolved.depth) == ("root-1", "grandchild-1", 2)
    assert reason == "chat_chain"


def test_cross_owner_chain_remains_unmatched() -> None:
    resolved, reason = resolve_usage_row(
        {"id": "usage-1", "chat_id": "child-1", "user_id_hash": "owner-a"},
        operations={}, children={},
        chats={"child-1": {"id": "child-1", "parent_id": None, "is_sub_chat": False, "hashed_user_id": "owner-b"}},
        mappings={},
    )

    assert resolved is None
    assert reason == "unmatched"


def test_operation_for_different_actual_chat_remains_unmatched() -> None:
    resolved, reason = resolve_usage_row(
        {"id": "usage-1", "operation_id": "operation-1", "chat_id": "child-1", "user_id_hash": "owner"},
        operations={"operation-1": Attribution("root-1", "child-2", None, "orch-1", 1, "operation", "owner")},
        children={}, chats=ROOT_CHAT, mappings={},
    )

    assert resolved is None
    assert reason == "unmatched"


def test_different_orchestration_identity_is_a_conflict() -> None:
    resolved, reason = resolve_usage_row(
        {"id": "usage-1", "operation_id": "operation-1", "chat_id": "child-1", "user_id_hash": "owner"},
        operations={"operation-1": Attribution("root-1", "child-1", "turn-1", "orch-1", 1, "operation", "owner")},
        children={"child-1": Attribution("root-1", "child-1", "turn-2", "orch-2", 1, "orchestration_child", "owner")},
        chats=ROOT_CHAT, mappings={},
    )

    assert resolved is None
    assert reason == "conflict"


def test_evidence_with_missing_root_remains_unmatched() -> None:
    resolved, reason = resolve_usage_row(
        {"id": "usage-1", "operation_id": "operation-1", "chat_id": "child-1", "user_id_hash": "owner"},
        operations={"operation-1": Attribution("missing-root", "child-1", None, "orch-1", 1, "operation", "owner")},
        children={}, chats=ROOT_CHAT, mappings={},
    )

    assert resolved is None
    assert reason == "unmatched"


def test_existing_orchestration_metadata_conflict_is_preserved() -> None:
    resolved, reason = resolve_usage_row(
        {
            "id": "usage-1", "operation_id": "operation-1", "chat_id": "child-1", "user_id_hash": "owner",
            "orchestration_id": "different-orchestration",
        },
        operations={"operation-1": Attribution("root-1", "child-1", None, "orch-1", 1, "operation", "owner")},
        children={}, chats=ROOT_CHAT, mappings={},
    )

    assert resolved is None
    assert reason == "conflict"


def test_matching_database_uuid_metadata_is_accepted() -> None:
    orchestration_id = uuid.uuid4()
    resolved, reason = resolve_usage_row(
        {
            "id": "usage-1", "operation_id": "operation-1", "chat_id": "child-1", "user_id_hash": "owner",
            "orchestration_id": orchestration_id,
        },
        operations={
            "operation-1": Attribution("root-1", "child-1", None, str(orchestration_id), 1, "operation", "owner")
        },
        children={}, chats=ROOT_CHAT, mappings={},
    )

    assert resolved is not None
    assert reason == "operation"
