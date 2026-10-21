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
    assert set(by_path) == {"package.json", "src/App.svelte"}
    plan = plan_application_preview_startup(
        files=[ApplicationPreviewFile(path=file["path"], content=file["content"]) for file in files],
        entrypoints=[ApplicationPreviewEntrypoint(name="frontend", command="npm run dev", port=5173)],
    )
    planned = {file.path: file.content for file in plan.files}
    main_ts = planned["src/main.ts"]

    assert "latest" not in package_json
    assert '"vite":"^5.4.21"' in package_json
    assert '"svelte":"^5.55.7"' in package_json
    assert "import { mount } from 'svelte';" in main_ts
    assert "new App" not in main_ts
    assert 'src="/src/main.ts"' in planned["index.html"]
    assert "mount(App, { target });" in main_ts
    assert plan_application_preview_startup(
        files=plan.files,
        entrypoints=[ApplicationPreviewEntrypoint(name="frontend", command="npm run dev", port=5173)],
    ).files == plan.files


@pytest.mark.parametrize("main_path", ["src/main.ts", "src/main.js"])
# contract-test: supporting surface=gui.web assertions=app-skills.media.application-screenshot
def test_minimal_svelte_preview_keeps_supplied_mounting_script(main_path: str) -> None:
    files = [
        ApplicationPreviewFile(path="package.json", content=json.dumps({
            "dependencies": {"svelte": "^5.55.7", "vite": "^5.4.21", "@sveltejs/vite-plugin-svelte": "^4.0.4"},
        })),
        ApplicationPreviewFile(path="src/App.svelte", content="<main>Hello</main>", source_embed_id="app-source"),
        ApplicationPreviewFile(path=main_path, content="// User-owned entrypoint", source_embed_id="main-source"),
    ]
    plan = plan_application_preview_startup(
        files=files,
        entrypoints=[ApplicationPreviewEntrypoint(name="frontend", command="npm run dev", port=5173)],
    )
    assert plan.files[:3] == files
    assert [file.path for file in plan.files] == [file.path for file in files] + ["index.html"]
    assert f'src="/{main_path}"' in plan.files[-1].content


# contract-test: supporting surface=gui.web assertions=app-skills.media.application-screenshot
def test_svelte_preview_preserves_custom_index_and_bootstrap() -> None:
    files = [
        ApplicationPreviewFile(path="package.json", content=json.dumps({
            "dependencies": {"svelte": "^5.55.7", "vite": "^5.4.21", "@sveltejs/vite-plugin-svelte": "^4.0.4"},
        })),
        ApplicationPreviewFile(path="src/App.svelte", content="<main>Hello</main>"),
        ApplicationPreviewFile(path="index.html", content='<div id="custom"></div><script type="module" src="/bootstrap.js"></script>'),
        ApplicationPreviewFile(path="bootstrap.js", content="// Custom application mounting"),
    ]
    plan = plan_application_preview_startup(
        files=files,
        entrypoints=[ApplicationPreviewEntrypoint(name="frontend", command="npm run dev", port=5173)],
    )
    assert plan.files == files


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
    assert plan.install_commands == ["npm install --ignore-scripts --no-audit --no-fund --prefer-offline"]
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
    assert "/home/user/.cache/openmates-application-capture" in sandbox.commands.calls[0][0]
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


