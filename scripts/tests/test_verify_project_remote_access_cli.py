"""Orchestration tests for the two-CLI Project verifier.

The tests execute Personal and Team fixture branches with process/network calls
replaced by deterministic fakes. They also pin truthful reporting for denial
probes that require a separately approved second test account.
"""

from __future__ import annotations

import json
import pytest
import signal
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import verify_project_remote_access_cli as verifier  # noqa: E402


class FakeProcess:
    def __init__(self, fixture: dict[str, object]) -> None:
        self.stdout = iter([
            json.dumps({"event": "fixture_ready", **fixture}) + "\n",
            json.dumps({"event": "bridge_stopped"}) + "\n",
        ])
        self.stderr = iter([])
        self.signals: list[int] = []
        self.killed = False

    def poll(self) -> None:
        return None

    def send_signal(self, value: int) -> None:
        self.signals.append(value)

    def wait(self, timeout: int) -> int:
        assert timeout == 30
        return 0

    def kill(self) -> None:
        self.killed = True


class TimedOutProcess(FakeProcess):
    def __init__(self) -> None:
        super().__init__({"project_id": "project-1", "source_id": "source-1", "team_id": None})
        self.wait_calls = 0

    def wait(self, timeout: int) -> int:
        self.wait_calls += 1
        if self.wait_calls == 1:
            raise verifier.subprocess.TimeoutExpired("fixture", timeout)
        return 0


