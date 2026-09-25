# backend/tests/test_assistant_speech_api.py
#
# Contract coverage for the authenticated first-party assistant-speech handler.
# Requests are owner-scoped and bounded before any provider dispatch; responses
# expose only safe status and encrypted generated-asset metadata.
#

import pytest
from pathlib import Path

from backend.core.api.app.routes.handlers.websocket_handlers.assistant_speech_handler import (
    MAX_SPEAKABLE_TEXT_LENGTH,
    handle_assistant_speech_event,
    handle_assistant_speech_websocket,
    handle_assistant_speech_request,
)
from backend.apps.ai.assistant_speech.streaming import _speech_source_identity
from backend.core.api.app.schemas.chat import CachedChatListItemData
from backend.core.api.app.services.directus.chat_methods import CHAT_METADATA_FIELDS
from backend.shared.python_utils.chat_ciphertext_fingerprint import (
    CHAT_METADATA_FINGERPRINT_FIELDS,
)


# contract-test: supporting surface=rest_api assertions=assistant-speech.preference.chat-scoped-default-off
def test_projects_encrypted_auto_speak_response_as_versioned_chat_metadata() -> None:
    backend_root = Path(__file__).resolve().parents[1]
    source_paths = (
        backend_root / "core/directus/schemas/chats.yml",
        backend_root / "core/api/app/tasks/persistence_tasks.py",
        backend_root / "core/api/app/tasks/user_cache_tasks.py",
        backend_root / "core/api/app/routes/handlers/websocket_handlers/encrypted_chat_metadata_handler.py",
        backend_root / "core/api/app/routes/handlers/websocket_handlers/phased_sync_handler.py",
    )

    assert "encrypted_auto_speak_response" in CHAT_METADATA_FIELDS.split(",")
    assert "encrypted_auto_speak_response" in CHAT_METADATA_FINGERPRINT_FIELDS
    assert CachedChatListItemData().encrypted_auto_speak_response is None
    assert CachedChatListItemData(encrypted_auto_speak_response="OM-ciphertext").encrypted_auto_speak_response == "OM-ciphertext"
    assert all("encrypted_auto_speak_response" in path.read_text(encoding="utf-8") for path in source_paths)


# contract-test: direct surface=rest_api assertions=assistant-speech.access.first-party-owner-scoped,assistant-speech.privacy.transient-plaintext-encrypted-audio
@pytest.mark.asyncio
async def test_rejects_unauthenticated_wrong_owner_and_non_assistant_requests_before_dispatch() -> None:
    dispatches: list[dict[str, object]] = []

    async def authorize(**_kwargs) -> dict[str, object]:
        return {"chat_owner_id": "owner-1", "message_role": "user"}

    async def must_not_dispatch(**kwargs) -> None:
        dispatches.append(kwargs)

    for user_id, expected_error in (
        (None, "authentication_required"),
        ("other-user", "forbidden"),
        ("owner-1", "assistant_message_required"),
    ):
        result = await handle_assistant_speech_request(
            user_id=user_id,
            payload={"chat_id": "chat-1", "assistant_message_id": "message-1", "segments": [{"speakable_text": "Hello."}]},
            authorize=authorize,
            rate_limit=lambda **_kwargs: True,
            budget_preflight=lambda **_kwargs: True,
            dispatch=must_not_dispatch,
        )
        assert result == {"status": "error", "error": expected_error}

    assert dispatches == []


# contract-test: direct surface=rest_api assertions=assistant-speech.access.first-party-owner-scoped
@pytest.mark.asyncio
async def test_rejects_an_oversized_segment_batch_before_authorized_dispatch() -> None:
    dispatches: list[dict[str, object]] = []

    async def authorize(**_kwargs) -> dict[str, object]:
        return {"chat_owner_id": "owner-1", "message_role": "assistant"}

    async def dispatch(**kwargs) -> None:
        dispatches.append(kwargs)

    result = await handle_assistant_speech_request(
        user_id="owner-1",
        payload={
            "chat_id": "chat-1",
            "assistant_message_id": "message-1",
            "segments": [{"segment_id": f"segment-{index}", "speakable_text": "Hello."} for index in range(21)],
        },
        authorize=authorize,
        rate_limit=lambda **_kwargs: True,
        budget_preflight=lambda **_kwargs: True,
        dispatch=dispatch,
    )

    assert result == {"status": "error", "error": "too_many_segments"}
    assert dispatches == []


