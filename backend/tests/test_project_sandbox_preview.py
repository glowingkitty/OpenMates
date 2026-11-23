# backend/tests/test_project_sandbox_preview.py
#
# Tests for the Project-sandbox app preview: folder validation, built-app card
# detection, dev-server start, the worker session, the gateway upstream lookup
# (traffic token stays server-side), keep-alive and the route/gateway guards.

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException

from backend.apps.ai.processing.project_app_preview_card import built_app_folders
from backend.apps.code import project_sandbox_preview as preview
from backend.apps.code.project_sandbox_preview import (
    ProjectPreviewError,
    dev_server_command,
    keep_project_preview_alive,
    normalize_preview_folder,
    project_preview_upstream,
    run_project_sandbox_preview_session,
    start_dev_server,
)
from backend.core.api.app.routes import application_preview as route
from backend.core.api.app.routes import application_preview_gateway as gateway
from backend.core.api.app.services.project_sandbox_service import (
    ProjectSandboxUnavailable,
    sandbox_record_key,
)

TRAFFIC_TOKEN = "traffic-secret-xyz"
HOST = "5173-sbx1.e2b.example"


def _sandbox_result(command: str = "npm run build", cwd: str = "", **over: Any) -> dict:
    result = {"write_back": {}, "status": "finished", "exit_code": 0, "command": command, "cwd": cwd}
    result.update(over)
    return result


# 1. folder normalisation
# contract-test: supporting surface=rest_api assertions=code-run.cloud.project-preview
@pytest.mark.parametrize("value,expected", [("", ""), (".", ""), ("web-app", "web-app"), ("apps/web", "apps/web")])
def test_normalize_preview_folder_accepts(value: str, expected: str) -> None:
    assert normalize_preview_folder(value) == expected


# contract-test: supporting surface=rest_api assertions=code-run.cloud.project-preview
@pytest.mark.parametrize("value", ["..", "a/../b", "a\\b", "a//b", "a" * 513])
def test_normalize_preview_folder_refuses(value: str) -> None:
    with pytest.raises(ProjectPreviewError):
        normalize_preview_folder(value)


# 2. built app folders
# contract-test: supporting surface=rest_api assertions=code-run.cloud.project-preview
def test_built_app_folders_picks_only_successful_sandbox_builds() -> None:
    results = [
        _sandbox_result(cwd="web"),
        _sandbox_result(cwd="web"),  # duplicate
        {"status": "finished", "exit_code": 0, "command": "npm run build", "cwd": "cloud"},  # not sandbox
        _sandbox_result(cwd="broken", exit_code=1),
        _sandbox_result(cwd="running", status="running"),
        _sandbox_result(command="ls", cwd="nobuild"),
        _sandbox_result(command="vite build", cwd="b"),
    ]
    assert built_app_folders(results) == ["web", "b"]
    assert built_app_folders("nope") == []


# contract-test: supporting surface=rest_api assertions=code-run.cloud.project-preview
def test_built_app_folders_caps_at_three() -> None:
    assert len(built_app_folders([_sandbox_result(cwd=f"app{i}") for i in range(6)])) == 3


# 3. dev server command
# contract-test: supporting surface=rest_api assertions=code-run.cloud.project-preview
def test_dev_server_command_shape() -> None:
    command = dev_server_command("", HOST)
    assert command.argv[0] == "env"
    assert command.argv[1] == f"{preview.VITE_ALLOWED_HOSTS_ENV}={HOST}"
    assert command.cwd == "."
    assert command.background is True
    assert dev_server_command("apps/web", HOST).cwd == "apps/web"


# 4. start_dev_server
class FakeCommands:
    def __init__(self, codes: list[tuple[str, int]] | None = None) -> None:
        self.codes = codes or []
        self.lines: list[str] = []

    async def run(self, line: str, timeout: float = 0, user: str | None = None) -> Any:
        self.lines.append(line)
        code = 0
        for needle, value in self.codes:
            if needle in line:
                code = value
        return SimpleNamespace(exit_code=code, stdout="", stderr="")