def test_personal_and_team_modes_execute_expected_requester_operations(monkeypatch) -> None:
    spawned: list[tuple[list[str], FakeProcess]] = []
    operations: list[list[str]] = []

    def fake_popen(command: list[str], **kwargs) -> FakeProcess:
        del kwargs
        team = "serve-team" in command
        process = FakeProcess({
            "project_id": "project-1",
            "source_id": "source-1",
            "team_id": "team-1" if team else None,
        })
        spawned.append((command, process))
        return process

    def fake_run_cli(
        home: Path,
        api_url: str,
        arguments: list[str],
        *,
        expected_error: str | None = None,
    ) -> dict[str, object]:
        del home, api_url
        operations.append(arguments)
        action = arguments[2]
        path = arguments[4] if action == "read" else None
        if expected_error:
            assert expected_error == ("protected_path" if path == ".env" else "source_offline")
            return {"error": {"code": expected_error}}
        if action == "list":
            return {"operation": "list", "result": {"entries": [{"path": "src", "type": "directory"}]}}
        if action == "search":
            return {"operation": "search", "result": {"matches": [{"path": "src/remote-demo.ts"}]}}
        return {"operation": "read", "result": {"content": 'export const remoteDemo = "OpenMates live remote preview";\n'}}

    monkeypatch.setattr(verifier.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(verifier, "_run_cli", fake_run_cli)

    personal = verifier._verify_context(
        "https://api.dev.openmates.org", Path("/host"), Path("/requester"), False
    )
    team = verifier._verify_context(
        "https://api.dev.openmates.org", Path("/host"), Path("/requester"), True
    )

    assert personal["status"] == team["status"] == "passed"
    assert personal["checks"] == team["checks"] == {
        "list_entry": 1,
        "search_match": 1,
        "read_content": 1,
        "protected_denial": 1,
        "offline_after_stop": 1,
    }
    encoded = json.dumps([personal, team], sort_keys=True)
    assert "OpenMates live remote preview" not in encoded
    assert "src/remote-demo.ts" not in encoded

    assert ["serve" in command for command, _ in spawned] == [True, False]
    assert ["serve-team" in command for command, _ in spawned] == [False, True]
    assert all(process.signals == [signal.SIGUSR1, signal.SIGINT] for _, process in spawned)
    assert [arguments[2] for arguments in operations] == [
        "list", "search", "read", "read", "list",
        "list", "search", "read", "read", "list",
    ]
    assert "--personal" in operations[0]
    assert operations[5][-2:] == ["--team", "team-1"]


def test_context_rejects_operation_only_projection(monkeypatch) -> None:
    process = FakeProcess({"project_id": "project-1", "source_id": "source-1", "team_id": None})
    monkeypatch.setattr(verifier.subprocess, "Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr(
        verifier,
        "_run_cli",
        lambda *args, **kwargs: {"operation": args[2][2]},
    )

    with pytest.raises(RuntimeError, match="result"):
        verifier._verify_context(
            "https://api.dev.openmates.org", Path("/host"), Path("/requester"), False
        )


def test_single_account_denial_probes_are_explicitly_not_run_with_named_coverage() -> None:
    probes = verifier.unavailable_account_probes()

    assert [probe["probe"] for probe in probes] == ["cross_account_denial", "removed_member_denial"]
    assert {probe["status"] for probe in probes} == {"not_run"}
    assert all("backend/tests/test_project_remote_access_bridge.py::test_" in probe["backend_denial_coverage"] for probe in probes)


@pytest.mark.parametrize(
    ("waiter", "expected_event"),
    [
        (verifier._wait_fixture, "fixture_ready"),
        (lambda process: verifier._wait_event(process, "bridge_stopped"), "bridge_stopped"),
    ],
)
def test_source_event_reads_have_bounded_deadlines(monkeypatch, waiter, expected_event: str) -> None:
    process = FakeProcess({"project_id": "project-1", "source_id": "source-1", "team_id": None})
    monkeypatch.setattr(verifier, "_readline_before", lambda *args, **kwargs: None)

    with pytest.raises(RuntimeError, match=rf"Timed out waiting for source CLI event '{expected_event}'"):
        waiter(process)


def test_context_kills_child_when_graceful_cleanup_times_out(monkeypatch) -> None:
    process = TimedOutProcess()
    monkeypatch.setattr(verifier.subprocess, "Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr(
        verifier,
        "_wait_fixture",
        lambda child: (_ for _ in ()).throw(RuntimeError("fixture timeout")),
    )

    with pytest.raises(RuntimeError, match="fixture timeout"):
        verifier._verify_context(
            "https://api.dev.openmates.org", Path("/host"), Path("/requester"), False
        )

    assert process.signals == [signal.SIGINT]
    assert process.killed is True
    assert process.wait_calls == 2


def test_requester_failure_reports_only_stable_parsed_error_code(monkeypatch) -> None:
    secret = "private remote plaintext"
    monkeypatch.setattr(
        verifier.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0],
            1,
            stdout="",
            stderr=json.dumps({"error": {"code": "protocol_timeout", "message": secret}, "debug": secret}),
        ),
    )

    with pytest.raises(RuntimeError) as raised:
        verifier._run_cli(Path("/requester"), "https://api.dev.openmates.org", ["projects", "files", "list"])

    assert "protocol_timeout" in str(raised.value)
    assert secret not in str(raised.value)


def test_requester_failure_never_includes_unparsed_stderr(monkeypatch) -> None:
    secret = "private remote plaintext"
    monkeypatch.setattr(
        verifier.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 1, stdout="", stderr=secret),
    )

    with pytest.raises(RuntimeError) as raised:
        verifier._run_cli(Path("/requester"), "https://api.dev.openmates.org", ["projects", "files", "list"])

    assert secret not in str(raised.value)
    assert "unknown_error" in str(raised.value)


def test_stable_error_code_reads_final_json_after_diagnostics() -> None:
    stderr = 'Node warning: harmless diagnostic\n{"error":{"code":"source_offline"}}\n'

    assert verifier._stable_error_code(stderr) == "source_offline"


@pytest.mark.parametrize(
    "stderr",
    [
        'diagnostic\n{"error":',
        '{"error":{"code":"Not-Allowlisted"}}',
        '{"error":{"code":"source_offline"}} trailing text',
    ],
)
def test_stable_error_code_rejects_malformed_or_non_allowlisted_lines(stderr: str) -> None:
    assert verifier._stable_error_code(stderr) == "unknown_error"


def test_stable_error_code_accepts_pure_json() -> None:
    assert verifier._stable_error_code('{"error":{"code":"protocol_timeout"}}') == "protocol_timeout"
