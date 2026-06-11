# backend/tests/test_e2b_code_runner.py
#
# Regression tests for the restricted E2B code runner provider.
# These tests cover dependency command planning without creating a sandbox,
# keeping package installation behavior deterministic and safe to validate in
# the API test container.

from __future__ import annotations

import sys
import time
from types import SimpleNamespace

import pytest

from backend.shared.providers.e2b_code_runner import (
    CodeRunCancelled,
    CodeRunDependencyInstall,
    CodeRunFile,
    _dependency_commands,
    _run_command_for_file,
    _run_interruptible_command,
    redact_execution_output,
    run_code_in_e2b,
)


class FakeCommandHandle:
    def __init__(self) -> None:
        self.killed = False

    def wait(self, on_stdout=None, on_stderr=None):
        while not self.killed:
            time.sleep(0.01)
        return type("Result", (), {"exit_code": 137})()

    def kill(self) -> bool:
        self.killed = True
        return True


class FakeCommands:
    def __init__(self) -> None:
        self.handle = FakeCommandHandle()

    def run(self, *_args, **_kwargs):
        return self.handle


class FakeSandbox:
    def __init__(self) -> None:
        self.commands = FakeCommands()


class FakeFiles:
    def write_files(self, _files):
        return None


class FakeE2BSandbox:
    create_kwargs: dict | None = None

    def __init__(self) -> None:
        self.sandbox_id = "sandbox-1"
        self.commands = SimpleNamespace(run=self._run_command)
        self.files = FakeFiles()
        self.killed = False

    def _run_command(self, *_args, **kwargs):
        if kwargs.get("background"):
            return SimpleNamespace(wait=lambda **_wait_kwargs: SimpleNamespace(exit_code=0))
        return SimpleNamespace(exit_code=0)

    @classmethod
    def create(cls, **kwargs):
        cls.create_kwargs = kwargs
        return cls()

    def kill(self) -> None:
        self.killed = True


def test_dependency_commands_install_selected_packages_without_manifests() -> None:
    commands = _dependency_commands(
        [CodeRunFile(path="main.py", language="python")],
        [
            CodeRunDependencyInstall(ecosystem="python", packages=("requests", "pandas==2.2.3")),
            CodeRunDependencyInstall(ecosystem="npm", packages=("axios",)),
        ],
    )

    assert commands == [
        ("Installing selected Python packages...", "python -m pip install pandas==2.2.3 requests"),
        ("Installing selected npm packages...", "npm install --ignore-scripts --no-audit --no-fund --package-lock=false axios"),
    ]


def test_dependency_commands_prefer_explicit_manifests() -> None:
    commands = _dependency_commands(
        [
            CodeRunFile(path="main.py", language="python"),
            CodeRunFile(path="requirements.txt", language=""),
            CodeRunFile(path="package.json", language=""),
        ],
        [
            CodeRunDependencyInstall(ecosystem="python", packages=("requests",)),
            CodeRunDependencyInstall(ecosystem="npm", packages=("axios",)),
        ],
    )

    assert commands == [
        ("Installing Python dependencies from requirements.txt...", "python -m pip install -r requirements.txt"),
        ("Installing JavaScript dependencies with npm install --ignore-scripts...", "npm install --ignore-scripts"),
    ]


@pytest.mark.parametrize(
    ("file", "expected_parts"),
    [
        (CodeRunFile(path="main.c", language="c"), ["command -v gcc", "gcc main.c -o /tmp/openmates-run-bin", "/tmp/openmates-run-bin"]),
        (CodeRunFile(path="main.cpp", language="cpp"), ["command -v g++", "g++ main.cpp -std=c++17 -o /tmp/openmates-run-bin", "/tmp/openmates-run-bin"]),
        (CodeRunFile(path="main.rs", language="rust"), ["command -v rustc", "rustc main.rs -o /tmp/openmates-run-bin", "/tmp/openmates-run-bin"]),
        (CodeRunFile(path="main.go", language="go"), ["command -v go", "go run main.go"]),
    ],
)
def test_run_command_supports_compiled_language_targets(file: CodeRunFile, expected_parts: list[str]) -> None:
    command = _run_command_for_file(file)

    for part in expected_parts:
        assert part in command


def test_redact_execution_output_allows_harmless_env_api_key_placeholder() -> None:
    output = "api_key = os.getenv('SERVICE_API_KEY', 'demo-placeholder')\nprint('ok')"

    assert redact_execution_output(output) == output


def test_interruptible_command_kills_active_handle_when_cancelled() -> None:
    sandbox = FakeSandbox()

    with pytest.raises(CodeRunCancelled):
        _run_interruptible_command(
            sandbox,
            "python main.py",
            300,
            lambda _kind, _text: None,
            lambda: True,
        )

    assert sandbox.commands.handle.killed is True


def test_run_code_passes_explicit_e2b_network_controls(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "e2b", SimpleNamespace(Sandbox=FakeE2BSandbox))

    result = run_code_in_e2b(
        [CodeRunFile(path="main.py", language="python", content="print('ok')", is_target=True)],
        "main.py",
        lambda _kind, _text: None,
        "test-key",
        enable_internet=False,
    )

    assert result.sandbox_id == "sandbox-1"
    assert FakeE2BSandbox.create_kwargs == {
        "api_key": "test-key",
        "secure": True,
        "allow_internet_access": False,
        "network": {"allow_public_traffic": False},
    }
