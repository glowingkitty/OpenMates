# backend/tests/test_run_application_preview_task.py
#
# Tests for the application preview worker lifecycle.
# They use the same Redis-like fake cache as the API tests and inject a fake E2B
# provider, so no sandbox or network call is made while proving session updates.

from __future__ import annotations

import json
import importlib.util
from pathlib import Path

import pytest

from backend.core.api.app.routes.application_preview import (
    ApplicationPreviewStartRequest,
    application_preview_session_key,
    create_application_preview_session,
)
from backend.shared.providers.e2b_application_preview import ApplicationPreviewRuntime
from backend.tests.test_application_preview_config import FakeCache, _user


def _load_worker_module():
    module_path = Path(__file__).resolve().parents[1] / "apps" / "code" / "tasks" / "run_application_preview_task.py"
    spec = importlib.util.spec_from_file_location("run_application_preview_task_under_test", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.anyio
async def test_run_application_preview_session_marks_session_running_with_upstream_url() -> None:
    worker = _load_worker_module()
    cache = FakeCache()
    await create_application_preview_session(
        cache_service=cache,
        session_id="session-1",
        application_embed_id="app-embed-1",
        body=ApplicationPreviewStartRequest(chat_id="chat-1"),
        current_user=_user("alice-user"),
        preview_origin="https://openmatesusercontent.org",
        now=2_000.0,
        preview_token="token-abc",
    )

    async def fake_provider(**_kwargs):
        return ApplicationPreviewRuntime(
            sandbox_id="sandbox-1",
            upstream_base_url="https://sandbox-1-5173.e2b.dev",
            ports={"frontend": 5173},
            latest_screenshot_url="https://openmatesusercontent.org/thumbs/session-1.png",
        )

    await worker.run_application_preview_session(
        cache_service=cache,
        session_id="session-1",
        payload={
            "files": [{"path": "package.json", "content": '{"scripts":{"dev":"vite"}}'}],
            "entrypoints": [{"name": "frontend", "command": "npm run dev", "port": 5173}],
        },
        provider_start=fake_provider,
        now=2_030.0,
    )

    stored = json.loads((await cache.redis.get(application_preview_session_key("session-1"))).decode("utf-8"))
    assert stored["status"] == "running"
    assert stored["sandbox_id"] == "sandbox-1"
    assert stored["upstream_base_url"] == "https://sandbox-1-5173.e2b.dev"
    assert stored["ports"] == {"frontend": 5173}
    assert stored["latest_screenshot_url"] == "https://openmatesusercontent.org/thumbs/session-1.png"
    assert stored["latest_screenshot_captured_at"] == 2_030.0
    assert stored["billing_state"]["billable_started_at"] == 2_030.0
    assert [event["text"] for event in stored["events"]][-2:] == [
        "Starting application preview sandbox...",
        "Application preview is running.",
    ]
    assert "token-abc" not in json.dumps(stored)


@pytest.mark.anyio
async def test_run_application_preview_session_marks_planning_error_failed_without_secret_leak() -> None:
    worker = _load_worker_module()
    cache = FakeCache()
    await create_application_preview_session(
        cache_service=cache,
        session_id="session-1",
        application_embed_id="app-embed-1",
        body=ApplicationPreviewStartRequest(chat_id="chat-1"),
        current_user=_user("alice-user"),
        preview_origin="https://openmatesusercontent.org",
        now=2_000.0,
        preview_token="token-abc",
    )

    await worker.run_application_preview_session(
        cache_service=cache,
        session_id="session-1",
        payload={
            "files": [{"path": "src/main.ts", "content": "const token = 'sk-test-secret-token-1234567890';"}],
            "entrypoints": [{"name": "frontend", "command": "npm run dev", "port": 5173}],
        },
        provider_start=None,
        now=2_030.0,
    )

    stored = json.loads((await cache.redis.get(application_preview_session_key("session-1"))).decode("utf-8"))
    serialized = json.dumps(stored)
    assert stored["status"] == "failed"
    assert "secrets" in stored["error"]
    assert "sk-test-secret" not in serialized
    assert "token-abc" not in serialized


@pytest.mark.anyio
async def test_stop_application_preview_sandbox_records_cleanup_event() -> None:
    worker = _load_worker_module()
    cache = FakeCache()
    await create_application_preview_session(
        cache_service=cache,
        session_id="session-1",
        application_embed_id="app-embed-1",
        body=ApplicationPreviewStartRequest(chat_id="chat-1"),
        current_user=_user("alice-user"),
        preview_origin="https://openmatesusercontent.org",
        now=2_000.0,
        preview_token="token-abc",
    )
    calls: list[dict[str, str]] = []

    async def fake_stop(**kwargs) -> bool:
        calls.append(kwargs)
        return True

    await worker.stop_application_preview_sandbox(
        cache_service=cache,
        session_id="session-1",
        sandbox_id="sandbox-1",
        api_key="e2b-key",
        provider_stop=fake_stop,
        now=2_090.0,
    )

    stored = json.loads((await cache.redis.get(application_preview_session_key("session-1"))).decode("utf-8"))
    assert calls == [{"sandbox_id": "sandbox-1", "api_key": "e2b-key"}]
    assert stored["sandbox_stopped_at"] == 2_090.0
    assert stored["events"][-1]["text"] == "Application preview sandbox stopped."