@pytest.mark.parametrize("template", ["", "prepared-preview-v1"])
# contract-test: supporting surface=gui.web assertions=code-run.execution.stream-status-visible,app-skills.media.application-screenshot
def test_preview_exposes_ready_runtime_before_screenshot_capture(monkeypatch, template: str) -> None:
    import sys
    from backend.shared.providers import e2b_application_preview as provider
    monkeypatch.setenv(provider.APPLICATION_PREVIEW_TEMPLATE_ENV, template)
    events = []
    class Sandbox:
        sandbox_id = "fixture-sandbox"
        files = SimpleNamespace(write_files=lambda _files: None)
        commands = SimpleNamespace(run=lambda *_args, **_kwargs: None)
        @classmethod
        def create(cls, **kwargs):
            assert kwargs["secure"] is True
            assert kwargs["template"] == (template or None)
            assert kwargs["envs"] == (
                {"PLAYWRIGHT_BROWSERS_PATH": f"{provider.APPLICATION_CAPTURE_DIRECTORY}/browsers"}
                if template else None
            )
            return cls()
        def get_host(self, port): return f"{port}-fixture.e2b.app"
    monkeypatch.setitem(sys.modules, "e2b", SimpleNamespace(Sandbox=Sandbox))
    monkeypatch.setattr(provider, "_wait_for_preview_ready", lambda _url: events.append("healthy"))
    def capture(_sandbox, _port):
        assert events == ["healthy", "runtime-visible"]
        return PNG_BYTES
    monkeypatch.setattr(provider, "_sandbox_screenshot_bytes", capture)
    def ready(runtime):
        assert runtime.upstream_base_url == "https://5173-fixture.e2b.app"
        assert runtime.latest_screenshot_bytes is None
        events.append("runtime-visible")
    result = start_application_preview_in_e2b(files=[ApplicationPreviewFile(path="index.html", content="<main>Fixture</main>")],
        entrypoints=[ApplicationPreviewEntrypoint(name="frontend", command="python3 -m http.server 5173", port=5173)],
        api_key="fixture", on_runtime_ready=ready)
    assert result.latest_screenshot_bytes == PNG_BYTES


# contract-test: supporting surface=gui.web assertions=app-skills.media.application-screenshot
@pytest.mark.parametrize('variation,expected', [
    ('prepared', True), ('unknown-package', False), ('wrong-version', False),
    ('lockfile', False), ('custom-config', False), ('nested-manifest', False),
    ('override', False), ('binary', False), ('supplied-node-modules', False),
])
def test_prepared_fast_path_preserves_dependency_and_custom_config_fallbacks(variation, expected):
    from backend.shared.providers import e2b_application_preview as provider
    dependencies = {name: '^' + version for name, version in provider.PREPARED_PREVIEW_DEPENDENCIES.items()}
    manifest = {'dependencies': dependencies, 'scripts': {'dev': 'vite'}}
    extra = []
    if variation == 'unknown-package':
        dependencies['some-other-library'] = '^1.0.0'
    if variation == 'wrong-version':
        dependencies['svelte'] = '^4.0.0'
    if variation == 'override':
        manifest['overrides'] = {'vite': '^4.0.0'}
    if variation == 'lockfile':
        extra = [ApplicationPreviewFile(path='package-lock.json', content='{}')]
    if variation == 'custom-config':
        extra = [ApplicationPreviewFile(path='vite.config.ts', content='export default {}')]
    if variation == 'nested-manifest':
        extra = [ApplicationPreviewFile(path='other/package.json', content='{}')]
    if variation == 'binary':
        extra = [ApplicationPreviewFile(path='asset.png', content_base64='AA==')]
    if variation == 'supplied-node-modules':
        extra = [ApplicationPreviewFile(path='node_modules/vite/package.json', content='{}')]
    plan = provider.plan_application_preview_startup(files=[
        ApplicationPreviewFile(path='package.json', content=json.dumps(manifest)),
        ApplicationPreviewFile(path='src/App.svelte', content='<h1>Current revision</h1>'), *extra,
    ], entrypoints=[ApplicationPreviewEntrypoint(name='frontend', command='npm run dev', port=5173)])
    assert provider._can_batch_prepared_vite_preview(plan) is expected


# contract-test: supporting surface=gui.web assertions=app-skills.media.application-screenshot
def test_prepared_batch_keeps_current_source_exact_hosts_and_install_fallback():
    import base64
    import re
    from backend.shared.providers import e2b_application_preview as provider
    commands = []
    uploaded = []
    plan = provider.plan_application_preview_startup(files=[
        ApplicationPreviewFile(path='package.json', content=json.dumps({'dependencies': provider.PREPARED_PREVIEW_DEPENDENCIES})),
        ApplicationPreviewFile(path='src/App.svelte', content='<h1>Current revision</h1>'),
    ], entrypoints=[ApplicationPreviewEntrypoint(name='frontend', command='npm run dev', port=5173)])
    sandbox = SimpleNamespace(commands=SimpleNamespace(run=lambda command, **kwargs: commands.append((command, kwargs))),
                              files=SimpleNamespace(write_files=uploaded.extend))
    provider._start_batched_vite_preview(sandbox, plan, ['5173-this-sandbox.e2b.app'])
    assert len(commands) == 1
    encoded = re.search(r"Buffer.from\('([A-Za-z0-9+/=]+)', 'base64'\)", commands[0][0]).group(1)
    setup = json.loads(base64.b64decode(encoded))
    files = {entry['path']: entry['data'] for entry in uploaded}
    assert files['src/App.svelte'] == '<h1>Current revision</h1>'
    assert '5173-this-sandbox.e2b.app' in files[provider.VITE_OPENMATES_CONFIG_PATH]
    assert 'allowedHosts: true' not in files[provider.VITE_OPENMATES_CONFIG_PATH]
    assert setup['install'] == plan.install_commands
    assert setup['expected'] == provider.PREPARED_PREVIEW_DEPENDENCIES
    assert 'files' not in setup
    assert 'Current revision' not in commands[0][0]


