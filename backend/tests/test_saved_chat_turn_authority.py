# contract-test-file: infrastructure
"""Saved descendant admission cannot reopen a delegated job or reset ancestry."""
import asyncio
import copy
import hashlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.shared.python_utils.saved_chat_turn_authority import (
    admission_chat_id, admission_message_id, resolve_saved_chat_ancestry,
    saved_chat_turn, prepare_saved_chat_turn,
)
from backend.apps.ai.sub_chat_orchestration import (
    ensure_orchestration_envelope, is_sub_chat_continuation, resolve_sub_chat_depth,
)


def request(depth=0):
    return SimpleNamespace(
        user_id="owner", user_id_hash=hashlib.sha256(b"owner").hexdigest(), team_id_hash=None,
        chat_id="grandchild", message_id="fresh-message", parent_id=None,
        root_chat_id=None, root_user_message_id=None, sub_chat_depth=depth,
        recovery_task_id=None, is_sub_chat=False, is_external=False, is_anonymous=False,
        is_incognito=False, orchestration_id=None, orchestration_dispatch_token=None,
    )


def test_reconstructed_turn_rederives_depth_and_owns_fresh_admission():
    service, _, _, _ = fixture()
    turn = request()
    asyncio.run(prepare_saved_chat_turn(turn, service))
    assert saved_chat_turn(turn)
    assert resolve_sub_chat_depth(turn) == 2
    assert admission_chat_id(turn) == "grandchild"
    assert admission_message_id(turn) == "fresh-message"
    assert turn.root_chat_id == "root"
    assert is_sub_chat_continuation(turn)
    with pytest.raises(RuntimeError, match="cannot start descendants"):
        ensure_orchestration_envelope(turn)
    assert turn.sub_chat_depth == 2


@pytest.mark.parametrize("field,value", [
    ("chat_id", "other"), ("user_id", "other-owner"),
    ("team_id_hash", "foreign-team"), ("root_chat_id", "forged-root"), ("parent_id", "other-parent"),
    ("sub_chat_depth", 0), ("is_sub_chat", True), ("orchestration_id", "completed-job"),
])
def test_verified_ancestry_cannot_be_rebound(field, value):
    turn = request()
    service, _, _, _ = fixture()
    asyncio.run(prepare_saved_chat_turn(turn, service))
    setattr(turn, field, value)
    with pytest.raises(ValueError, match="identity_mismatch"):
        saved_chat_turn(turn)


def test_serialized_flags_cannot_grant_ancestry_authority():
    turn = request(depth=1)
    turn._verified_saved_chat_turn = {"depth": 1}
    assert not saved_chat_turn(turn)
    assert resolve_sub_chat_depth(turn) == 2


def test_lineage_query_failure_never_falls_back_to_editable_root():
    service, rows, _, _ = fixture()
    rows["grandchild"].update(parent_id=None, is_sub_chat=False)
    service.get_items = AsyncMock(side_effect=RuntimeError("database unavailable"))
    with pytest.raises(RuntimeError, match="database unavailable"):
        asyncio.run(prepare_saved_chat_turn(request(), service))


def test_fresh_turn_cannot_reuse_original_delegated_job():
    service, _, _, _ = fixture()
    turn = request()
    turn.orchestration_id = "completed-job"
    with pytest.raises(ValueError, match="cannot_reuse_delegated_job"):
        asyncio.run(prepare_saved_chat_turn(turn, service))


def fixture(*, team=None):
    owner = hashlib.sha256(b"owner").hexdigest()
    rows = {key: {"id": key, "hashed_user_id": owner, "hashed_team_id": team,
                  "parent_id": parent, "is_sub_chat": bool(parent)}
            for key, parent in [("root", None), ("child", "root"), ("grandchild", "child")]}
    links = {key: {"parent_chat_id": parent, "depth": depth, "orchestration_id": "tree"}
             for key, parent, depth in [("child", "root", 1), ("grandchild", "child", 2)]}

    async def get_items(collection, *, params, **kwargs):
        assert kwargs["admin_required"] and kwargs["raise_on_error"] and kwargs["no_cache"]
        if collection == "sub_chat_orchestration_children":
            link = links.get(params["filter[child_chat_id][_eq]"])
            return [copy.deepcopy(link)] if link else []
        assert collection == "sub_chat_orchestrations"
        return [{"id": "tree", "root_chat_id": "root", "hashed_user_id": owner, "hashed_team_id": team}]
    service = SimpleNamespace(chat=SimpleNamespace(get_chat_metadata=AsyncMock(side_effect=lambda key, **kwargs: rows.get(key))),
                              get_items=get_items)
    return service, rows, links, owner


