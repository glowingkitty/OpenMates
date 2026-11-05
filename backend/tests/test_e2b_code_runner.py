# backend/tests/test_e2b_code_runner.py
#
# Regression tests for the restricted E2B code runner provider.
# These tests cover dependency command planning without creating a sandbox,
# keeping package installation behavior deterministic and safe to validate in
# the API test container.

from __future__ import annotations

import json
import shlex
import sys
import time
from types import SimpleNamespace

import pytest

from backend.shared.providers.e2b_code_runner import (
    CodeRunCancelled,
    CodeRunDependencyInstall,
    CodeRunFile,
    _dependency_commands,
    _python_runtime_command,
    _python_versions_command,
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
    discovery_stdout: str = ""

    def __init__(self) -> None:
        self.sandbox_id = "sandbox-1"
        self.commands = SimpleNamespace(run=self._run_command)
        self.files = FakeFiles()
        self.killed = False

    def _run_command(self, *_args, **kwargs):
        if kwargs.get("background"):
            return SimpleNamespace(wait=lambda **_wait_kwargs: SimpleNamespace(exit_code=0))
        command = str(_args[0]) if _args else ""
        if "OPENMATES_CODE_RUN_DISCOVER_OUTPUTS" in command:
            return SimpleNamespace(exit_code=0, stdout=self.discovery_stdout, stderr="")
        return SimpleNamespace(exit_code=0)

    @classmethod
    def create(cls, **kwargs):
        cls.create_kwargs = kwargs
        return cls()

    def kill(self) -> None:
        self.killed = True


# contract-test: supporting surface=rest_api assertions=code-run.request.validated,code-run.execution.e2b-only
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


# contract-test: supporting surface=rest_api assertions=code-run.request.validated,code-run.execution.e2b-only
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
        (CodeRunFile(path="main.rs", language="rust"), ["command -v rustc", "rustc --edition=2021 main.rs -o /tmp/openmates-run-bin", "/tmp/openmates-run-bin"]),
        (CodeRunFile(path="main.go", language="go"), ["command -v go", "go run main.go"]),
    ],
)
# contract-test: supporting surface=rest_api assertions=code-run.execution.e2b-only,code-run.surface-parity
def test_run_command_supports_compiled_language_targets(file: CodeRunFile, expected_parts: list[str]) -> None:
    command = _run_command_for_file(file)

    for part in expected_parts:
        assert part in command


# contract-test: supporting surface=rest_api assertions=code-run.execution.stream-status-visible
def test_redact_execution_output_allows_harmless_env_api_key_placeholder() -> None:
    output = "api_key = os.getenv('SERVICE_API_KEY', 'demo-placeholder')\nprint('ok')"

    assert redact_execution_output(output) == output


# contract-test: supporting surface=rest_api assertions=code-run.execution.stream-status-visible
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


# contract-test: supporting surface=rest_api assertions=code-run.execution.e2b-only,code-run.request.validated
@pytest.mark.parametrize("template", [None, "prepared-languages-v1"])
def test_run_code_passes_explicit_e2b_network_controls(monkeypatch: pytest.MonkeyPatch, template: str | None) -> None:
    monkeypatch.setitem(sys.modules, "e2b", SimpleNamespace(Sandbox=FakeE2BSandbox))
    if template:
        monkeypatch.setenv("E2B_CODE_RUN_TEMPLATE", template)
    else:
        monkeypatch.delenv("E2B_CODE_RUN_TEMPLATE", raising=False)

    result = run_code_in_e2b(
        [CodeRunFile(path="main.py", language="python", content="print('ok')", is_target=True)],
        "main.py",
        lambda _kind, _text: None,
        "test-key",
        enable_internet=False,
    )

    assert result.sandbox_id == "sandbox-1"
    assert FakeE2BSandbox.create_kwargs == {
        **({"template": template} if template else {}),
        "api_key": "test-key",
        "secure": True,
        "allow_internet_access": False,
        "network": {"allow_public_traffic": False},
    }


