# backend/tests/test_code_run_billing_attribution.py
#
# Focused tests for Code Run worker billing metadata.
# The worker module imports runtime services at module load. Keep service stubs
# inert, but use the real provider's pure dataclasses/helpers: its E2B SDK import
# is already deferred until execution. A process-global partial provider module
# would otherwise replace worker file types in subsequently collected tests.

from __future__ import annotations

import sys
import types

import pytest


class _CeleryAppStub:
    def send_task(self, *_args, **_kwargs):
        return None

    def task(self, *_args, **_kwargs):
        return lambda func: func


tasks_stub = types.ModuleType("backend.core.api.app.tasks")
tasks_stub.__path__ = []
celery_config_stub = types.ModuleType("backend.core.api.app.tasks.celery_config")
celery_config_stub.app = _CeleryAppStub()


async def _missing_worker_cache_service():
    raise AssertionError("worker cache service is not used by this unit test")


celery_config_stub.get_worker_cache_service = _missing_worker_cache_service
sys.modules.setdefault("backend.core.api.app.tasks", tasks_stub)
sys.modules.setdefault("backend.core.api.app.tasks.celery_config", celery_config_stub)

secrets_manager_stub = types.ModuleType("backend.core.api.app.utils.secrets_manager")


class _SecretsManagerStub:
    async def initialize(self):
        return None

    async def aclose(self):
        return None


secrets_manager_stub.SecretsManager = _SecretsManagerStub
sys.modules.setdefault("backend.core.api.app.utils.secrets_manager", secrets_manager_stub)

from backend.apps.code.tasks.run_code_task import _charge_run_credits  # noqa: E402


# contract-test: supporting surface=rest_api assertions=code-run.billing.rate-limits,code-run.surface-parity
@pytest.mark.anyio
async def test_charge_run_credits_preserves_api_key_attribution(monkeypatch: pytest.MonkeyPatch) -> None:
    requests: list[dict] = []

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

    class FakeAsyncClient:
        def __init__(self, timeout: int):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url: str, json: dict, headers: dict):
            requests.append({"url": url, "json": json, "headers": headers})
            return FakeResponse()

    monkeypatch.setattr("backend.apps.code.tasks.run_code_task.httpx.AsyncClient", FakeAsyncClient)

    await _charge_run_credits(
        {
            "user_id": "user-1",
            "user_id_hash": "user-hash",
            "chat_id": None,
            "message_id": None,
            "target_embed_id": None,
            "target_path": "main.py",
            "files": [{"path": "main.py"}],
            "api_key_hash": "api-key-hash",
            "device_hash": "device-hash",
        },
        5,
        "execution-1",
        {"billing_phase": "completed", "charged_minutes": 1},
    )

    assert requests[0]["json"]["api_key_hash"] == "api-key-hash"
    assert requests[0]["json"]["device_hash"] == "device-hash"
    assert requests[0]["json"]["idempotency_key"].startswith("code-run:execution-1:")