def resolve(service, owner, chat="grandchild", team=None):
    return asyncio.run(resolve_saved_chat_ancestry(service, chat_id=chat, owner_hash=owner, team_hash=team))


def test_canonical_lineage_survives_client_reparenting():
    service, rows, _, owner = fixture()
    rows["grandchild"].update(parent_id=None, is_sub_chat=False)
    ancestry = resolve(service, owner)
    assert (ancestry.parent_id, ancestry.root_chat_id, ancestry.depth) == ("child", "root", 2)
    assert resolve(service, owner, "root") is None


@pytest.mark.parametrize("corruption", ["foreign_owner", "foreign_team", "missing", "cycle", "depth3", "mismatch"])
def test_invalid_canonical_ancestry_rejected(corruption):
    service, rows, links, owner = fixture()
    if corruption == "foreign_owner":
        rows["root"]["hashed_user_id"] = "foreign"
    if corruption == "foreign_team":
        rows["child"]["hashed_team_id"] = "foreign"
    if corruption == "missing":
        del rows["child"]
    if corruption == "cycle":
        rows["root"].update(parent_id="grandchild", is_sub_chat=True)
    if corruption == "depth3":
        links["grandchild"]["depth"] = 3
    if corruption == "mismatch":
        links["child"]["depth"] = 2
    with pytest.raises(ValueError, match="saved_chat_ancestry"):
        resolve(service, owner)


def test_legacy_ancestry_is_bounded_and_team_ancestry_is_scoped():
    service, rows, links, owner = fixture(team="team")
    rows["child"]["hashed_user_id"] = "other-team-member"
    assert resolve(service, owner, team="team").depth == 2
    links.clear()
    assert resolve(service, owner, team="team").depth == 2
    rows["great-grandchild"] = {**rows["grandchild"], "id": "great-grandchild", "parent_id": "grandchild"}
    with pytest.raises(ValueError, match="depth"):
        resolve(service, owner, "great-grandchild", team="team")


def test_reconstructed_queue_or_resume_cannot_reset_depth():
    service, _, _, _ = fixture()
    turn = request()
    asyncio.run(prepare_saved_chat_turn(turn, service))
    # Simulate a transport rebuilding only the ordinary request fields.
    rebuilt = request()
    rebuilt.message_id = "next-user-message"
    assert not saved_chat_turn(rebuilt)
    asyncio.run(prepare_saved_chat_turn(rebuilt, service))
    assert admission_message_id(rebuilt) == "next-user-message"
    assert resolve_sub_chat_depth(rebuilt) == 2
    with pytest.raises(RuntimeError, match="cannot start descendants"):
        ensure_orchestration_envelope(rebuilt)


def test_stage_one_and_main_share_fingerprint_without_serializing_authority():
    from backend.apps.ai.skills.ask_skill import AskSkillRequest
    from backend.apps.ai.processing.stage_one_handoff import request_fingerprint
    service, _, _, _ = fixture()
    raw = {key: value for key, value in vars(request()).items()}
    stage_one = AskSkillRequest(**raw, message_history=[])
    main = AskSkillRequest(**raw, message_history=[])
    asyncio.run(prepare_saved_chat_turn(stage_one, service))
    asyncio.run(prepare_saved_chat_turn(main, service))
    stage_payload = stage_one.model_dump(mode="json")
    assert "_verified_saved_chat_turn" not in stage_payload
    assert request_fingerprint(stage_payload, {}) == request_fingerprint(main.model_dump(mode="json"), {})
    replay = AskSkillRequest(**stage_payload)
    assert not saved_chat_turn(replay)
    asyncio.run(prepare_saved_chat_turn(replay, service))
    assert saved_chat_turn(replay)