class FakeSandbox:
    def __init__(self, codes: list[tuple[str, int]] | None = None) -> None:
        self.commands = FakeCommands(codes)

    def get_host(self, port: int) -> str:
        return f"https://{port}-sbx1.e2b.example"


async def _no_sleep(_: float) -> None:
    return None


# contract-test: supporting surface=rest_api assertions=code-run.cloud.project-preview
@pytest.mark.anyio
async def test_start_dev_server_reuses_listening_port(monkeypatch: pytest.MonkeyPatch) -> None:
    async def probe(sandbox: Any, url: str) -> bool:
        return True

    async def admits(sandbox: Any, host: str) -> bool:
        return host == HOST

    monkeypatch.setattr("backend.apps.code.project_sandbox_command._probe", probe)
    monkeypatch.setattr("backend.apps.code.project_sandbox_preview._admits_host", admits)
    sandbox = FakeSandbox()
    assert await start_dev_server(sandbox, "web", sleep=_no_sleep) == HOST
    assert sandbox.commands.lines == []


# Recipe proof 22 Nov: a dev server the test run had started kept the port; Vite blocked the preview host.
# contract-test: supporting surface=rest_api assertions=code-run.cloud.project-preview
@pytest.mark.anyio
async def test_start_dev_server_replaces_a_server_that_blocks_the_preview_host(monkeypatch: pytest.MonkeyPatch) -> None:
    probes = iter([True, False, False, True])  # foreign server, stopped, starting, ours ready
    started: list[str] = []

    async def probe(sandbox: Any, url: str) -> bool:
        return next(probes)

    admitted = iter([False, True])  # the foreign server refuses the host, ours admits it

    async def admits(sandbox: Any, host: str) -> bool:
        return next(admitted)

    async def start_background(sandbox: Any, command: Any, line: str) -> str:
        started.append(line)
        return "log"

    monkeypatch.setattr("backend.apps.code.project_sandbox_command._probe", probe)
    monkeypatch.setattr("backend.apps.code.project_sandbox_preview._admits_host", admits)
    monkeypatch.setattr("backend.apps.code.project_sandbox_command._start_background", start_background)
    sandbox = FakeSandbox()
    assert await start_dev_server(sandbox, "web", sleep=_no_sleep) == HOST
    assert any("/proc/net/tcp" in line and ":1435$" in line for line in sandbox.commands.lines)
    assert len(started) == 1 and f"__VITE_ADDITIONAL_SERVER_ALLOWED_HOSTS={HOST}" in started[0]


# contract-test: supporting surface=rest_api assertions=code-run.cloud.project-preview
@pytest.mark.anyio
async def test_the_host_check_treats_a_vite_block_as_refused() -> None:
    from backend.apps.code.project_sandbox_preview import _admits_host

    class Answer(FakeCommands):
        def __init__(self, code: str) -> None:
            super().__init__()
            self.code = code

        async def run(self, line: str, timeout: float = 0, user: str | None = None) -> Any:
            self.lines.append(line)
            return SimpleNamespace(exit_code=0, stdout=self.code, stderr="")

    for code, admitted in (("200", True), ("403", False), ("000", False)):
        sandbox = FakeSandbox()
        sandbox.commands = Answer(code)
        assert await _admits_host(sandbox, HOST) is admitted
        assert f"Host: {HOST}" in sandbox.commands.lines[0]


# contract-test: supporting surface=rest_api assertions=code-run.cloud.project-preview
@pytest.mark.anyio
async def test_start_dev_server_without_dev_script_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    async def probe(sandbox: Any, url: str) -> bool:
        return False

    monkeypatch.setattr("backend.apps.code.project_sandbox_command._probe", probe)
    with pytest.raises(ProjectPreviewError, match="dev script"):
        await start_dev_server(FakeSandbox([("scripts?.dev", 3)]), "web", sleep=_no_sleep)