@pytest.mark.parametrize(
    ("path", "language", "source", "terminal_output", "exit_code", "scan_available"),
    [
        ("main.py", "python", "print(1 / 3)", "0.3333333333333333\n", 0, True),
        ("main.rs", "rust", 'fn main() { println!("sum=55"); }', "sum=55\n", 0, True),
        ("main.rs", "rust", "fn main() { missing(); }", "error[E0425]: cannot find function missing\n", 1, True),
        ("main.py", "python", "print('result')", "result\n", 0, False),
    ],
)
# contract-test: supporting surface=rest_api assertions=code-run.assistant.auto-debug-bounded,code-run.output.cached-inference-guard,code-run.execution.stream-status-visible
def test_assistant_worker_continuation_delivers_checked_execution_result(
    monkeypatch: pytest.MonkeyPatch,
    path: str,
    language: str,
    source: str,
    terminal_output: str,
    exit_code: int,
    scan_available: bool,
) -> None:
    """A tracked run resumes the assistant with real results or a scan-unavailable receipt."""
    from types import SimpleNamespace

    from backend.apps.code.tasks import run_code_task
    from backend.shared.python_utils import terminal_output_safety
    from backend.shared.python_utils.structured_content_sanitization import StructuredScanError, TextDecision

    updates: list[dict] = []
    continuations: list[dict] = []
    cache = object()

    async def store_execution(_execution_id, patch):
        updates.append(patch)

    async def append_output(*_args):
        return None

    async def is_cancel_requested(_execution_id):
        return False

    async def clear_active_run(_payload):
        return None

    async def get_cache():
        return cache

    async def get_key(_secrets_manager):
        return "unit-test-key"

    async def charge(*_args):
        return 5

    async def persist_artifacts(**kwargs):
        assert kwargs["artifacts"] == []
        return [{
            "path": "outputs/result.csv", "mime_type": "text/csv", "kind": "csv",
            "size_bytes": 12, "asset_id": "execution-1", "variant": "result-csv",
            "download_url": "https://example.invalid/download?token=private",
        }]

    async def dispatch(**kwargs):
        continuations.append(kwargs)

    async def classify(units, **_kwargs):
        if not scan_available:
            raise StructuredScanError("OUTPUT_SAFETY_UNAVAILABLE")
        return {unit["id"]: TextDecision("safe") for unit in units}

    def run_provider(files, target_path, on_output, *_args):
        assert target_path == path
        assert files[0].content == source
        assert files[0].language == language
        on_output("stdout" if exit_code == 0 else "stderr", terminal_output)
        return SimpleNamespace(
            exit_code=exit_code, duration_seconds=1.2,
            output_truncated=False, artifacts=[], skipped_artifacts=[],
        )

    monkeypatch.setattr(run_code_task, "_store_execution", store_execution)
    monkeypatch.setattr(run_code_task, "_append_output", append_output)
    monkeypatch.setattr(run_code_task, "_is_cancel_requested", is_cancel_requested)
    monkeypatch.setattr(run_code_task, "_clear_active_run", clear_active_run)
    monkeypatch.setattr(run_code_task, "get_worker_cache_service", get_cache)
    monkeypatch.setattr(run_code_task, "get_e2b_api_key_async", get_key)
    monkeypatch.setattr(run_code_task, "_charge_run_credits", charge)
    monkeypatch.setattr(run_code_task, "_persist_code_run_artifacts", persist_artifacts)
    monkeypatch.setattr(run_code_task, "_dispatch_code_run_async_continuation", dispatch)
    monkeypatch.setattr(run_code_task, "run_code_in_e2b", run_provider)
    monkeypatch.setattr(terminal_output_safety, "classify_text_units", classify)

    run_code_task._run_code_execution("execution-1", {
        "user_id": "user-1", "chat_id": "chat-1", "message_id": "message-1",
        "target_embed_id": "embed-code-1", "target_path": path,
        "files": [{"path": path, "content": source, "language": language, "is_target": True}],
        "assistant_async_task": True, "same_turn_batch_id": "trusted-batch",
    })

    assert len(continuations) == 1
    assert continuations[0]["async_task_id"] == "execution-1"
    assert continuations[0]["request_metadata"] == {
        "target_filename": path, "user_id": "user-1", "chat_id": "chat-1",
        "message_id": "message-1", "same_turn_batch_id": "trusted-batch",
    }
    completed = continuations[0]["completed_results"][0]
    assert completed["target_embed_id"] == "embed-code-1"
    assert completed["target_filename"] == path
    assert completed["exit_code"] == exit_code
    assert completed["status"] == ("finished" if exit_code == 0 else "failed")
    assert completed["charged_credits"] == 5
    assert completed["artifacts"][0]["asset_id"] == "execution-1"
    assert "download_url" not in completed["artifacts"][0]
    if scan_available:
        assert completed["output"] == terminal_output
        assert completed["output_safety_receipt"]["scan_status"] == "scanned"
    else:
        assert "output" not in completed
        assert completed["output_safety_receipt"]["scan_status"] == "unscanned"
        assert completed["output_safety_receipt"]["scan_reason"] == "OUTPUT_SAFETY_UNAVAILABLE"
    assert updates[-1]["status"] == completed["status"]