# contract-test: direct surface=rest_api assertions=code-run.artifacts.explicit-only,code-run.execution.e2b-only
def test_run_code_collects_explicit_output_artifacts_before_teardown(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeE2BSandbox.discovery_stdout = json.dumps({
        "artifacts": [
            {
                "path": "outputs/chart.png",
                "normalized_path": "outputs/chart.png",
                "mime_type": "image/png",
                "kind": "image",
                "size_bytes": 4,
                "content_base64": "ZGF0YQ==",
            }
        ],
        "skipped": [{"path": "outputs/.env", "reason": "hidden_or_secret_path"}],
    })
    monkeypatch.setitem(sys.modules, "e2b", SimpleNamespace(Sandbox=FakeE2BSandbox))

    result = run_code_in_e2b(
        [CodeRunFile(path="main.py", language="python", content="print('ok')", is_target=True)],
        "main.py",
        lambda _kind, _text: None,
        "test-key",
    )

    assert result.artifacts == [
        {
            "path": "outputs/chart.png",
            "normalized_path": "outputs/chart.png",
            "mime_type": "image/png",
            "kind": "image",
            "size_bytes": 4,
            "content_base64": "ZGF0YQ==",
        }
    ]
    assert result.skipped_artifacts == [{"path": "outputs/.env", "reason": "hidden_or_secret_path"}]
    assert result.sandbox_id == "sandbox-1"


class DiagnosticSandbox(FakeE2BSandbox):
    """Exercise provider command sequencing and real streaming callbacks offline."""

    instance = None
    install_exit_code = 0
    diagnostic_exit_code = 0
    cancel_runtime = False

    def __init__(self) -> None:
        super().__init__()
        self.commands_seen = []
        self.timeouts_seen = []
        self.runtime_handle = FakeCommandHandle()
        type(self).instance = self

    def _run_command(self, command, **kwargs):
        self.commands_seen.append(command)
        self.timeouts_seen.append(kwargs.get("timeout"))
        if not kwargs.get("background"):
            return super()._run_command(command, **kwargs)
        if "Python runtime:" in command:
            if self.cancel_runtime:
                return self.runtime_handle
            stdout = "Python runtime: 3.11.12 (/usr/local/bin/python)\npip runtime: 25.0 (/usr/local/lib/python3.11/site-packages/pip)\n"
            stderr, code = "", self.diagnostic_exit_code
        elif "python -m pip install" in command:
            stdout = "Requirement already satisfied: requests\n"
            stderr = "ERROR: numpy==2.5.4 requires Python >=3.12\n" if self.install_exit_code else ""
            code = self.install_exit_code
        elif "Installed Python distribution:" in command:
            stdout, stderr, code = "Installed Python distribution: requests==2.32.5\n", "", self.diagnostic_exit_code
        else:
            stdout, stderr, code = "target output\n", "", 0

        def wait(on_stdout, on_stderr):
            if stdout:
                on_stdout(stdout)
            if stderr:
                on_stderr(stderr)
            return SimpleNamespace(exit_code=code)

        return SimpleNamespace(wait=wait)


@pytest.fixture
def diagnostic_sandbox(monkeypatch):
    monkeypatch.setitem(sys.modules, "e2b", SimpleNamespace(Sandbox=DiagnosticSandbox))
    monkeypatch.setattr(DiagnosticSandbox, "install_exit_code", 0)
    monkeypatch.setattr(DiagnosticSandbox, "diagnostic_exit_code", 0)
    monkeypatch.setattr(DiagnosticSandbox, "cancel_runtime", False)
    return DiagnosticSandbox


# contract-test: supporting surface=rest_api assertions=code-run.execution.e2b-only,code-run.execution.stream-status-visible
def test_python_diagnostics_use_trusted_cwd_same_interpreter_and_metadata() -> None:
    runtime = shlex.split(_python_runtime_command())
    versions = shlex.split(_python_versions_command(
        [CodeRunFile(path="main.py", language="python")],
        [CodeRunDependencyInstall(ecosystem="python", packages=("requests[security]>=2", "numpy==2.5.4"))],
    ))
    assert runtime[:5] == versions[:5] == ["cd", "/", "&&", "python", "-c"]
    assert _run_command_for_file(CodeRunFile(path="main.py", language="python")) == "python main.py"
    assert "sys.version" in runtime[5] and "sys.executable" in runtime[5]
    assert "metadata.distribution('pip')" in runtime[5]
    assert "metadata.version(name)" in versions[5]
    assert "requested = ['numpy', 'requests']" in versions[5]
    assert "import requests" not in versions[5]


# contract-test: supporting surface=rest_api assertions=code-run.request.validated,code-run.execution.e2b-only
def test_python_versions_respect_requirements_and_include_requests() -> None:
    files = [
        CodeRunFile(path="requirements.txt", language="", content="-r included.txt\n-c constraints.txt\nrequests>=2\n"),
        CodeRunFile(path="included.txt", language="", content="numpy==2.5.4\n-r requirements.txt\n"),
        CodeRunFile(path="constraints.txt", language="", content="unrequested==1\n"),
    ]
    command = _python_versions_command(files, [CodeRunDependencyInstall(ecosystem="python", packages=("ignored",))])
    assert "requested = ['numpy', 'requests']" in shlex.split(command)[5]
    assert "unrequested" not in command and "ignored" not in command
    assert _dependency_commands(files)[0][1] == "python -m pip install -r requirements.txt"


# contract-test: direct surface=rest_api assertions=code-run.execution.e2b-only,code-run.execution.stream-status-visible
def test_python_runtime_then_install_then_actual_versions_then_target(diagnostic_sandbox) -> None:
    events = []
    result = run_code_in_e2b(
        [CodeRunFile(path="main.py", language="python", content="print('target output')")],
        "main.py", lambda kind, text: events.append((kind, text)), "test-key",
        [CodeRunDependencyInstall(ecosystem="python", packages=("requests",))],
    )
    sandbox = diagnostic_sandbox.instance
    background = [command for command, timeout in zip(sandbox.commands_seen, sandbox.timeouts_seen) if timeout]
    assert len(background) == 4
    assert "Python runtime:" in background[0]
    assert "python -m pip install requests" in background[1]
    assert "metadata.version(name)" in background[2]
    assert "python main.py" in background[3]
    assert [timeout for timeout in sandbox.timeouts_seen if timeout] == [25, 130, 25, 310]
    stdout = "".join(text for kind, text in events if kind == "stdout")
    assert "Python runtime: 3.11.12" in stdout
    assert "pip runtime: 25.0" in stdout
    assert "Requirement already satisfied: requests" in stdout
    assert "Installed Python distribution: requests==2.32.5" in stdout
    assert result.exit_code == 0 and sandbox.killed


# contract-test: direct surface=rest_api assertions=code-run.execution.e2b-only,code-run.execution.stream-status-visible
@pytest.mark.parametrize("manifest", [False, True])
def test_python_install_failure_preserves_pins_stderr_and_skips_target(diagnostic_sandbox, monkeypatch, manifest) -> None:
    monkeypatch.setattr(diagnostic_sandbox, "install_exit_code", 1)
    events = []
    files = [CodeRunFile(path="main.py", language="python")]
    if manifest:
        files.append(CodeRunFile(path="requirements.txt", language="", content="numpy==2.5.4\n"))
    result = run_code_in_e2b(
        files, "main.py", lambda kind, text: events.append((kind, text)), "test-key",
        [CodeRunDependencyInstall(ecosystem="python", packages=("numpy==2.5.4",))],
    )
    sandbox = diagnostic_sandbox.instance
    install_commands = [command for command in sandbox.commands_seen if "python -m pip install" in command]
    assert len(install_commands) == 1
    assert ("-r requirements.txt" if manifest else "numpy==2.5.4") in install_commands[0]
    assert not any("python main.py" in command or "metadata.version(name)" in command for command in sandbox.commands_seen)
    stderr = "".join(text for kind, text in events if kind == "stderr")
    assert "ERROR: numpy==2.5.4 requires Python >=3.12\n" in stderr
    assert "Python dependency installation failed" in stderr
    assert "automatic version resolution" in stderr
    assert "Explicit pins were not changed" in stderr
    assert result.exit_code == 1 and sandbox.killed


# contract-test: direct surface=rest_api assertions=code-run.execution.e2b-only,code-run.execution.stream-status-visible
def test_python_runtime_cancellation_kills_command_and_sandbox(diagnostic_sandbox, monkeypatch) -> None:
    monkeypatch.setattr(diagnostic_sandbox, "cancel_runtime", True)

    def should_cancel():
        sandbox = diagnostic_sandbox.instance
        return sandbox is not None and any("Python runtime:" in command for command in sandbox.commands_seen)

    monkeypatch.setattr(diagnostic_sandbox, "instance", None)
    with pytest.raises(CodeRunCancelled):
        run_code_in_e2b(
            [CodeRunFile(path="main.py", language="python")], "main.py",
            lambda _kind, _text: None, "test-key",
            [CodeRunDependencyInstall(ecosystem="python", packages=("requests",))], should_cancel,
        )
    sandbox = diagnostic_sandbox.instance
    assert sandbox.runtime_handle.killed and sandbox.killed
    assert not any("python -m pip install" in command or "python main.py" in command for command in sandbox.commands_seen)


# contract-test: direct surface=rest_api assertions=code-run.execution.e2b-only,code-run.execution.stream-status-visible
def test_optional_python_diagnostics_failure_does_not_block_target(diagnostic_sandbox, monkeypatch) -> None:
    monkeypatch.setattr(diagnostic_sandbox, "diagnostic_exit_code", 1)
    events = []
    result = run_code_in_e2b(
        [CodeRunFile(path="main.py", language="python")], "main.py",
        lambda kind, text: events.append((kind, text)), "test-key",
        [CodeRunDependencyInstall(ecosystem="python", packages=("requests",))],
    )
    assert result.exit_code == 0
    assert any("python main.py" in command for command in diagnostic_sandbox.instance.commands_seen)
    stderr = "".join(text for kind, text in events if kind == "stderr")
    assert "Python runtime diagnostics unavailable" in stderr
    assert "Installed Python package diagnostics unavailable" in stderr
    assert diagnostic_sandbox.instance.killed
