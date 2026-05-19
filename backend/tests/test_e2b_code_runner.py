# backend/tests/test_e2b_code_runner.py
#
# Regression tests for the restricted E2B code runner provider.
# These tests cover dependency command planning without creating a sandbox,
# keeping package installation behavior deterministic and safe to validate in
# the API test container.

from __future__ import annotations

import time

import pytest

from backend.shared.providers.e2b_code_runner import (
    CodeRunCancelled,
    CodeRunDependencyInstall,
    CodeRunFile,
    _dependency_commands,
    _run_interruptible_command,
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