# contract-test: direct surface=rest_api assertions=assistant-speech.access.first-party-owner-scoped,assistant-speech.safety.provider-after-approval,assistant-speech.privacy.transient-plaintext-encrypted-audio
@pytest.mark.asyncio
async def test_rejects_rate_and_budget_before_dispatch_and_returns_safe_ready_metadata() -> None:
    dispatches: list[dict[str, object]] = []

    async def authorize(**_kwargs) -> dict[str, object]:
        return {"chat_owner_id": "owner-1", "message_role": "assistant"}

    async def dispatch(**kwargs) -> dict[str, object]:
        dispatches.append(kwargs)
        return {
            "segment_id": "segment-0",
            "status": "ready",
            "encrypted_audio": {"s3_key": "private/speech/segment-0.mp3", "encryption": "aes-gcm"},
            "duration_seconds": 1.2,
            "provider_request_id": "server-only",
            "speakable_text": "must not leave the handler",
        }

    payload = {
        "chat_id": "chat-1",
        "assistant_message_id": "message-1",
        "segments": [{"source_version": 1, "sequence": 0, "kind": "prose_paragraph", "source_hash": "source-hash", "speakable_text": "Hello."}],
    }
    for rate_allowed, budget_allowed, expected_error in ((False, True, "rate_limited"), (True, False, "insufficient_budget")):
        result = await handle_assistant_speech_request(
            user_id="owner-1",
            payload=payload,
            authorize=authorize,
            rate_limit=lambda **_kwargs: rate_allowed,
            budget_preflight=lambda **_kwargs: budget_allowed,
            dispatch=dispatch,
        )
        assert result == {"status": "error", "error": expected_error}

    result = await handle_assistant_speech_request(
        user_id="owner-1",
        payload=payload,
        authorize=authorize,
        rate_limit=lambda **_kwargs: True,
        budget_preflight=lambda **_kwargs: True,
        dispatch=dispatch,
    )

    assert dispatches == [{"user_id": "owner-1", "chat_id": "chat-1", "assistant_message_id": "message-1", "segments": payload["segments"], "defer_after_first": False, "require_registered": False}]
    assert result == {
        "status": "accepted",
        "chat_id": "chat-1",
        "message_id": "message-1",
        "segments": [
            {
                "segment_id": "segment-0",
                "status": "ready",
                "duration_seconds": 1.2,
            }
        ],
    }


# contract-test: direct surface=rest_api assertions=assistant-speech.execution.web-paragraph-demand,assistant-speech.on-demand.generate-missing-only,assistant-speech.access.first-party-owner-scoped
@pytest.mark.asyncio
async def test_deferred_web_request_preflights_only_first_paragraph_and_generate_requires_registered_source() -> None:
    preflighted: list[int] = []
    dispatched: list[dict[str, object]] = []

    async def authorize(**_kwargs):
        return {"chat_owner_id": "owner-1", "message_role": "assistant"}

    async def preflight(**kwargs):
        preflighted.append(kwargs["segment"]["sequence"])
        return True

    async def dispatch(**kwargs):
        dispatched.append(kwargs)
        return [{"segment_id": f"segment-{segment['sequence']}", "sequence": segment["sequence"], "status": "registered" if segment["sequence"] else "queued"} for segment in kwargs["segments"]]

    segments = [
        {"source_version": 1, "sequence": sequence, "kind": "prose_paragraph", "source_hash": "server-verified", "speakable_text": f"Paragraph {sequence}."}
        for sequence in range(3)
    ]
    result = await handle_assistant_speech_request(
        user_id="owner-1", payload={"chat_id": "chat-1", "assistant_message_id": "message-1", "segments": segments, "defer_after_first": True},
        authorize=authorize, rate_limit=lambda **_kwargs: True, budget_preflight=preflight, dispatch=dispatch,
    )
    assert preflighted == [0]
    assert dispatched[0]["defer_after_first"] is True
    assert result["segments"][1]["status"] == "registered"
    await handle_assistant_speech_request(
        user_id="owner-1", payload={"action": "generate", "chat_id": "chat-1", "assistant_message_id": "message-1", "segments": [segments[1]]},
        authorize=authorize, rate_limit=lambda **_kwargs: True, budget_preflight=preflight, dispatch=dispatch,
    )
    assert preflighted == [0, 1]
    assert dispatched[1]["require_registered"] is True


# contract-test: direct surface=rest_api assertions=assistant-speech.access.first-party-owner-scoped
@pytest.mark.asyncio
async def test_rate_limit_is_charged_once_by_requested_segment_count() -> None:
    observed: list[dict[str, object]] = []

    async def authorize(**_kwargs) -> dict[str, object]:
        return {"chat_owner_id": "owner-1", "message_role": "assistant"}

    async def rate_limit(**kwargs) -> bool:
        observed.append(kwargs)
        return True

    async def dispatch(**_kwargs) -> list[dict[str, object]]:
        return []

    segment = {"source_version": 1, "sequence": 0, "kind": "prose_paragraph", "source_hash": "hash", "speakable_text": "Hello."}
    result = await handle_assistant_speech_request(
        user_id="owner-1",
        payload={"chat_id": "chat-1", "assistant_message_id": "message-1", "segments": [segment, {**segment, "sequence": 1}]},
        authorize=authorize,
        rate_limit=rate_limit,
        budget_preflight=lambda **_kwargs: True,
        dispatch=dispatch,
    )

    assert result == {"status": "accepted", "chat_id": "chat-1", "message_id": "message-1", "segments": []}
    assert observed == [{"user_id": "owner-1", "chat_id": "chat-1", "segment_count": 2}]