# contract-test: supporting surface=rest_api assertions=code-run.cloud.project-preview
@pytest.mark.anyio
async def test_start_dev_server_installs_then_starts_and_probes(monkeypatch: pytest.MonkeyPatch) -> None:
    probes = iter([False, False, True])
    started: list[str] = []

    async def probe(sandbox: Any, url: str) -> bool:
        return next(probes)

    async def start_background(sandbox: Any, command: Any, line: str) -> str:
        started.append(line)
        return "log"

    async def admits(sandbox: Any, host: str) -> bool:
        return True

    monkeypatch.setattr("backend.apps.code.project_sandbox_command._probe", probe)
    monkeypatch.setattr("backend.apps.code.project_sandbox_preview._admits_host", admits)
    monkeypatch.setattr("backend.apps.code.project_sandbox_command._start_background", start_background)
    sandbox = FakeSandbox([("test -d node_modules", 1), ("scripts?.dev", 4)])  # a dev script without Vite
    assert await start_dev_server(sandbox, "web", sleep=_no_sleep) == HOST
    assert any("npm install" in line for line in sandbox.commands.lines)
    assert len(started) == 1 and "npm run dev" in started[0] and "--config" not in started[0]


# Recipe proof 22 Nov: Vite 5.4.21 ignores the allowed-hosts variable and blocked the preview host.
# contract-test: supporting surface=rest_api assertions=code-run.cloud.project-preview
@pytest.mark.anyio
async def test_a_vite_app_starts_through_a_config_that_admits_the_preview_host(monkeypatch: pytest.MonkeyPatch) -> None:
    probes = iter([False, True])
    started: list[str] = []
    admitted = iter([True])

    async def probe(sandbox: Any, url: str) -> bool:
        return next(probes)

    async def admits(sandbox: Any, host: str) -> bool:
        return next(admitted)

    async def start_background(sandbox: Any, command: Any, line: str) -> str:
        started.append(line)
        return "log"

    monkeypatch.setattr("backend.apps.code.project_sandbox_command._probe", probe)
    monkeypatch.setattr("backend.apps.code.project_sandbox_preview._admits_host", admits)
    monkeypatch.setattr("backend.apps.code.project_sandbox_command._start_background", start_background)
    sandbox = FakeSandbox()
    assert await start_dev_server(sandbox, "web", sleep=_no_sleep) == HOST
    written = [line for line in sandbox.commands.lines if preview.VITE_PREVIEW_CONFIG in line]
    assert len(written) == 1 and "allowedHosts" in written[0] and f'"{HOST}"' in written[0]
    assert preview.VITE_PREVIEW_CONFIG.startswith("node_modules/")  # never written back to the Project
    assert f"--config {preview.VITE_PREVIEW_CONFIG}" in started[0]


# contract-test: supporting surface=rest_api assertions=code-run.cloud.project-preview
@pytest.mark.anyio
async def test_a_dev_server_that_still_refuses_the_preview_host_fails_with_a_clear_message(
        monkeypatch: pytest.MonkeyPatch) -> None:
    probes = iter([False, True])

    async def probe(sandbox: Any, url: str) -> bool:
        return next(probes)

    async def admits(sandbox: Any, host: str) -> bool:
        return False

    async def start_background(sandbox: Any, command: Any, line: str) -> str:
        return "log"

    monkeypatch.setattr("backend.apps.code.project_sandbox_command._probe", probe)
    monkeypatch.setattr("backend.apps.code.project_sandbox_preview._admits_host", admits)
    monkeypatch.setattr("backend.apps.code.project_sandbox_command._start_background", start_background)
    with pytest.raises(ProjectPreviewError, match="refuses the preview address"):
        await start_dev_server(FakeSandbox(), "web", sleep=_no_sleep)


# contract-test: supporting surface=rest_api assertions=code-run.cloud.project-preview
@pytest.mark.anyio
async def test_start_dev_server_times_out(monkeypatch: pytest.MonkeyPatch) -> None:
    async def probe(sandbox: Any, url: str) -> bool:
        return False

    async def start_background(sandbox: Any, command: Any, line: str) -> str:
        return "log"

    monkeypatch.setattr("backend.apps.code.project_sandbox_command._probe", probe)
    monkeypatch.setattr("backend.apps.code.project_sandbox_command._start_background", start_background)
    with pytest.raises(ProjectPreviewError, match="not become ready"):
        await start_dev_server(FakeSandbox(), "", sleep=_no_sleep, ready_timeout=0.02)


