# backend/tests/test_e2b_image_to_html_renderer.py
#
# Contract tests for the E2B-backed HTML renderer used by Code image-to-HTML.
# Generated HTML is untrusted, so rendering must happen in E2B rather than in a
# local Playwright instance on OpenMates API or worker hosts.

from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.shared.providers.e2b_html_renderer import render_html_in_e2b


class FakeFiles:
    def __init__(self) -> None:
        self.writes: list[dict[str, str]] = []

    def write_files(self, files: list[dict[str, str]]) -> None:
        self.writes.extend(files)


class FakeCommands:
    def __init__(self) -> None:
        self.commands: list[tuple[str, dict[str, object]]] = []

    def run(self, command: str, **kwargs: object) -> SimpleNamespace:
        self.commands.append((command, kwargs))
        return SimpleNamespace(stdout="iVBORw0KGgo=", exit_code=0)


class FakeSandbox:
    create_kwargs: dict[str, object] | None = None
    killed_ids: list[str] = []

    def __init__(self) -> None:
        self.sandbox_id = "sandbox-render-1"
        self.files = FakeFiles()
        self.commands = FakeCommands()

    @classmethod
    def create(cls, **kwargs: object) -> "FakeSandbox":
        cls.create_kwargs = kwargs
        return cls()

    @classmethod
    def kill(cls, *, sandbox_id: str, api_key: str) -> bool:
        cls.killed_ids.append(f"{sandbox_id}:{api_key}")
        return True


def test_render_html_in_e2b_writes_only_index_html_and_cleans_up() -> None:
    result = render_html_in_e2b(
        html="<html><body>Hello</body></html>",
        api_key="test-e2b-key",
        sandbox_cls=FakeSandbox,
        now=lambda: 100.0,
        monotonic=lambda: 101.25,
    )

    assert result.sandbox_id == "sandbox-render-1"
    assert result.screenshot_bytes == b"\x89PNG\r\n\x1a\n"
    assert result.duration_seconds == 1.25
    assert FakeSandbox.create_kwargs == {
        "api_key": "test-e2b-key",
        "secure": True,
        "allow_internet_access": True,
        "network": {"allow_public_traffic": False},
    }
    assert FakeSandbox.killed_ids == ["sandbox-render-1:test-e2b-key"]


def test_render_command_uses_browser_inside_sandbox() -> None:
    sandbox = FakeSandbox()

    render_html_in_e2b(
        html="<html><body>Hello</body></html>",
        api_key="test-e2b-key",
        sandbox_cls=lambda **_kwargs: sandbox,
    )

    assert sandbox.files.writes == [{"path": "index.html", "data": "<html><body>Hello</body></html>"}]
    assert len(sandbox.commands.commands) == 2
    install_command, install_kwargs = sandbox.commands.commands[0]
    assert "npm install" in install_command
    assert install_kwargs.get("timeout")
    command, kwargs = sandbox.commands.commands[1]
    assert "playwright" in command.lower() or "chromium" in command.lower()
    assert "--disable-background-networking" in command
    assert "--host-resolver-rules" in command
    assert "width: 1440, height: 1200" in command
    assert kwargs.get("timeout") == 0


def test_render_command_uses_source_viewport_when_provided() -> None:
    sandbox = FakeSandbox()

    render_html_in_e2b(
        html="<html><body>Hello</body></html>",
        api_key="test-e2b-key",
        viewport_width=1520,
        viewport_height=929,
        sandbox_cls=lambda **_kwargs: sandbox,
    )

    command, _kwargs = sandbox.commands.commands[1]
    assert "width: 1520, height: 929" in command


def test_render_html_in_e2b_rejects_empty_screenshot_stdout() -> None:
    class EmptyStdoutCommands(FakeCommands):
        def run(self, command: str, **kwargs: object) -> SimpleNamespace:
            self.commands.append((command, kwargs))
            return SimpleNamespace(stdout="", stderr="missing screenshot", exit_code=1)

    class EmptyStdoutSandbox(FakeSandbox):
        def __init__(self) -> None:
            super().__init__()
            self.commands = EmptyStdoutCommands()

    with pytest.raises(RuntimeError, match="E2B HTML render failed"):
        render_html_in_e2b(
            html="<html><body>Hello</body></html>",
            api_key="test-e2b-key",
            sandbox_cls=EmptyStdoutSandbox,
        )
