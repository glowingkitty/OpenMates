"""Durable equality is the only prepared-privacy freshness authority."""

import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.core.api.app.services.personal_privacy_snapshot import (
    PersonalPrivacySocketState,
    PersonalPrivacyReceiptCapacityError,
    privacy_v2_request,
    read_personal_privacy_snapshot,
)

REQUEST = {
    "request_id": "49c6fabb-8871-4fd0-bf79-277cc3fa541a",
    "purpose": "send",
    "turn_id": "cec99c53-745c-4d0a-bc14-621fe6cc0a8b",
}
AUTH = {"user_id": "owner", "session_hash": "session", "upgrade_device_hash": "device"}
GENERATION = "78a3ee6d-7ce4-4be1-b6af-60b5407c5830:7"


@pytest.mark.parametrize(
    "change", [{"turn_id": "other"}, {"team_id": "team"}, {"privacy_generation": "old"}]
)
# contract-test: direct surface=rest_api assertions=ai-model-routing.preprocessing.prepared-privacy,auth.session.isolation
def test_receipt_is_exact_scoped_and_consumed_even_on_failure(change):
    state = PersonalPrivacySocketState()
    receipt = state.issue(request=REQUEST, auth=AUTH, generation=GENERATION)
    payload = {
        "turn_id": REQUEST["turn_id"],
        "privacy_receipt_id": receipt,
        "privacy_generation": GENERATION,
        **change,
    }
    assert not state.consume(payload, AUTH)
    assert receipt not in state.pending


@pytest.mark.parametrize(
    "change",
    [
        {"user_id": "other"},
        {"session_hash": "rotated"},
        {"upgrade_device_hash": "other"},
        {},
    ],
)
# contract-test: direct surface=rest_api assertions=ai-model-routing.preprocessing.prepared-privacy,auth.session.authoritative-enforcement
def test_receipt_rejects_authority_change_and_expiry(change):
    state = PersonalPrivacySocketState()
    receipt = state.issue(request=REQUEST, auth=AUTH, generation=GENERATION)
    if not change:
        state.pending[receipt]["expires_at"] = time.monotonic() - 1
    assert not state.consume(
        {
            "turn_id": REQUEST["turn_id"],
            "privacy_receipt_id": receipt,
            "privacy_generation": GENERATION,
        },
        {**AUTH, **change},
    )


# contract-test: direct surface=rest_api assertions=ai-model-routing.preprocessing.prepared-privacy
def test_receipt_one_use_socket_local_with_independent_pending_proofs():
    state = PersonalPrivacySocketState()
    first = state.issue(request=REQUEST, auth=AUTH, generation=GENERATION)
    second = state.issue(request=REQUEST, auth=AUTH, generation=GENERATION)
    payload = {
        "turn_id": REQUEST["turn_id"],
        "privacy_receipt_id": second,
        "privacy_generation": GENERATION,
    }
    assert first != second
    assert not PersonalPrivacySocketState().consume(payload, AUTH)
    assert state.consume(payload, AUTH)
    assert not state.consume(payload, AUTH)
    assert state.consume({**payload, "privacy_receipt_id": first}, AUTH)


@pytest.mark.parametrize(
    "change",
    [
        {"team_id": "team"},
        {"unchanged": True},
        {"turn_id": None},
        {"known_generation": 7},
        {"request_id": "bad"},
        {"purpose": "prepare"},
    ],
)
# contract-test: direct surface=rest_api assertions=ai-model-routing.preprocessing.prepared-privacy
def test_v2_rejects_untrusted_certifications_and_scope(change):
    assert privacy_v2_request({**REQUEST, **change}) is None