# 5. worker session
class FakeService:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error

    async def ensure_ready(self, **_: Any) -> Any:
        if self.error:
            raise self.error
        return SimpleNamespace(sandbox_id="sbx1")


def _payload(**over: Any) -> dict[str, Any]:
    return {"user_id": "u1", "chat_id": "c1", "project_id": "p1", "cwd": "web", **over}


async def _run_session(monkeypatch: pytest.MonkeyPatch, service: FakeService, start: Any = None) -> list[dict]:
    patches: list[dict] = []

    async def patch(session_id: str, data: dict) -> None:
        patches.append(data)

    async def connect(sandbox_id: str, secrets_manager: Any = None) -> Any:
        return object()

    async def default_start(sandbox: Any, folder: str, sleep: Any = None) -> str:
        return HOST

    monkeypatch.setattr(preview, "start_dev_server", start or default_start)
    await run_project_sandbox_preview_session(
        cache_service=None, session_id="s1", payload=_payload(), patch=patch, service=service, connect=connect)
    return patches


# contract-test: supporting surface=rest_api assertions=code-run.cloud.project-preview
@pytest.mark.anyio
async def test_session_success_patches_running_without_token(monkeypatch: pytest.MonkeyPatch) -> None:
    patches = await _run_session(monkeypatch, FakeService())
    last = patches[-1]
    assert last["status"] == "running"
    assert last["project_sandbox_id"] == "sbx1"
    assert last["project_preview"] == {"host": HOST, "user_id": "u1", "chat_id": "c1", "project_id": "p1"}
    assert TRAFFIC_TOKEN not in json.dumps(patches)
    assert "token" not in json.dumps(patches).lower()


# contract-test: supporting surface=rest_api assertions=code-run.cloud.project-preview
@pytest.mark.anyio
async def test_session_no_device_fails_with_device_message(monkeypatch: pytest.MonkeyPatch) -> None:
    patches = await _run_session(monkeypatch, FakeService(ProjectSandboxUnavailable("no_device")))
    assert patches[-1]["status"] == "failed"
    assert "keep OpenMates open on a device" in patches[-1]["error"]


# contract-test: supporting surface=rest_api assertions=code-run.cloud.project-preview
@pytest.mark.anyio
async def test_session_preview_error_fails_with_its_message(monkeypatch: pytest.MonkeyPatch) -> None:
    async def failing(sandbox: Any, folder: str, sleep: Any = None) -> str:
        raise ProjectPreviewError("Installing the app's dependencies failed.")

    patches = await _run_session(monkeypatch, FakeService(), start=failing)
    assert patches[-1]["status"] == "failed"
    assert patches[-1]["error"] == "Installing the app's dependencies failed."


# 6. gateway upstream
class FakeKVCache:
    def __init__(self, values: dict[str, Any]) -> None:
        self.values = values

    async def get(self, key: str) -> Any:
        return self.values.get(key)


def _session() -> dict[str, Any]:
    return {"status": "running", "project_sandbox_id": "sbx1",
            "project_preview": {"host": HOST, "user_id": "u1", "chat_id": "c1", "project_id": "p1"}}


# contract-test: supporting surface=rest_api assertions=code-run.cloud.project-preview
@pytest.mark.anyio
async def test_upstream_returns_host_and_traffic_header() -> None:
    record = {"sandbox_id": "sbx1", "traffic_access_token": TRAFFIC_TOKEN}
    cache = FakeKVCache({sandbox_record_key("u1", "c1", "p1"): json.dumps(record)})
    assert await project_preview_upstream(cache, _session()) == (
        f"https://{HOST}", {"e2b-traffic-access-token": TRAFFIC_TOKEN})