# contract-test: direct surface=rest_api assertions=assistant-speech.access.first-party-owner-scoped,assistant-speech.privacy.transient-plaintext-encrypted-audio
@pytest.mark.asyncio
async def test_rejects_client_controlled_segment_identity_and_oversized_transient_text_before_dispatch() -> None:
    async def authorize(**_kwargs) -> dict[str, object]:
        return {"chat_owner_id": "owner-1", "message_role": "assistant"}

    async def dispatch(**_kwargs) -> None:
        raise AssertionError("untrusted segment input must not dispatch")

    result = await handle_assistant_speech_request(
        user_id="owner-1",
        payload={
            "chat_id": "chat-1",
            "assistant_message_id": "message-1",
            "segments": [{"segment_id": "client-id", "source_hash": "client-hash", "speakable_text": "x" * (MAX_SPEAKABLE_TEXT_LENGTH + 1)}],
        },
        authorize=authorize,
        rate_limit=lambda **_kwargs: True,
        budget_preflight=lambda **_kwargs: True,
        dispatch=dispatch,
    )

    assert result == {"status": "error", "error": "segment_text_too_long"}


# contract-test: direct surface=rest_api assertions=assistant-speech.on-demand.generate-missing-only,assistant-speech.segmentation.immutable-source
@pytest.mark.asyncio
async def test_request_requires_server_observed_sequence_kind_and_source_hash() -> None:
    async def authorize(**_kwargs) -> dict[str, object]:
        return {"chat_owner_id": "owner-1", "message_role": "assistant"}

    async def dispatch(**_kwargs) -> None:
        raise AssertionError("missing canonical segment metadata must not dispatch")

    result = await handle_assistant_speech_request(
        user_id="owner-1",
        payload={
            "chat_id": "chat-1",
            "assistant_message_id": "message-1",
            "segments": [{"speakable_text": "arbitrary client content"}],
        },
        authorize=authorize,
        rate_limit=lambda **_kwargs: True,
        budget_preflight=lambda **_kwargs: True,
        dispatch=dispatch,
    )

    assert result == {"status": "error", "error": "canonical_segment_required"}


# contract-test: direct surface=rest_api assertions=assistant-speech.access.first-party-owner-scoped,assistant-speech.on-demand.generate-missing-only,assistant-speech.lifecycle.disable-delete-invalidate
@pytest.mark.asyncio
async def test_websocket_handler_wires_real_request_retry_and_delete_dependencies_without_logging_plaintext() -> None:
    sent: list[dict[str, object]] = []
    actions: list[tuple[str, dict[str, object]]] = []

    class Manager:
        async def send_personal_message(self, message, _user_id, _device_hash):
            sent.append(message)

    async def authorize(**_kwargs):
        return {"chat_owner_id": "owner-1", "message_role": "assistant"}

    async def dispatch(**kwargs):
        actions.append(("dispatch", kwargs))
        return {"segment_id": "segment-0", "status": "queued"}

    async def retry(**kwargs):
        actions.append(("retry", kwargs))
        return {"segment_id": "segment-0", "status": "queued"}

    async def delete(**kwargs):
        actions.append(("delete", kwargs))

    for action, payload in (
        ("request", {"chat_id": "chat-1", "assistant_message_id": "message-1", "segments": [{"source_version": 1, "sequence": 0, "kind": "prose_paragraph", "source_hash": "source-hash", "speakable_text": "private"}]}),
        ("retry", {"chat_id": "chat-1", "assistant_message_id": "message-1", "segments": [{"source_version": 1, "sequence": 0, "kind": "prose_paragraph", "source_hash": "source-hash", "speakable_text": "private"}]}),
        ("delete", {"chat_id": "chat-1", "assistant_message_id": "message-1"}),
        ("cancel", {"chat_id": "chat-1", "assistant_message_id": "message-1"}),
    ):
        await handle_assistant_speech_websocket(
            manager=Manager(),
            user_id="owner-1",
            device_fingerprint_hash="device-1",
            payload={"action": action, **payload},
            authorize=authorize,
            rate_limit=lambda **_kwargs: True,
            budget_preflight=lambda **_kwargs: True,
            dispatch=dispatch,
            retry=retry,
            cancel=delete,
            delete=delete,
        )

    assert [action for action, _ in actions] == ["dispatch", "dispatch", "delete", "delete"]
    assert all("private" not in repr(message) for message in sent)