@pytest.mark.parametrize(
    "status,data,known,raises",
    [
        (404, None, GENERATION, False),
        (200, {"supported": False}, GENERATION, False),
        (
            200,
            {"supported": True, "privacy_generation": GENERATION, "unchanged": True},
            GENERATION,
            False,
        ),
        (
            200,
            {"supported": True, "privacy_generation": GENERATION, "unchanged": True},
            "older",
            True,
        ),
        (
            200,
            {"supported": True, "privacy_generation": None, "unchanged": True},
            None,
            True,
        ),
        (503, None, GENERATION, True),
    ],
)
# contract-test: direct surface=rest_api assertions=ai-model-routing.preprocessing.prepared-privacy
def test_internal_generation_validation_and_unsupported_fallback(
    monkeypatch, status, data, known, raises
):
    monkeypatch.setenv("INTERNAL_API_SHARED_TOKEN", "test-internal")
    directus = SimpleNamespace(
        base_url="http://cms",
        _make_api_request=AsyncMock(
            return_value=SimpleNamespace(
                status_code=status, json=lambda: {"data": data}
            )
        ),
    )
    if raises:
        with pytest.raises(RuntimeError):
            asyncio.run(read_personal_privacy_snapshot(directus, "owner", known))
    else:
        result = asyncio.run(read_personal_privacy_snapshot(directus, "owner", known))
        assert result == (data if data and data.get("supported") else None)
    call = directus._make_api_request.call_args
    assert call.kwargs["json"] == {"user_id": "owner", "known_generation": known}
    assert call.kwargs["headers"]["Cache-Control"] == "no-store"


# contract-test: direct surface=rest_api assertions=ai-model-routing.preprocessing.prepared-privacy
def test_receipt_successful_exact_lost_ack_replay_keeps_durable_idempotency():
    state = PersonalPrivacySocketState()
    receipt = state.issue(request=REQUEST, auth=AUTH, generation=GENERATION)
    payload = {
        "turn_id": REQUEST["turn_id"],
        "privacy_receipt_id": receipt,
        "privacy_generation": GENERATION,
        "inference_request": {"message": {"content": "in-memory-only"}},
    }
    assert state.consume(payload, AUTH)
    assert not state.consume(payload, AUTH)  # no durable acceptance yet
    state.mark_admitted(payload)
    assert state.consume(payload, AUTH)
    assert not state.consume({**payload, "message_id": "different"}, AUTH)
    assert state.consume(payload, AUTH)
    assert not state.consume(payload, {**AUTH, "session_hash": "rotated"})
    state.issue(request=REQUEST, auth=AUTH, generation=GENERATION)
    assert state.consume(payload, AUTH), (
        "Another pending turn must not invalidate accepted ACK replay"
    )


# contract-test: direct surface=rest_api assertions=ai-model-routing.preprocessing.prepared-privacy
def test_privacy_generation_migration_is_packaged_for_every_setup_path():
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    migration = "migrate_personal_privacy_generation.sql"
    setup = (root / "backend/core/directus/Dockerfile.setup.selfhost").read_text()
    assert f"COPY setup/{migration} /usr/src/app/migrations/{migration}" in setup
    assert (
        f"./directus/setup/{migration}:/usr/src/app/migrations/{migration}:ro"
        in (root / "backend/core/docker-compose.yml").read_text()
    )
    assert (
        "openmates-cms-setup:"
        in (root / "backend/core/docker-compose.selfhost.yml").read_text()
    )
    assert (
        "extensions/personal-privacy-snapshot/src/*.js"
        in (root / "backend/core/directus/Dockerfile").read_text()
    )