# contract-test: supporting surface=rest_api assertions=code-run.cloud.project-preview
@pytest.mark.anyio
async def test_upstream_none_on_mismatch_or_missing_record() -> None:
    key = sandbox_record_key("u1", "c1", "p1")
    other = FakeKVCache({key: {"sandbox_id": "sbx-other", "traffic_access_token": TRAFFIC_TOKEN}})
    assert await project_preview_upstream(other, _session()) is None
    assert await project_preview_upstream(FakeKVCache({}), _session()) is None


# 7. keep alive
class FakeTouchService:
    def __init__(self) -> None:
        self.touched: list[dict] = []

    async def touch(self, **kwargs: Any) -> None:
        self.touched.append(kwargs)


# contract-test: supporting surface=rest_api assertions=code-run.cloud.project-preview
@pytest.mark.anyio
async def test_keep_alive_touches_at_most_once_a_minute_and_only_running() -> None:
    service = FakeTouchService()
    session = {**_session(), "last_sandbox_touch_at": 1000.0}
    assert await keep_project_preview_alive(service, session, now=1030.0) is False
    assert await keep_project_preview_alive(service, session, now=1061.0) is True
    assert service.touched == [{"user_id": "u1", "chat_id": "c1", "project_id": "p1"}]
    assert await keep_project_preview_alive(service, {**session, "status": "stopped"}, now=5000.0) is False
    assert await keep_project_preview_alive(service, {"status": "running"}, now=5000.0) is False
    assert len(service.touched) == 1


# 8. route payload
# contract-test: supporting surface=rest_api assertions=code-run.cloud.project-preview
@pytest.mark.anyio
@pytest.mark.parametrize("extra", [{"shared_context": "x"}, {"auto_started": True}])
async def test_route_refuses_shared_or_auto_started(extra: dict) -> None:
    body = route.ApplicationPreviewStartRequest(
        chat_id="c1", project_sandbox=route.ProjectSandboxPreviewTarget(project_id="p1"), **extra)
    with pytest.raises(HTTPException) as exc:
        await route.collect_project_sandbox_preview_payload(
            application_embed_id="e1", body=body, current_user=SimpleNamespace(id="u1"),
            cache_service=None, directus_service=None)
    assert exc.value.status_code == 400


# contract-test: supporting surface=rest_api assertions=code-run.cloud.project-preview
@pytest.mark.anyio
async def test_route_refuses_escaping_folder_and_builds_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    async def allow(**_: Any) -> None:
        return None

    monkeypatch.setattr(route, "_strict_owner_chat_access", allow)
    user = SimpleNamespace(id="u1")
    bad = route.ApplicationPreviewStartRequest(
        chat_id="c1", project_sandbox=route.ProjectSandboxPreviewTarget(project_id="p1", cwd="a/../b"))
    with pytest.raises(HTTPException) as exc:
        await route.collect_project_sandbox_preview_payload(
            application_embed_id="e1", body=bad, current_user=user, cache_service=None, directus_service=None)
    assert exc.value.status_code == 400
    good = route.ApplicationPreviewStartRequest(
        chat_id="c1", project_sandbox=route.ProjectSandboxPreviewTarget(project_id="p1", cwd="web"))
    payload = await route.collect_project_sandbox_preview_payload(
        application_embed_id="e1", body=good, current_user=user, cache_service=None, directus_service=None)
    assert payload["source"] == "project_sandbox" and payload["cwd"] == "web" and payload["user_id"] == "u1"


# 9. gateway 410
# contract-test: supporting surface=rest_api assertions=code-run.cloud.project-preview
@pytest.mark.anyio
async def test_gateway_returns_410_when_sandbox_is_gone(monkeypatch: pytest.MonkeyPatch) -> None:
    async def validate(*_: Any, **__: Any) -> dict:
        return {**_session(), "preview_source": "project_sandbox"}

    async def no_upstream(cache_service: Any, session: dict) -> None:
        return None

    monkeypatch.setattr(gateway, "validate_preview_gateway_access", validate)
    monkeypatch.setattr(preview, "project_preview_upstream", no_upstream)
    response = await gateway.build_preview_gateway_response(object(), "s1", "tok", "index.html", now=1.0)
    assert response.status_code == 410
    assert b"sandbox_stopped" in response.body