# contract-test: direct surface=rest_api assertions=assistant-speech.on-demand.generate-missing-only,assistant-speech.failure.nonblocking-visible-resumable,assistant-speech.privacy.transient-plaintext-encrypted-audio
@pytest.mark.asyncio
async def test_event_request_returns_persisted_ready_segment_without_redelivery(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("celery", reason="real event binder imports the Celery app")
    from backend.apps.audio.tasks import common as audio_task_common
    from backend.core.api.app.tasks import celery_config

    text = "Already generated."
    segment = {
        "id": "row-1",
        "segment_id": "segment-ready",
        "source_version": 1,
        "sequence": 0,
        "kind": "prose_paragraph",
        "source_hash": _speech_source_identity(text),
        "voice_profile_key": "warm_neutral",
        "voice_profile_version": 1,
        "status": "ready",
        "generated_asset_id": "asset-1",
        "duration_seconds": 1.2,
        "speakable_text": "must not be returned",
        "provider_request_id": "server-only",
    }
    sent: list[dict[str, object]] = []
    dispatched: list[tuple[str, dict[str, object], str]] = []

    class Manager:
        async def send_personal_message(self, message, _user_id, _device_hash):
            sent.append(message)

    class RedisClient:
        async def incrby(self, _key, amount):
            return amount

        async def expire(self, *_args):
            return True

    class Cache:
        @property
        def client(self):
            async def connected_client():
                return RedisClient()

            return connected_client()

        async def get_user_vault_key_id(self, _user_id):
            return "vault-key-1"

    class Chat:
        async def check_chat_ownership(self, chat_id, user_id):
            assert (chat_id, user_id) == ("chat-1", "owner-1")
            return True

    class Directus:
        chat = Chat()

        async def get_items(self, collection, *, params, no_cache):
            if collection == "messages":
                return [{"role": "assistant"}]
            if collection == "assistant_speech_segments":
                if params["filter[kind][_eq]"] == "app_use_announcement":
                    return []
                assert params["filter[source_hash][_eq]"] == segment["source_hash"]
                return [segment] if params["filter[sequence][_eq]"] == 0 else []
            return []

    async def credit_headroom(**_kwargs):
        raise AssertionError("ready speech replay must not require credit headroom")

    monkeypatch.setattr(audio_task_common, "ensure_audio_credit_headroom", credit_headroom)
    monkeypatch.setattr(celery_config.app, "send_task", lambda name, *, kwargs, queue: dispatched.append((name, kwargs, queue)), raising=False)

    await handle_assistant_speech_event(
        manager=Manager(),
        directus_service=Directus(),
        cache_service=Cache(),
        user_id="owner-1",
        device_fingerprint_hash="device-1",
        payload={
            "action": "request",
            "chat_id": "chat-1",
            "assistant_message_id": "message-1",
            "segments": [
                {
                    "source_version": 1,
                    "sequence": 0,
                    "kind": "prose_paragraph",
                    "source_hash": "client-placeholder",
                    "speakable_text": text,
                }
            ],
        },
    )

    assert dispatched == []
    assert sent == [
        {
            "type": "assistant_speech_status",
            "payload": {
                "status": "accepted",
                "chat_id": "chat-1",
                "message_id": "message-1",
                "segments": [
                    {
                        "segment_id": "segment-ready",
                        "sequence": 0,
                        "request_sequence": 0,
                        "status": "ready",
                        "generated_asset_id": "asset-1",
                        "duration_seconds": 1.2,
                        "kind": "prose_paragraph",
                    }
                ],
            },
        }
    ]
    assert "must not be returned" not in repr(sent)


# contract-test: direct surface=rest_api assertions=assistant-speech.on-demand.generate-missing-only,assistant-speech.failure.nonblocking-visible-resumable,assistant-speech.privacy.transient-plaintext-encrypted-audio
@pytest.mark.asyncio
async def test_event_request_creates_and_dispatches_missing_historical_segments(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("celery", reason="real event binder imports the Celery app")
    from backend.apps.audio.tasks import common as audio_task_common
    from backend.core.api.app.tasks import celery_config

    text = "Generate this historical paragraph."
    sent: list[dict[str, object]] = []
    dispatched: list[tuple[str, dict[str, object], str]] = []
    rows: dict[str, list[dict[str, object]]] = {
        "assistant_speech_manifests": [],
        "assistant_speech_segments": [],
    }

    class Manager:
        async def send_personal_message(self, message, _user_id, _device_hash):
            sent.append(message)

    class RedisClient:
        async def incrby(self, _key, amount):
            return amount

        async def expire(self, *_args):
            return True

    class Cache:
        @property
        def client(self):
            async def connected_client():
                return RedisClient()

            return connected_client()

        async def get_user_vault_key_id(self, _user_id):
            return "vault-key-1"

    class Chat:
        async def check_chat_ownership(self, _chat_id, _user_id):
            return True

    class Directus:
        chat = Chat()

        async def get_items(self, collection, *, params, no_cache):
            del no_cache
            if collection == "messages":
                return [{"role": "assistant"}]
            candidates = rows.get(collection, [])
            for key, value in params.items():
                if not key.startswith("filter[") or not key.endswith("][_eq]"):
                    continue
                field = key.removeprefix("filter[").removesuffix("][_eq]")
                candidates = [row for row in candidates if row.get(field) == value]
            return candidates[: int(params.get("limit", len(candidates)))]

        async def create_item(self, collection, record):
            rows[collection].append(dict(record))
            return record, None

        async def update_item(self, collection, row_id, patch):
            for row in rows[collection]:
                if row.get("id") == row_id or row.get("manifest_id") == row_id:
                    row.update(patch)
                    return row
            return None

    async def credit_headroom(**_kwargs):
        return None

    monkeypatch.setattr(audio_task_common, "ensure_audio_credit_headroom", credit_headroom)
    monkeypatch.setattr(celery_config.app, "send_task", lambda name, *, kwargs, queue: dispatched.append((name, kwargs, queue)), raising=False)

    await handle_assistant_speech_event(
        manager=Manager(),
        directus_service=Directus(),
        cache_service=Cache(),
        user_id="owner-1",
        device_fingerprint_hash="device-1",
        payload={
            "action": "request",
            "chat_id": "chat-1",
            "assistant_message_id": "message-1",
            "segments": [{
                "source_version": 1,
                "sequence": 0,
                "kind": "prose_paragraph",
                "source_hash": "client-placeholder",
                "speakable_text": text,
            }],
        },
    )

    assert len(rows["assistant_speech_manifests"]) == 1
    assert len(rows["assistant_speech_segments"]) == 1
    assert rows["assistant_speech_segments"][0]["source_hash"] == _speech_source_identity(text)
    assert rows["assistant_speech_segments"][0]["voice_profile_key"] == "george"
    assert [task[0] for task in dispatched] == [
        "apps.audio.tasks.assistant_speech_billing",
        "apps.audio.tasks.assistant_speech_segment",
    ]
    assert "speakable_text" not in dispatched[0][1]["arguments"]
    assert dispatched[1][1]["arguments"]["speakable_text"] == text
    assert sent[0]["payload"]["segments"][0]["status"] == "queued"
    assert text not in repr(sent)


# contract-test: direct surface=rest_api assertions=assistant-speech.on-demand.generate-missing-only,assistant-speech.failure.nonblocking-visible-resumable,assistant-speech.privacy.transient-plaintext-encrypted-audio
@pytest.mark.asyncio
async def test_event_request_requeues_retryable_error_when_plaintext_is_resupplied(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("celery", reason="real event binder imports the Celery app")
    from backend.apps.audio.tasks import common as audio_task_common
    from backend.core.api.app.tasks import celery_config

    text = "Retry this paragraph."
    segment = {
        "id": "row-1",
        "segment_id": "segment-retryable-error",
        "source_version": 1,
        "sequence": 1,
        "kind": "prose_paragraph",
        "source_hash": _speech_source_identity(text),
        "voice_profile_key": "warm_neutral",
        "voice_profile_version": 1,
        "status": "error",
        "error": "Speech is temporarily unavailable.",
        "retryable": True,
    }
    repeated_segment = {**segment, "id": "row-2", "segment_id": "segment-retryable-error-2", "sequence": 2}
    sent: list[dict[str, object]] = []
    dispatched: list[tuple[str, dict[str, object], str]] = []

    class Manager:
        async def send_personal_message(self, message, _user_id, _device_hash):
            sent.append(message)

    class RedisClient:
        async def incrby(self, _key, amount):
            return amount

        async def expire(self, *_args):
            return True

    class Cache:
        @property
        def client(self):
            async def connected_client():
                return RedisClient()

            return connected_client()

        async def get_user_vault_key_id(self, _user_id):
            return "vault-key-1"

    class Chat:
        async def check_chat_ownership(self, chat_id, user_id):
            assert (chat_id, user_id) == ("chat-1", "owner-1")
            return True

    class Directus:
        chat = Chat()

        async def get_items(self, collection, *, params, no_cache):
            if collection == "messages":
                return [{"role": "assistant"}]
            if collection == "assistant_speech_segments":
                if params["filter[kind][_eq]"] == "app_use_announcement":
                    return [{"segment_id": "app-use", "sequence": 0}]
                assert params["filter[source_hash][_eq]"] == segment["source_hash"]
                return [row for row in (segment, repeated_segment) if row["sequence"] == params["filter[sequence][_eq]"]]
            return []

    async def credit_headroom(**_kwargs):
        return None

    monkeypatch.setattr(audio_task_common, "ensure_audio_credit_headroom", credit_headroom)
    monkeypatch.setattr(celery_config.app, "send_task", lambda name, *, kwargs, queue: dispatched.append((name, kwargs, queue)), raising=False)

    await handle_assistant_speech_event(
        manager=Manager(),
        directus_service=Directus(),
        cache_service=Cache(),
        user_id="owner-1",
        device_fingerprint_hash="device-1",
        payload={
            "action": "request",
            "chat_id": "chat-1",
            "assistant_message_id": "message-1",
            "segments": [
                {
                    "source_version": 1,
                    "sequence": 0,
                    "kind": "prose_paragraph",
                    "source_hash": "client-placeholder",
                    "speakable_text": text,
                },
                {
                    "source_version": 1,
                    "sequence": 1,
                    "kind": "prose_paragraph",
                    "source_hash": "client-placeholder",
                    "speakable_text": text,
                },
            ],
        },
    )

    assert [call[0] for call in dispatched] == ["apps.audio.tasks.assistant_speech_segment"] * 2
    assert [call[1]["arguments"]["segment_id"] for call in dispatched] == ["segment-retryable-error", "segment-retryable-error-2"]
    assert [call[1]["arguments"]["sequence"] for call in dispatched] == [1, 2]
    assert all(call[1]["arguments"]["speakable_text"] == text for call in dispatched)
    assert all(call[2] == "app_music" for call in dispatched)
    assert sent == [
        {
            "type": "assistant_speech_status",
            "payload": {
                "status": "accepted",
                "chat_id": "chat-1",
                "message_id": "message-1",
                "segments": [
                    {"segment_id": "segment-retryable-error", "sequence": 1, "request_sequence": 0, "kind": "prose_paragraph", "status": "queued"},
                    {"segment_id": "segment-retryable-error-2", "sequence": 2, "request_sequence": 1, "kind": "prose_paragraph", "status": "queued"},
                ],
            },
        }
    ]
    assert text not in repr(sent)


# contract-test: direct surface=rest_api assertions=assistant-speech.on-demand.generate-missing-only,assistant-speech.segmentation.immutable-source
@pytest.mark.asyncio
async def test_event_replay_falls_back_to_content_identity_after_repeated_search_dedup_shifts_prose(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("celery", reason="real event binder imports the Celery app")
    from backend.apps.audio.tasks import common as audio_task_common
    from backend.core.api.app.tasks import celery_config

    canonical_search_text = "Search results are available."
    requested_search_text = "Ich habe die News-Suche verwendet."
    prose_text = "Later prose remains replayable."
    rows = [
        {"segment_id": "prelude", "source_version": 1, "sequence": 0, "kind": "app_use_announcement", "source_hash": "prelude", "status": "ready"},
        {"segment_id": "search-1", "source_version": 1, "sequence": 1, "kind": "embed_summary", "source_hash": _speech_source_identity(canonical_search_text), "status": "ready", "generated_asset_id": "asset-search"},
        {"segment_id": "search-2", "source_version": 1, "sequence": 2, "kind": "embed_summary", "source_hash": _speech_source_identity(canonical_search_text), "status": "ready", "generated_asset_id": "asset-search-2"},
        {"segment_id": "prose", "source_version": 1, "sequence": 3, "kind": "prose_paragraph", "source_hash": _speech_source_identity(prose_text), "status": "ready", "generated_asset_id": "asset-prose"},
    ]
    for row in rows:
        row.update({"user_id": "owner-1", "chat_id": "chat-1", "assistant_message_id": "message-1"})
    sent: list[dict[str, object]] = []
    dispatched: list[object] = []

    class Manager:
        async def send_personal_message(self, message, _user_id, _device_hash):
            sent.append(message)

    class RedisClient:
        async def incrby(self, _key, amount):
            return amount

        async def expire(self, *_args):
            return True

    class Cache:
        @property
        def client(self):
            async def connected_client():
                return RedisClient()

            return connected_client()

        async def get_user_vault_key_id(self, _user_id):
            return "vault-key-1"

    class Chat:
        async def check_chat_ownership(self, _chat_id, _user_id):
            return True

    class Directus:
        chat = Chat()

        async def get_items(self, collection, *, params, no_cache):
            del no_cache
            if collection == "messages":
                return [{"role": "assistant"}]
            if collection != "assistant_speech_segments":
                return []
            candidates = rows
            for key, value in params.items():
                if key.startswith("filter[") and key.endswith("][_eq]"):
                    field = key.removeprefix("filter[").removesuffix("][_eq]")
                    candidates = [row for row in candidates if row.get(field) == value]
            candidates = sorted(candidates, key=lambda row: int(row["sequence"]))
            return candidates[: int(params.get("limit", len(candidates)))]

    async def credit_headroom(**_kwargs):
        raise AssertionError("ready content-identity replay must not require credits")

    monkeypatch.setattr(audio_task_common, "ensure_audio_credit_headroom", credit_headroom)
    monkeypatch.setattr(celery_config.app, "send_task", lambda *args, **kwargs: dispatched.append((args, kwargs)), raising=False)

    await handle_assistant_speech_event(
        manager=Manager(), directus_service=Directus(), cache_service=Cache(), user_id="owner-1", device_fingerprint_hash="device-1",
        payload={"action": "request", "chat_id": "chat-1", "assistant_message_id": "message-1", "segments": [
            {"source_version": 1, "sequence": 0, "kind": "embed_summary", "source_hash": "client", "speakable_text": requested_search_text},
            {"source_version": 1, "sequence": 1, "kind": "prose_paragraph", "source_hash": "client", "speakable_text": prose_text},
        ]},
    )

    assert dispatched == []
    assert sent[0]["payload"]["segments"] == [
        {"segment_id": "search-1", "sequence": 1, "request_sequence": 0, "status": "ready", "generated_asset_id": "asset-search", "kind": "embed_summary"},
        {"segment_id": "prose", "sequence": 3, "request_sequence": 1, "status": "ready", "generated_asset_id": "asset-prose", "kind": "prose_paragraph"},
    ]


# contract-test: direct surface=rest_api assertions=assistant-speech.on-demand.generate-missing-only,assistant-speech.segmentation.immutable-source
@pytest.mark.asyncio
async def test_event_requeues_known_localized_summary_with_canonical_text_and_hash(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("celery", reason="real event binder imports the Celery app")
    from backend.apps.audio import pricing
    from backend.apps.audio.tasks import common as audio_task_common
    from backend.core.api.app.tasks import celery_config

    canonical_text = "I used the News Search skill."
    requested_text = "Ich habe die News-Suche verwendet."
    canonical_hash = _speech_source_identity(canonical_text)
    row = {
        "id": "row-1",
        "segment_id": "news-summary",
        "user_id": "owner-1",
        "chat_id": "chat-1",
        "assistant_message_id": "message-1",
        "source_version": 1,
        "sequence": 0,
        "kind": "embed_summary",
        "source_hash": canonical_hash,
        "voice_profile_key": "warm_neutral",
        "voice_profile_version": 1,
        "status": "error",
        "retryable": True,
    }
    sent: list[dict[str, object]] = []
    dispatched: list[tuple[str, dict[str, object], str]] = []
    estimated_characters: list[int] = []

    class Manager:
        async def send_personal_message(self, message, _user_id, _device_hash):
            sent.append(message)

    class RedisClient:
        async def incrby(self, _key, amount):
            return amount

        async def expire(self, *_args):
            return True

    class Cache:
        @property
        def client(self):
            async def connected_client():
                return RedisClient()

            return connected_client()

        async def get_user_vault_key_id(self, _user_id):
            return "vault-key-1"

    class Chat:
        async def check_chat_ownership(self, _chat_id, _user_id):
            return True

    class Directus:
        chat = Chat()

        async def get_items(self, collection, *, params, no_cache):
            del no_cache
            if collection == "messages":
                return [{"role": "assistant"}]
            if collection != "assistant_speech_segments":
                return []
            candidates = [row]
            for key, value in params.items():
                if key.startswith("filter[") and key.endswith("][_eq]"):
                    field = key.removeprefix("filter[").removesuffix("][_eq]")
                    candidates = [candidate for candidate in candidates if candidate.get(field) == value]
            return candidates[: int(params.get("limit", len(candidates)))]

    def calculate_credits(*, submitted_characters):
        estimated_characters.append(submitted_characters)
        return 1

    async def credit_headroom(**_kwargs):
        return None

    monkeypatch.setattr(pricing, "calculate_assistant_response_speech_credits", calculate_credits)
    monkeypatch.setattr(audio_task_common, "ensure_audio_credit_headroom", credit_headroom)
    monkeypatch.setattr(celery_config.app, "send_task", lambda name, *, kwargs, queue: dispatched.append((name, kwargs, queue)), raising=False)

    await handle_assistant_speech_event(
        manager=Manager(), directus_service=Directus(), cache_service=Cache(), user_id="owner-1", device_fingerprint_hash="device-1",
        payload={"action": "request", "chat_id": "chat-1", "assistant_message_id": "message-1", "segments": [
            {"source_version": 1, "sequence": 0, "kind": "embed_summary", "source_hash": "client", "speakable_text": requested_text},
        ]},
    )

    assert estimated_characters == [len(canonical_text)]
    assert [task[0] for task in dispatched] == ["apps.audio.tasks.assistant_speech_segment"]
    arguments = dispatched[0][1]["arguments"]
    assert arguments["speakable_text"] == canonical_text
    assert arguments["source_hash"] == canonical_hash
    assert requested_text not in repr(dispatched)
    assert sent[0]["payload"]["segments"] == [
        {"segment_id": "news-summary", "sequence": 0, "request_sequence": 0, "kind": "embed_summary", "status": "queued"},
    ]


# contract-test: direct surface=rest_api assertions=assistant-speech.failure.nonblocking-visible-resumable,assistant-speech.segmentation.immutable-source
@pytest.mark.asyncio
async def test_event_returns_visible_segment_error_when_sealed_manifest_rejects_missing_history(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("celery", reason="real event binder imports the Celery app")
    from backend.apps.audio.tasks import common as audio_task_common
    from backend.apps.audio.assistant_speech.persistence import manifest_id_for
    from backend.core.api.app.tasks import celery_config

    text = "Missing historical paragraph."
    manifest = {
        "id": "manifest-row",
        "manifest_id": manifest_id_for(chat_id="chat-1", assistant_message_id="message-1", source_version=1, voice_key="george", voice_version=1),
        "user_id": "owner-1",
        "chat_id": "chat-1",
        "assistant_message_id": "message-1",
        "ordered_segment_ids": ["prelude"],
        "sealed": True,
        "execution_version": 1,
    }
    prelude = {"segment_id": "prelude", "user_id": "owner-1", "chat_id": "chat-1", "assistant_message_id": "message-1", "source_version": 1, "sequence": 0, "kind": "app_use_announcement", "source_hash": "prelude", "status": "ready"}
    sent: list[dict[str, object]] = []
    dispatched: list[tuple[str, dict[str, object], str]] = []

    class Manager:
        async def send_personal_message(self, message, _user_id, _device_hash):
            sent.append(message)

    class RedisClient:
        async def incrby(self, _key, amount):
            return amount

        async def expire(self, *_args):
            return True

    class Cache:
        @property
        def client(self):
            async def connected_client():
                return RedisClient()

            return connected_client()

        async def get_user_vault_key_id(self, _user_id):
            return "vault-key-1"

    class Chat:
        async def check_chat_ownership(self, _chat_id, _user_id):
            return True

    class Directus:
        chat = Chat()

        async def get_items(self, collection, *, params, no_cache):
            del no_cache
            if collection == "messages":
                return [{"role": "assistant"}]
            candidates = [manifest] if collection == "assistant_speech_manifests" else [prelude] if collection == "assistant_speech_segments" else []
            for key, value in params.items():
                if key.startswith("filter[") and key.endswith("][_eq]"):
                    field = key.removeprefix("filter[").removesuffix("][_eq]")
                    candidates = [row for row in candidates if row.get(field) == value]
            return candidates[: int(params.get("limit", len(candidates)))]

    async def credit_headroom(**_kwargs):
        return None

    monkeypatch.setattr(audio_task_common, "ensure_audio_credit_headroom", credit_headroom)
    monkeypatch.setattr(celery_config.app, "send_task", lambda name, *, kwargs, queue: dispatched.append((name, kwargs, queue)), raising=False)

    await handle_assistant_speech_event(
        manager=Manager(), directus_service=Directus(), cache_service=Cache(), user_id="owner-1", device_fingerprint_hash="device-1",
        payload={"action": "request", "chat_id": "chat-1", "assistant_message_id": "message-1", "segments": [
            {"source_version": 1, "sequence": 0, "kind": "prose_paragraph", "source_hash": "client", "speakable_text": text},
        ]},
    )

    result = sent[0]["payload"]["segments"][0]
    assert result == {
        "segment_id": result["segment_id"],
        "sequence": 1,
        "request_sequence": 0,
        "status": "error",
        "error": "Speech is temporarily unavailable.",
        "retryable": False,
        "kind": "prose_paragraph",
    }
    assert [task[0] for task in dispatched] == ["apps.audio.tasks.assistant_speech_billing"]
    assert text not in repr(sent)


# contract-test: supporting surface=rest_api assertions=assistant-speech.access.first-party-owner-scoped,assistant-speech.failure.nonblocking-visible-resumable
def test_authenticated_websocket_router_registers_only_the_first_party_assistant_speech_event() -> None:
    backend_root = Path(__file__).resolve().parents[1]
    router_source = (backend_root / "core/api/app/routes/websockets.py").read_text(encoding="utf-8")
    handler_source = (backend_root / "core/api/app/routes/handlers/websocket_handlers/assistant_speech_handler.py").read_text(encoding="utf-8")

    assert 'message_type == "assistant_speech"' in router_source
    assert "handle_assistant_speech_event(" in router_source
    assert "check_chat_ownership" in handler_source
    assert '"messages"' in handler_source
    assert "assistant-speech:rate:" in handler_source


# contract-test: supporting surface=rest_api assertions=assistant-speech.lifecycle.disable-delete-invalidate
def test_directus_chat_deletion_service_owns_speech_tombstone_and_cleanup_dispatch() -> None:
    backend_root = Path(__file__).resolve().parents[1]
    chat_methods = (backend_root / "core/api/app/services/directus/chat_methods.py").read_text(encoding="utf-8")
    persistence_tasks = (backend_root / "core/api/app/tasks/persistence_tasks.py").read_text(encoding="utf-8")

    assert "cleanup_assistant_speech_for_chat" in chat_methods
    assert "cleanup_assistant_speech_for_message" in chat_methods
    assert "_enqueue_assistant_speech_cleanup" not in persistence_tasks


# contract-test: direct surface=rest_api assertions=assistant-speech.lifecycle.disable-delete-invalidate
@pytest.mark.asyncio
async def test_shared_message_deletion_tombstones_and_enqueues_speech_cleanup(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("celery", reason="shared cleanup dispatch requires the Celery dependency")
    from backend.core.api.app.services.directus.chat_methods import ChatMethods
    from backend.core.api.app.tasks.celery_config import app

    segments = [{"id": "speech-row", "segment_id": "segment-1", "status": "generating"}]
    dispatched: list[tuple[str, dict[str, object], str]] = []

    class Directus:
        async def get_items(self, collection, *, params, no_cache=False):
            if collection == "assistant_speech_manifests":
                return [{"user_id": "owner-1", "assistant_message_id": "message-1"}]
            if collection == "assistant_speech_segments":
                return segments
            if collection == "messages":
                return [{"id": "message-row"}]
            return []

        async def update_item(self, _collection, _row_id, patch):
            segments[0].update(patch)

        async def delete_item(self, **_kwargs):
            return True

    monkeypatch.setattr(app, "send_task", lambda name, *, kwargs, queue: dispatched.append((name, kwargs, queue)), raising=False)

    deleted = await ChatMethods(Directus()).delete_message_by_client_id("chat-1", "message-1")

    assert deleted is True
    assert segments[0]["status"] == "cancelled"
    assert dispatched == [
        (
            "apps.audio.tasks.assistant_speech_delete",
            {"arguments": {"user_id": "owner-1", "chat_id": "chat-1", "assistant_message_id": "message-1"}},
            "app_music",
        ),
    ]
