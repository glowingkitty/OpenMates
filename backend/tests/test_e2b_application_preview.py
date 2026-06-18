# backend/tests/test_e2b_application_preview.py
#
# Regression tests for E2B application-preview planning.
# These tests keep sandbox creation out of scope and verify deterministic file,
# dependency, and dev-server command planning for the later worker slice.

from __future__ import annotations

import pytest

from backend.shared.providers.e2b_application_preview import (
    ApplicationPreviewEntrypoint,
    ApplicationPreviewFile,
    ApplicationPreviewPlanningError,
    _vite_allowed_hosts,
    _wait_for_preview_ready,
    _with_vite_preview_settings,
    _with_vite_allowed_hosts,
    _write_vite_allowed_hosts_config,
    plan_application_preview_startup,
)


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


def test_preview_planning_adds_tailwind_configs_when_generated_css_uses_directives() -> None:
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

    files_by_path = {file.path: file.content for file in plan.files}
    assert "tailwind.config.cjs" in files_by_path
    assert "postcss.config.cjs" in files_by_path
    assert "./src/**/*.{js,ts,jsx,tsx,svelte,html}" in files_by_path["tailwind.config.cjs"]
    assert "tailwindcss: {}" in files_by_path["postcss.config.cjs"]


def test_preview_planning_does_not_add_tailwind_configs_for_plain_css() -> None:
    plan = plan_application_preview_startup(
        files=[
            ApplicationPreviewFile(path="package.json", content='{"scripts":{"dev":"vite"},"devDependencies":{"tailwindcss":"latest"}}'),
            ApplicationPreviewFile(path="src/index.css", content="body { background: white; }\n"),
        ],
        entrypoints=[ApplicationPreviewEntrypoint(name="frontend", command="npm run dev", port=5173)],
    )

    assert "tailwind.config.cjs" not in {file.path for file in plan.files}
    assert "postcss.config.cjs" not in {file.path for file in plan.files}


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


def test_preview_keeps_existing_vite_config_for_framework_plugins() -> None:
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

    assert path is None
    assert sandbox.files.payloads == []


def test_preview_readiness_waits_through_transient_e2b_502() -> None:
    statuses = iter([502, 502, 200])
    sleeps: list[float] = []

    _wait_for_preview_ready(
        "https://5173-example.e2b.app/",
        timeout_seconds=5,
        interval_seconds=0.01,
        fetch_status=lambda _: next(statuses),
        sleep=sleeps.append,
    )

    assert sleeps == [0.01, 0.01]


def test_preview_readiness_times_out_with_last_status() -> None:
    with pytest.raises(RuntimeError, match="last status 502"):
        _wait_for_preview_ready(
            "https://5173-example.e2b.app/",
            timeout_seconds=0,
            fetch_status=lambda _: 502,
            sleep=lambda _: None,
        )


def test_preview_start_command_does_not_duplicate_vite_allowed_hosts_env() -> None:
    command = _with_vite_allowed_hosts(
        "__VITE_ADDITIONAL_SERVER_ALLOWED_HOSTS=custom.example npm run dev",
        ["5173-izr5goe7od08cvlqzemo8.e2b.app"],
    )

    assert command == "__VITE_ADDITIONAL_SERVER_ALLOWED_HOSTS=custom.example npm run dev"


@pytest.mark.parametrize("path", ["/etc/passwd", "../secret.txt", "src/../../secret.txt", ""])
def test_preview_planning_rejects_unsafe_paths(path: str) -> None:
    with pytest.raises(ApplicationPreviewPlanningError):
        plan_application_preview_startup(
            files=[ApplicationPreviewFile(path=path, content="x")],
            entrypoints=[ApplicationPreviewEntrypoint(name="frontend", command="npm run dev", port=5173)],
        )


def test_preview_planning_rejects_secret_like_file_content() -> None:
    with pytest.raises(ApplicationPreviewPlanningError, match="secrets"):
        plan_application_preview_startup(
            files=[ApplicationPreviewFile(path="src/main.ts", content="const apiKey = 'sk-test-secret-token-1234567890';")],
            entrypoints=[ApplicationPreviewEntrypoint(name="frontend", command="npm run dev", port=5173)],
        )


def test_preview_planning_requires_entrypoints_and_ports() -> None:
    with pytest.raises(ApplicationPreviewPlanningError, match="entrypoint"):
        plan_application_preview_startup(files=[ApplicationPreviewFile(path="index.html", content="ok")], entrypoints=[])

    with pytest.raises(ApplicationPreviewPlanningError, match="port"):
        plan_application_preview_startup(
            files=[ApplicationPreviewFile(path="index.html", content="ok")],
            entrypoints=[ApplicationPreviewEntrypoint(name="frontend", command="npm run dev", port=70_000)],
        )