# contract-test: supporting surface=gui.web assertions=app-skills.media.application-screenshot
@pytest.mark.parametrize('cache_matches', [True, False])
def test_batched_setup_executes_cached_or_install_fallback_and_waits_for_server(tmp_path, cache_matches):
    import os
    import shutil
    import signal
    import socket
    import subprocess
    from backend.shared.providers import e2b_application_preview as provider
    if shutil.which('node') is None:
        pytest.skip('Node is needed to exercise the sandbox bootstrap program')
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]
    for name, version in provider.PREPARED_PREVIEW_DEPENDENCIES.items():
        package = tmp_path / 'node_modules' / name / 'package.json'
        package.parent.mkdir(parents=True, exist_ok=True)
        package.write_text(json.dumps({'version': version if cache_matches else '0.0.0'}))
    server = "require('fs').writeFileSync('server.pid', String(process.pid)); require('http').createServer((req,res)=>res.end('ok')).listen(%d,'127.0.0.1');" % port
    plan = provider.ApplicationPreviewPlan(files=[
        ApplicationPreviewFile(path='server.cjs', content=server),
        ApplicationPreviewFile(path='package.json', content=json.dumps({'dependencies': provider.PREPARED_PREVIEW_DEPENDENCIES})),
    ], install_commands=['node -e "require(\'fs\').writeFileSync(\'installed\', \'yes\')"'],
       start_commands=[{'name': 'frontend', 'command': 'node server.cjs', 'port': port}])
    def upload(entries):
        for entry in entries:
            target = tmp_path / entry['path']
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(entry['data'])
    def execute(command, **kwargs):
        result = subprocess.run(['bash', '-lc', command], cwd=tmp_path, capture_output=True, timeout=10)
        return SimpleNamespace(exit_code=result.returncode)
    sandbox = SimpleNamespace(files=SimpleNamespace(write_files=upload), commands=SimpleNamespace(run=execute))
    try:
        provider._start_batched_vite_preview(sandbox, plan, ['127.0.0.1'])
        assert (tmp_path / 'installed').exists() is (not cache_matches)
        assert (tmp_path / 'server.pid').exists()
    finally:
        if (tmp_path / 'server.pid').exists():
            os.kill(int((tmp_path / 'server.pid').read_text()), signal.SIGTERM)


# contract-test: supporting surface=gui.web assertions=app-skills.media.application-screenshot
@pytest.mark.parametrize('dev,eligible', [('vite', True), ('vite --host 0.0.0.0', True), ('vite && echo custom', False), (['vite'], False)])
def test_warm_template_preserves_custom_dev_scripts(dev, eligible):
    from backend.shared.providers import e2b_application_preview as p
    plan = p.plan_application_preview_startup(files=[
        ApplicationPreviewFile(path='package.json', content=json.dumps({'scripts': {'dev': dev}, 'dependencies': p.PREPARED_PREVIEW_DEPENDENCIES})),
        ApplicationPreviewFile(path='src/App.svelte', content='<h1>New revision</h1>'),
    ], entrypoints=[ApplicationPreviewEntrypoint(name='frontend', command='npm run dev', port=5173)])
    assert p._can_warm_start_preview(plan) is eligible


