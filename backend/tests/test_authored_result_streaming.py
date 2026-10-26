"""Exercise authored-result dispatch through the real assistant stream parser."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from backend.apps.ai.processing.preprocessor import PreprocessingResult
from backend.apps.ai.skills.ask_skill import AskSkillRequest
from backend.apps.ai.tasks import stream_consumer
from backend.apps.ai.utils.json_content_fences import json_content_embed_type
from backend.shared.python_utils.chat_recovery_context import RequiredRecoveryOutputError


SOURCE = json.dumps({
    "schemaVersion": 1,
    "title": "Conference",
    "items": [{
        "id": "event", "kind": "events.event", "title": "Conference 2027",
        "origin": "user_provided",
        "details": {
            "date_start": "2027-01-30T09:00:00+01:00",
            "date_end": "2027-01-30T18:00:00+01:00",
            "venue": {"name": "Example venue", "city": "Brussels"},
        },
    }],
    "view": {"mode": "auto", "items": ["event"]},
}, indent=2)
REFERENCE = '{"type":"authored_results","embed_id":"carrier-1"}'


def _chunks(variant, source=SOURCE):
    if variant == "single":
        return [f"```openmates_embeds\n{source}\n```\n\n"]
    opening = ["```", "openmates_embeds\n"] if variant == "bare" else ["```openmates_embeds\n"]
    # Include a chunk ending at an actual JSON newline. This exercises the
    # shared per-line updater, independently of the closing-fence path.
    return opening + [source[:3], source[3:45], source[45:] + "\n", "```\n\n"]


@pytest.fixture
def consume(monkeypatch):
    def run(chunks, *, placeholder="ok", update_error=None, interruption=None,
            services=True, anonymous=False, finished_false=False):
        state = {"value": "STARTED"}

        async def main_stream(**_kwargs):
            for index, chunk in enumerate(chunks):
                if interruption == "revoke" and index == len(chunks) - 1:
                    state["value"] = stream_consumer.TASK_STATE_REVOKED
                yield chunk
            if interruption == "error":
                raise RuntimeError("provider failed")
            if interruption == "soft_limit":
                raise stream_consumer.SoftTimeLimitExceeded()

        class FakeEmbedService:
            create_json_content_embed_placeholder = AsyncMock(return_value={
                "embed_id": "carrier-1", "embed_reference": REFERENCE,
            } if placeholder == "ok" else None)
            update_json_content_embed_content = AsyncMock(return_value=True)
            create_code_embed_placeholder = AsyncMock()
            update_code_embed_content = AsyncMock()
            instances = []

            def __init__(self, *_args):
                self.instances.append(self)

        if isinstance(placeholder, Exception):
            FakeEmbedService.create_json_content_embed_placeholder.side_effect = placeholder
        if update_error or finished_false:
            async def update(**kwargs):
                if update_error and kwargs["status"] == update_error[0]:
                    raise update_error[1]
                return not (finished_false and kwargs["status"] == "finished")
            FakeEmbedService.update_json_content_embed_content.side_effect = update

        monkeypatch.setattr(stream_consumer, "handle_main_processing", main_stream)
        monkeypatch.setattr(stream_consumer.celery_config.app, "AsyncResult",
                            lambda _: SimpleNamespace(state=state["value"]))
        monkeypatch.setattr("backend.core.api.app.services.embed_service.EmbedService", FakeEmbedService)
        request = AskSkillRequest(
            chat_id="chat-1", message_id="message-1", user_id="user-1", user_id_hash="hash-1",
            message_history=[], is_incognito=True, is_anonymous=anonymous,
            embed_file_path_index={"existing.pdf": "existing-upload"},
        )
        result = asyncio.run(stream_consumer._consume_main_processing_stream(
            task_id="task-1", request_data=request,
            preprocessing_result=PreprocessingResult(can_proceed=True), base_instructions={},
            directus_service=SimpleNamespace() if services else None,
            encryption_service=SimpleNamespace() if services else None,
            user_vault_key_id="vault-1" if services else None,
            all_mates_configs=[], discovered_apps_metadata={}, cache_service=None,
        ))
        return result, FakeEmbedService
    return run


@pytest.mark.parametrize("variant", ["single", "multi", "bare"])
# contract-test: direct surface=rest_api assertions=authored-results.lifecycle.encrypted-and-stable,authored-results.groups.same-response-and-reuse
def test_authored_fence_uses_one_carrier_for_all_updates(consume, variant):
    result, service = consume(_chunks(variant))
    assert json_content_embed_type("openmates_embeds") == "authored_results"
    assert json_content_embed_type("authored_results") is None
    assert result[0].count(REFERENCE) == 1
    assert "schemaVersion" not in result[0]
    assert "date_start" not in result[0]
    service.create_json_content_embed_placeholder.assert_awaited_once()
    assert service.create_json_content_embed_placeholder.await_args.kwargs["source_language"] == "openmates_embeds"
    updates = [call.kwargs for call in service.update_json_content_embed_content.await_args_list]
    assert updates and all(call["embed_id"] == "carrier-1" for call in updates)
    assert all(call["source_language"] == "openmates_embeds" for call in updates)
    finished = [call for call in updates if call["status"] == "finished"]
    assert len(finished) == 1 and json.loads(finished[0]["source_json"]) == json.loads(SOURCE)
    if variant != "single":
        assert any(call["status"] == "processing" for call in updates)
    assert all(instance.authoring_reference_index == {"existing.pdf": "existing-upload"}
               for instance in service.instances)
    service.create_code_embed_placeholder.assert_not_awaited()
    service.update_code_embed_content.assert_not_awaited()


@pytest.mark.parametrize("variant", ["single", "multi", "bare"])
@pytest.mark.parametrize("failure", ["none", "exception", "services"])
# contract-test: direct surface=rest_api assertions=authored-results.lifecycle.encrypted-and-stable
def test_failed_placeholder_never_exposes_authoring_json(consume, variant, failure):
    result, service = consume(
        _chunks(variant), services=failure != "services",
        placeholder=RuntimeError("unavailable") if failure == "exception" else "none",
    )
    assert "schemaVersion" not in result[0]
    assert "openmates_embeds" not in result[0]
    assert "date_start" not in result[0]
    service.create_code_embed_placeholder.assert_not_awaited()
    service.update_code_embed_content.assert_not_awaited()


@pytest.mark.parametrize("variant", ["single", "multi", "bare"])
# contract-test: direct surface=rest_api assertions=authored-results.lifecycle.encrypted-and-stable
def test_rejected_malformed_source_never_falls_back_to_code(consume, variant):
    result, service = consume(
        _chunks(variant, '{"schemaVersion":1,"private-authoring-marker":'),
        update_error=("finished", ValueError("malformed source")),
    )
    assert "schemaVersion" not in result[0]
    assert "private-authoring-marker" not in result[0]
    assert service.update_json_content_embed_content.await_args.kwargs["status"] == "error"
    assert service.update_json_content_embed_content.await_args.kwargs["source_json"] == ""
    service.update_code_embed_content.assert_not_awaited()


@pytest.mark.parametrize("variant", ["single", "multi", "bare"])
# contract-test: direct surface=rest_api assertions=authored-results.lifecycle.encrypted-and-stable
def test_unsaved_final_update_attempts_one_empty_error_snapshot(consume, variant):
    result, service = consume(_chunks(variant), finished_false=True)
    assert "schemaVersion" not in result[0]
    updates = [call.kwargs for call in service.update_json_content_embed_content.await_args_list]
    assert [call["status"] for call in updates[-2:]] == ["finished", "error"]
    assert updates[-1]["source_json"] == ""
    service.update_code_embed_content.assert_not_awaited()


# contract-test: supporting surface=rest_api assertions=authored-results.lifecycle.encrypted-and-stable
def test_failed_final_error_snapshot_does_not_retry_or_hide_recovery_failure(consume):
    error = RequiredRecoveryOutputError("required error snapshot unavailable")
    with pytest.raises(RequiredRecoveryOutputError):
        consume(_chunks("multi"), finished_false=True, update_error=("error", error))


# contract-test: supporting surface=rest_api assertions=authored-results.lifecycle.encrypted-and-stable
def test_failed_final_error_snapshot_is_bounded_and_logged(consume, monkeypatch):
    error_log = Mock()
    monkeypatch.setattr(stream_consumer.logger, "error", error_log)
    result, service = consume(
        _chunks("multi"), finished_false=True, update_error=("error", RuntimeError("storage unavailable")),
    )
    assert "schemaVersion" not in result[0]
    assert any("Error saving failed JSON content snapshot carrier-1" in call.args[0]
               for call in error_log.call_args_list)
    updates = [call.kwargs for call in service.update_json_content_embed_content.await_args_list]
    assert [call["status"] for call in updates[-2:]] == ["finished", "error"]
    assert sum(call["status"] == "error" for call in updates) == 1


@pytest.mark.parametrize("interruption", [None, "error", "soft_limit", "revoke"])
# contract-test: direct surface=rest_api assertions=authored-results.lifecycle.encrypted-and-stable
def test_unclosed_or_cancelled_source_ends_with_empty_error_snapshot(consume, interruption):
    chunks = ["```openmates_embeds\n", SOURCE[:45] + "\n", '"private-cancelled-marker": true']
    result, service = consume(chunks, interruption=interruption)
    assert "schemaVersion" not in result[0]
    assert "private-cancelled-marker" not in result[0]
    updates = [call.kwargs for call in service.update_json_content_embed_content.await_args_list]
    assert updates[-1]["status"] == "error"
    assert updates[-1]["source_json"] == ""
    assert not any(call["status"] == "finished" for call in updates)
    assert result[1] == (interruption == "revoke")
    assert result[2] == (interruption == "soft_limit")
    service.update_code_embed_content.assert_not_awaited()


@pytest.mark.parametrize("phase", ["placeholder", "processing", "finished", "error"])
# contract-test: supporting surface=rest_api assertions=authored-results.lifecycle.encrypted-and-stable
def test_required_recovery_failures_escape_stream_fallback(consume, phase):
    error = RequiredRecoveryOutputError("required recovery unavailable")
    with pytest.raises(RequiredRecoveryOutputError):
        consume(
            _chunks("multi") if phase != "error" else ["```openmates_embeds\n", SOURCE[:45]],
            placeholder=error if phase == "placeholder" else "ok",
            update_error=(phase, error) if phase != "placeholder" else None,
        )


@pytest.mark.parametrize("variant", ["single", "multi", "bare"])
@pytest.mark.parametrize("interruption", [None, "revoke"])
# contract-test: direct surface=rest_api assertions=authored-results.lifecycle.encrypted-and-stable
def test_anonymous_response_only_path_suppresses_unsupported_authoring(consume, variant, interruption):
    result, service = consume(_chunks(variant), anonymous=True, interruption=interruption)
    assert "schemaVersion" not in result[0]
    assert "openmates_embeds" not in result[0]
    service.create_json_content_embed_placeholder.assert_not_awaited()
    service.create_code_embed_placeholder.assert_not_awaited()
