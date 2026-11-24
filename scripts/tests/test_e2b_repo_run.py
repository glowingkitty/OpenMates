#!/usr/bin/env python3
# contract-test-file: tooling
"""Contracts for the standalone E2B repository runner (scripts/e2b_repo_run.py).

Scope: CLI parsing and the upload/run/exit-status flow against a fake E2B SDK and
fake capacity slot; a throwaway local git repository; no E2B key or network.
Run: python3 -m pytest scripts/tests/test_e2b_repo_run.py
"""

from __future__ import annotations

import subprocess
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import e2b_repo_run as runner  # noqa: E402 - scripts/ is added to sys.path above


class CommandExit(Exception):
    def __init__(self, exit_code: int) -> None:
        super().__init__(exit_code)
        self.exit_code = exit_code


class FakeSandbox:
    created: list["FakeSandbox"] = []
    exit_code = 0

    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs
        self.sandbox_id = "sbx-test"
        self.writes: dict[str, bytes] = {}
        self.runs: list[tuple[str, dict]] = []
        self.killed = False
        self.files = types.SimpleNamespace(write=self.writes.__setitem__)
        self.commands = types.SimpleNamespace(run=self._run)

    @classmethod
    def create(cls, **kwargs) -> "FakeSandbox":
        sandbox = cls(**kwargs)
        cls.created.append(sandbox)
        return sandbox

    def _run(self, command: str, **kwargs):
        self.runs.append((command, kwargs))
        if self.exit_code:
            raise CommandExit(self.exit_code)
        return types.SimpleNamespace(exit_code=0)

    def kill(self) -> None:
        self.killed = True


class FakeSlot:
    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        return None


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "example-repo"
    path.mkdir()
    git = ["git", "-C", str(path), "-c", "user.name=Test", "-c", "user.email=test@example.org"]
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    (path / "README.md").write_text("example\n")
    subprocess.run(git + ["add", "README.md"], check=True)
    subprocess.run(git + ["commit", "-q", "-m", "init"], check=True)
    return path


@pytest.fixture
def fake_e2b(monkeypatch) -> dict:
    FakeSandbox.created = []
    FakeSandbox.exit_code = 0
    module = types.ModuleType("e2b")
    module.Sandbox = FakeSandbox
    module.CommandExitException = CommandExit
    module.SandboxException = RuntimeError
    module.TimeoutException = TimeoutError
    monkeypatch.setitem(sys.modules, "e2b", module)
    seen: dict = {"labels": [], "checked": [], "spend": 0}
    monkeypatch.setattr(runner.e2b_dev_capacity, "acquire",
                        lambda label, timeout, announce=None: seen["labels"].append(label) or FakeSlot())
    monkeypatch.setattr(runner.e2b_dev_capacity, "budget_exhausted", lambda: None)
    monkeypatch.setattr(runner.e2b_dev_capacity, "record_spend",
                        lambda *args: seen.__setitem__("spend", seen["spend"] + 1))
    monkeypatch.setattr(runner.heavy_remote, "e2b_api_key", lambda: "test-key")
    monkeypatch.setattr(runner.heavy_remote, "sandbox_env", lambda kind: {})
    monkeypatch.setattr(runner.heavy_remote, "checked",
                        lambda sandbox, command, timeout, what: seen["checked"].append(command) or "")
    return seen


def test_repo_is_required() -> None:
    with pytest.raises(SystemExit):
        runner.parse_args(["--sandbox-root", "/work/src", "--", "true"])


def test_sandbox_root_is_required() -> None:
    with pytest.raises(SystemExit):
        runner.parse_args(["--repo", ".", "--", "true"])


def test_cli_flags_and_defaults(tmp_path: Path) -> None:
    args = runner.parse_args(["--repo", str(tmp_path), "--sandbox-root", "/work/src",
                              "--revision", "abc", "--timeout", "60", "--", "bash", "-c", "make test"])
    assert (args.repo, args.revision, args.timeout) == (tmp_path, "abc", 60)
    assert args.sandbox_root == "/work/src"
    assert args.command == ["bash", "-c", "make test"]


@pytest.mark.parametrize("argv", [["--repo", ".", "--sandbox-root", "/work/src"],
                                  ["--repo", ".", "--sandbox-root", "/work/src", "--timeout", "0", "--", "true"],
                                  ["--repo", ".", "--sandbox-root", "relative", "--", "true"]])
def test_invalid_arguments_are_refused(argv: list[str]) -> None:
    with pytest.raises(SystemExit):
        runner.parse_args(argv)


def test_clean_run_uploads_commit_and_returns_zero(repo: Path, fake_e2b: dict) -> None:
    commit = runner.resolve_commit(repo, "HEAD")
    assert runner.main(["--repo", str(repo), "--sandbox-root", "/home/user/repo", "--", "bash", "-c", "make test"]) == 0
    sandbox = FakeSandbox.created[0]
    assert fake_e2b["labels"] == ["repo-tests: " + commit[:12]]
    assert sandbox.kwargs["metadata"] == {"purpose": "repo-tests"}
    assert list(sandbox.writes) == [runner.ARCHIVE_PATH]
    assert fake_e2b["checked"] == [f"mkdir -p /home/user/repo && tar -xzf {runner.ARCHIVE_PATH} -C /home/user/repo"]
    command, kwargs = sandbox.runs[0]
    assert command == "bash -c 'make test'" and kwargs["cwd"] == "/home/user/repo"
    assert sandbox.killed and fake_e2b["spend"] == 1


def test_failing_command_status_is_returned(repo: Path, fake_e2b: dict) -> None:
    FakeSandbox.exit_code = 3
    assert runner.main(["--repo", str(repo), "--sandbox-root", "/work/src", "--", "false"]) == 3
    sandbox = FakeSandbox.created[0]
    assert sandbox.runs[0][1]["cwd"] == "/work/src"
    assert sandbox.killed and fake_e2b["spend"] == 1


def test_unknown_revision_fails_before_any_sandbox(repo: Path, fake_e2b: dict) -> None:
    with pytest.raises(subprocess.CalledProcessError):
        runner.main(["--repo", str(repo), "--sandbox-root", "/work/src", "--revision", "does-not-exist", "--", "true"])
    assert FakeSandbox.created == [] and fake_e2b["labels"] == []