# contract-test: supporting surface=gui.web assertions=app-skills.media.application-screenshot
def test_warm_activation_uploads_source_and_exact_hosts_before_content_free_signal():
    import hashlib
    from backend.shared.providers import e2b_application_preview as p
    uploads = []
    plan = p.plan_application_preview_startup(files=[
        ApplicationPreviewFile(path='package.json', content=json.dumps({'scripts': {'dev': 'vite'}, 'dependencies': p.PREPARED_PREVIEW_DEPENDENCIES})),
        ApplicationPreviewFile(path='src/App.svelte', content='<h1>New revision</h1>'),
    ], entrypoints=[ApplicationPreviewEntrypoint(name='frontend', command='npm run dev', port=5173)])
    sandbox = SimpleNamespace(files=SimpleNamespace(write_files=uploads.append))
    revision = p._activate_warm_preview(sandbox, plan, ['5173-exact.e2b.app'])
    assert len(uploads) == 1
    source = {file['path']: file['data'] for file in uploads[0]}
    assert source['src/App.svelte'] == '<h1>New revision</h1>'
    assert "allowedHosts: ['5173-exact.e2b.app']" in source[p.VITE_OPENMATES_CONFIG_PATH]
    activation = json.loads(source.pop('/tmp/openmates-preview-request.json'))
    assert activation['revision'] == revision
    assert activation['port'] == 5173
    assert activation['files'] == {path: hashlib.sha256(content.encode()).hexdigest() for path, content in source.items()}


# contract-test: supporting surface=gui.web assertions=app-skills.media.application-screenshot
@pytest.mark.parametrize('actual,expected', [('older-revision', 503), ('current-revision', 200)])
def test_warm_readiness_requires_current_revision_header(monkeypatch, actual, expected):
    from backend.shared.providers import e2b_application_preview as p
    class Response:
        status = 200
        headers = {'X-OpenMates-Preview-Ready': actual}
        def __enter__(self):
            return self
        def __exit__(self, *_args):
            return None
    monkeypatch.setattr(p, 'urlopen', lambda *_args, **_kwargs: Response())
    sandbox = SimpleNamespace(files=SimpleNamespace(read=lambda _path: '{"status":"running"}'))
    assert p._fetch_warm_preview_status(sandbox, 'https://5173-example.e2b.app', 'current-revision') == expected


# contract-test: supporting surface=gui.web assertions=app-skills.media.application-screenshot
@pytest.mark.parametrize('custom', ['entrypoint', 'predev', 'postdev'])
def test_warm_start_keeps_custom_bootstrap_and_lifecycle_on_normal_path(custom):
    from backend.shared.providers import e2b_application_preview as p
    scripts = {'dev': 'vite'}
    if custom in {'predev', 'postdev'}:
        scripts[custom] = 'node setup.js'
    files = [ApplicationPreviewFile(path='package.json', content=json.dumps({'scripts': scripts, 'dependencies': p.PREPARED_PREVIEW_DEPENDENCIES})),
             ApplicationPreviewFile(path='src/App.svelte', content='<h1>App</h1>')]
    if custom == 'entrypoint':
        files.append(ApplicationPreviewFile(path='index.html', content='<script type="module" src="/custom.js"></script>'))
    plan = p.plan_application_preview_startup(files=files, entrypoints=[ApplicationPreviewEntrypoint(name='frontend', command='npm run dev', port=5173)])
    assert p._can_warm_start_preview(plan) is False


# contract-test: supporting surface=gui.web assertions=app-skills.media.application-screenshot
@pytest.mark.parametrize('paths', [
    ['vite.config.openmates.mjs'],
    ['./vite.config.openmates.mjs'],
    ['.cache/openmates-application-capture'],
    ['.cache/openmates-application-capture/runtime.mjs'],
    [r'.cache\openmates-application-capture\runtime.mjs'],
    ['src/App.svelte', './src/App.svelte'],
    ['src/App.svelte', r'src\App.svelte'],
])
# contract-test: supporting surface=gui.web assertions=app-skills.media.application-screenshot
def test_preview_rejects_reserved_and_duplicate_paths_before_sandbox_creation(monkeypatch, paths):
    from backend.shared.providers import e2b_application_preview as p
    def unexpected_create(**_kwargs):
        pytest.fail('Unsafe input must be rejected before sandbox creation')
    monkeypatch.setitem(sys.modules, 'e2b', SimpleNamespace(Sandbox=SimpleNamespace(create=unexpected_create)))
    with pytest.raises(p.ApplicationPreviewPlanningError):
        p.start_application_preview_in_e2b(
            files=[ApplicationPreviewFile(path=path, content='untrusted source') for path in paths],
            entrypoints=[ApplicationPreviewEntrypoint(name='frontend', command='npm run dev', port=5173)],
            api_key='test-key',
        )
