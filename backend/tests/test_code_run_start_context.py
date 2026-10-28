"""Private callback identity survives Code Run queueing without changing manual runs."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.tests.runtime_import_stubs import install_code_route_import_stubs

install_code_route_import_stubs()

from backend.core.api.app.routes import code_execution  # noqa: E402


@pytest.mark.parametrize("assistant", [True, False])
@pytest.mark.anyio
# contract-test: supporting surface=rest_api assertions=code-run.assistant.auto-debug-bounded,code-run.surface-parity
async def test_start_code_run_keeps_same_turn_batch_in_private_worker_payload(monkeypatch, assistant):
    cache = SimpleNamespace(client=AsyncMock(return_value=object())())
    queued, records = [], []

    async def create_record(cache_service, execution_id, record):
        assert cache_service is cache
        records.append(record)

    monkeypatch.setattr(code_execution, "_try_add_active_run", AsyncMock(return_value=True))
    monkeypatch.setattr(code_execution, "_try_reserve_provider_run", AsyncMock(return_value=None))
    monkeypatch.setattr(code_execution, "_create_execution_record", create_record)
    monkeypatch.setattr(code_execution.celery_app, "send_task", lambda *args, **kwargs: queued.append((args, kwargs)))
    result = await code_execution.start_code_run_execution(
        current_user=SimpleNamespace(id="owner", credits=25), cache_service=cache,
        files=[{"path": "main.rs", "content": "fn main() {}", "language": "rust", "is_target": True}],
        target_path="main.rs", enable_internet=False, chat_id="chat", target_embed_id="source",
        message_id="message", dependency_installs=[],
        **({"assistant_async_task": True, "same_turn_batch_id": "trusted-batch"} if assistant else {}),
    )
    assert len(queued) == 1
    args, kwargs = queued[0]
    assert args == ("code.run_execution",)
    assert kwargs["queue"] == "app_code"
    assert kwargs["args"][0] == result.execution_id
    payload = kwargs["args"][1]
    assert payload["same_turn_batch_id"] == ("trusted-batch" if assistant else None)
    assert payload["assistant_async_task"] is assistant
    assert (payload["user_id"], payload["chat_id"], payload["message_id"]) == ("owner", "chat", "message")
    assert "same_turn_batch_id" not in records[0]  # Never becomes public execution status.