@pytest.mark.parametrize("generation", [GENERATION, None])
# contract-test: direct surface=rest_api assertions=ai-model-routing.preprocessing.prepared-privacy,chats.message.identity-idempotent
def test_parallel_turn_receipts_survive_reverse_admission_and_accepted_replay(
    generation,
):
    state = PersonalPrivacySocketState()
    requests = [
        {**REQUEST, "turn_id": str(uuid)}
        for uuid in [
            "11111111-1111-4111-8111-111111111111",
            "22222222-2222-4222-8222-222222222222",
        ]
    ]
    ids = [
        state.issue(request=request, auth=AUTH, generation=generation)
        for request in requests
    ]
    payloads = [
        {
            "turn_id": request["turn_id"],
            "privacy_receipt_id": receipt_id,
            "privacy_generation": generation,
        }
        for request, receipt_id in zip(requests, ids)
    ]
    assert state.consume(payloads[1], AUTH)
    state.mark_admitted(payloads[1])
    assert state.consume(payloads[0], AUTH), (
        "Slow first encryption must keep its exact turn receipt"
    )
    state.mark_admitted(payloads[0])
    assert state.consume(payloads[1], AUTH)
    assert state.consume(payloads[0], AUTH)
    assert not state.consume({**payloads[1], "turn_id": payloads[0]["turn_id"]}, AUTH)


# contract-test: direct surface=rest_api assertions=ai-model-routing.preprocessing.prepared-privacy
def test_live_pending_capacity_is_explicit_and_only_expired_proofs_are_pruned(
    monkeypatch,
):
    now = 100.0
    monkeypatch.setattr(time, "monotonic", lambda: now)
    state = PersonalPrivacySocketState()
    ids = [
        state.issue(request=REQUEST, auth=AUTH, generation=GENERATION)
        for _ in range(state.MAX_PENDING)
    ]
    assert not state.can_issue()
    with pytest.raises(PersonalPrivacyReceiptCapacityError):
        state.issue(request=REQUEST, auth=AUTH, generation=GENERATION)
    assert set(state.pending) == set(ids)
    now += state.RECEIPT_TTL_SECONDS
    assert state.can_issue()
    assert not state.pending
    assert state.issue(request=REQUEST, auth=AUTH, generation=None)


# contract-test: direct surface=rest_api assertions=ai-model-routing.preprocessing.prepared-privacy,auth.session.isolation
def test_unknown_receipt_and_failed_targeted_attempt_preserve_unrelated_turn():
    state = PersonalPrivacySocketState()
    first = state.issue(request=REQUEST, auth=AUTH, generation=GENERATION)
    other = state.issue(
        request={**REQUEST, "turn_id": "22222222-2222-4222-8222-222222222222"},
        auth=AUTH,
        generation=None,
    )
    payload = {
        "turn_id": REQUEST["turn_id"],
        "privacy_receipt_id": first,
        "privacy_generation": GENERATION,
    }
    assert not state.consume({**payload, "privacy_receipt_id": "unknown"}, AUTH)
    assert first in state.pending and other in state.pending
    assert not state.consume({**payload, "team_id": "team"}, AUTH)
    assert first not in state.pending and other in state.pending
    assert state.consume(
        {
            "turn_id": "22222222-2222-4222-8222-222222222222",
            "privacy_receipt_id": other,
            "privacy_generation": None,
        },
        AUTH,
    )


# contract-test: direct surface=rest_api assertions=ai-model-routing.preprocessing.prepared-privacy,chats.message.identity-idempotent
def test_accepted_replay_registry_is_bounded_and_expires_without_live_eviction(
    monkeypatch,
):
    now = 100.0
    monkeypatch.setattr(time, "monotonic", lambda: now)
    state = PersonalPrivacySocketState()
    payloads = []
    for _ in range(state.MAX_TRACKED):
        receipt = state.issue(request=REQUEST, auth=AUTH, generation=GENERATION)
        payload = {
            "turn_id": REQUEST["turn_id"],
            "privacy_receipt_id": receipt,
            "privacy_generation": GENERATION,
        }
        assert state.consume(payload, AUTH)
        state.mark_admitted(payload)
        payloads.append(payload)
    assert not state.can_issue()
    assert len(state.consumed) == state.MAX_TRACKED
    assert state.consume(payloads[0], AUTH), (
        "Capacity must preserve earlier exact accepted retries"
    )
    now += state.RECEIPT_TTL_SECONDS
    assert state.can_issue()
    assert not state.consumed
    assert not state.consume(payloads[0], AUTH)
