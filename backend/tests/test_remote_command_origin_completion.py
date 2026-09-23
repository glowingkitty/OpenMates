"""Origin completion tests for client-encrypted remote commands."""

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from backend.core.api.app.routes.handlers.websocket_handlers import (
    remote_command_origin_completion_handler as handler,
)
from backend.core.api.app.schemas.remote_command_schemas import (
    RemoteCommandOriginCompletion,
    RemoteCommandSourceCompletion,
)


class _WebSocket:
    def __init__(self) -> None:
        self.sent: list[dict] = []
        self.app = SimpleNamespace(state=SimpleNamespace(secrets_manager=object()))

    async def send_json(self, value: dict) -> None:
        self.sent.append(value)


class _Manager:
    def can_execute_remote_command_job(self, user_id: str, device: str, chat_id: str) -> bool:
        return (user_id, device, chat_id) == ("user-1", "device-1", "chat-1")


class _Authorization:
    def __init__(self, *_args) -> None:
        pass

    async def get_active_focus(self, **_kwargs):
        return {"project_id": "project-1"}


class _Receipt:
    def to_dict(self) -> dict:
        return {"policy": "terminal-output-v1", "scan_status": "scanned"}


class _Service:
    completed: list[dict] = []

    def __init__(self, _cache) -> None:
        pass

    async def require_origin_job(self, **_kwargs):
        return {
            "state": "AWAITING_ORIGIN_COMPLETION",
            "result_status": "succeeded",
            "continuation_task_id": "continuation-1",
            "source_id": "source-1",
        }

    async def complete_from_origin(self, **kwargs):
        self.completed.append(kwargs)
        return {
            "job": {
                "execution_id": "execution-1",
                "state": "TERMINAL",
                "continuation_task_id": "continuation-1",
                "source_id": "source-1",
            },
            "replayed": False,
        }

    def public_summary(self, job):
        return {"execution_id": job["execution_id"], "state": job["state"]}


# contract-test: supporting surface=cli assertions=code-run.output.external-text-guard,code-run.execution.wait-or-continue
@pytest.mark.asyncio
async def test_origin_plaintext_is_server_scanned_before_single_continuation(monkeypatch) -> None:
    websocket = _WebSocket()
    dispatched: list[dict] = []
    _Service.completed.clear()
    monkeypatch.setattr(handler, "ProjectWriteAuthorizationService", _Authorization)
    monkeypatch.setattr(handler, "RemoteCommandService", _Service)

    async def _scan(text, **_kwargs):
        assert text == "untrusted terminal text"
        return SimpleNamespace(model_text="checked terminal text", receipt=_Receipt())

    async def _dispatch(**kwargs):
        dispatched.append(kwargs)

    monkeypatch.setattr(handler, "sanitize_terminal_output_for_model", _scan)
    monkeypatch.setattr(handler, "_dispatch_async_skill_continuation", _dispatch)

    await handler.handle_remote_command_origin_completion(
        websocket=websocket,
        manager=_Manager(),
        cache_service=object(),
        directus_service=object(),
        user_id="user-1",
        device_fingerprint_hash="device-1",
        payload={
            "protocol_version": 1,
            "execution_id": "execution-1",
            "chat_id": "chat-1",
            "project_id": "project-1",
            "result_status": "succeeded",
            "model_text": "untrusted terminal text",
        },
    )

    assert _Service.completed[0]["safety_receipt"]["scan_status"] == "scanned"
    assert dispatched[0]["async_task_id"] == "continuation-1"
    assert dispatched[0]["completed_results"][0]["output"] == "checked terminal text"
    assert "untrusted terminal text" not in str(dispatched)
    assert websocket.sent[-1]["type"] == "remote_command_origin_completion_ack"


# contract-test: supporting surface=cli assertions=code-run.output.external-text-guard
def test_origin_client_cannot_supply_a_safety_receipt() -> None:
    with pytest.raises(ValidationError):
        RemoteCommandOriginCompletion.model_validate(
            {
                "protocol_version": 1,
                "execution_id": "execution-1",
                "chat_id": "chat-1",
                "project_id": "project-1",
                "result_status": "succeeded",
                "model_text": "output",
                "safety_receipt": {"scan_status": "scanned"},
            }
        )


# contract-test: supporting surface=cli assertions=code-run.output.external-text-guard,code-run.execution.wait-or-continue
def test_source_completion_binds_plaintext_excerpt_to_exact_terminal_lease() -> None:
    payload = {
        "protocol_version": 1,
        "execution_id": "execution-1",
        "project_id": "project-1",
        "source_id": "source-1",
        "source_session_id": "session-1",
        "lease_token": "lease-token-with-enough-length",
        "lease_generation": 2,
        "sequence": 4,
        "status": "succeeded",
        "encrypted_event": "project-key-ciphertext",
        "model_text": "bounded transient excerpt",
    }
    parsed = RemoteCommandSourceCompletion.model_validate(payload)
    assert parsed.sequence == 4
    assert parsed.model_text == "bounded transient excerpt"
    with pytest.raises(ValidationError):
        RemoteCommandSourceCompletion.model_validate({**payload, "event_kind": "terminal"})


# contract-test: supporting surface=cli assertions=code-run.output.external-text-guard,code-run.execution.wait-or-continue
@pytest.mark.asyncio
async def test_upstream_truncation_is_marked_before_scan_and_never_reports_full_coverage(monkeypatch) -> None:
    websocket = _WebSocket()
    scanned: list[str] = []

    async def _scan(text, **_kwargs):
        scanned.append(text)
        return SimpleNamespace(model_text=text, receipt=_Receipt())

    async def _dispatch(**_kwargs):
        return None

    monkeypatch.setattr(handler, "sanitize_terminal_output_for_model", _scan)
    monkeypatch.setattr(handler, "_dispatch_async_skill_continuation", _dispatch)
    outcome = await handler.complete_remote_command_output(
        websocket=websocket,
        cache_service=object(),
        service=_Service(object()),
        job={"source_id": "source-1"},
        user_id="user-1",
        execution_id="execution-1",
        chat_id="chat-1",
        project_id="project-1",
        result_status="succeeded",
        model_text="retained tail",
        upstream_truncated=True,
        omitted_chars=1234,
    )
    assert scanned[0].startswith("[Remote command transcript is incomplete")
    receipt = _Service.completed[-1]["safety_receipt"]
    assert receipt["coverage"] == "selected_excerpt"
    assert receipt["upstream_truncated"] is True
    assert receipt["upstream_omitted_chars"] == 1234
    assert outcome["replayed"] is False
