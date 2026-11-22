"""Cloud Project commands run in the chat's hosted Project sandbox for users on the sandbox path."""
import asyncio
import sys
import types
from types import SimpleNamespace

import pytest

from backend.apps.ai.processing import project_sandbox_gate as gate
from backend.apps.ai.processing import project_test_snapshot as pts
from backend.apps.code import project_sandbox_command as psc
from backend.core.api.app.services import project_sandbox_writeback as writeback
from backend.shared.providers.e2b_code_runner import CodeRunCancelled


class FakeExit(Exception):
    def __init__(self, exit_code):
        super().__init__("exit")
        self.exit_code = exit_code


class FakeHandle:
    def __init__(self, sandbox, exit_code, hang):
        self.sandbox, self.exit_code, self.hang, self.killed = sandbox, exit_code, hang, False

    async def wait(self, on_stdout=None, on_stderr=None):
        on_stdout("hello\n")
        on_stderr("warn\n")
        while self.hang and not self.killed:
            await asyncio.sleep(0.05)
        if self.exit_code:
            raise FakeExit(self.exit_code)
        return SimpleNamespace(exit_code=0)

    async def kill(self):
        self.killed = True


class FakeCommands:
    def __init__(self, sandbox):
        self.sandbox, self.calls, self.handles = sandbox, [], []

    async def run(self, command, background=False, timeout=None, user=None, **_):
        self.calls.append({"command": command, "background": background, "timeout": timeout, "user": user})
        if background and "nohup" not in command:
            handle = FakeHandle(self.sandbox, self.sandbox.exit_code, self.sandbox.hang)
            self.handles.append(handle)
            return handle
        return SimpleNamespace(stdout="200" if "curl" in command else "server log", exit_code=0)


class FakeSandbox:
    def __init__(self, exit_code=0, hang=False):
        self.exit_code, self.hang = exit_code, hang
        self.commands = FakeCommands(self)


class FakeClient:
    def __init__(self, revisions):
        self.revisions, self.calls = revisions, []

    async def call(self, endpoint, body=None, timeout=None):
        self.calls.append(endpoint)
        return {"revisions": self.revisions}


class FakeService:
    def __init__(self, revisions):
        self.client = FakeClient(revisions)
        self.ensure_args, self.touched = None, 0

    async def ensure_ready(self, **kwargs):
        self.ensure_args = kwargs
        return SimpleNamespace(sandbox_id="sbx-1", job_id="job-1", client=self.client)

    async def touch(self, **_):
        self.touched += 1


@pytest.fixture
def env(monkeypatch):
    loop = asyncio.new_event_loop()
    sandbox = FakeSandbox()
    created = []

    async def connect(sandbox_id, secrets_manager=None):
        return sandbox

    monkeypatch.setattr(psc, "connect_project_sandbox", connect)
    monkeypatch.setitem(sys.modules, "e2b", types.SimpleNamespace(CommandExitException=FakeExit))
    committed = []

    async def commit(handle, revisions, **kwargs):
        committed.append((revisions, kwargs))
        return writeback.WritebackResult(committed=[r["path"] for r in revisions])

    monkeypatch.setattr(writeback, "commit_revisions", commit)
    monkeypatch.setattr(
        "backend.shared.providers.e2b_project_workspace.run_workspace_command",
        lambda *a, **k: created.append(1))
    yield SimpleNamespace(loop=loop, sandbox=sandbox, committed=committed, workspace_created=created)
    loop.close()


def payload(**command):
    base = {"argv": ["npm", "test"], "cwd": ".", "timeout_seconds": 120, "background": False,
            "ready_url": None, "project_id": "p1", "team_id": None, "project_sandbox": True}
    return {"user_id": "u1", "chat_id": "c1", "files": [], "command_run": {**base, **command}}


def run(env, service, data, cancel=lambda: False):
    out = []
    result = psc.execute_sandbox_command(
        data, lambda kind, text: out.append((kind, text)), cancel, object(), env.loop.run_until_complete,
        None, service=service, directus_service=object())
    return result, out


# contract-test: direct surface=rest_api assertions=code-run.cloud.commands,code-run.cloud.workspace,code-run.cloud.command-changes-sync-back
def test_sandbox_command_runs_in_project_dir_and_commits_scanned_revisions(env):
    service = FakeService([{"path": "src/a.ts", "embed_id": "e1", "transaction": {}}])
    (result, outcome), out = run(env, service, payload(cwd="web"))
    line = env.sandbox.commands.calls[0]["command"]
    assert "/home/user/project/web" in line and "npm test" in line and line.startswith("timeout 120s bash -lc")
    assert service.ensure_args["project_id"] == "p1" and service.client.calls == ["/v1/scan"]
    assert env.committed[0][0][0]["path"] == "src/a.ts"
    assert outcome.write_back["committed"] == ["src/a.ts"] and outcome.changes == []
    assert result.exit_code == 0 and ("stdout", "hello\n") in out and service.touched == 1
    assert env.workspace_created == []  # the separate workspace is never created
    assert all(call["user"] == "user" for call in env.sandbox.commands.calls)  # never root


# contract-test: direct surface=rest_api assertions=projects.keys.sandbox-sealed-handover
def test_background_command_probe_and_log_run_as_user(env):
    service = FakeService([])
    run(env, service, payload(background=True, ready_url="http://localhost:3000"))
    assert len(env.sandbox.commands.calls) >= 3
    assert all(call["user"] == "user" for call in env.sandbox.commands.calls)


# contract-test: direct surface=rest_api assertions=code-run.cloud.commands
def test_sandbox_command_failure_exit_code_and_folder_escape(env):
    env.sandbox.exit_code = 3
    (result, _), _ = run(env, FakeService([]), payload())
    assert result.exit_code == 3
    with pytest.raises(psc.ProjectSandboxCommandError):
        run(env, FakeService([]), payload(cwd="../outside"))


# contract-test: direct surface=rest_api assertions=code-run.cloud.commands
def test_sandbox_command_deadline_wrapper_and_cancel(env):
    env.sandbox.hang = True
    with pytest.raises(CodeRunCancelled):
        run(env, FakeService([]), payload(timeout_seconds=45), cancel=lambda: True)
    call = env.sandbox.commands.calls[0]
    assert call["command"].startswith("timeout 45s ") and call["timeout"] == 55
    assert env.sandbox.commands.handles[0].killed


# contract-test: direct surface=rest_api assertions=code-run.cloud.commands
def test_sandbox_background_dev_server_ready(env):
    (result, outcome), out = run(env, FakeService([]), payload(
        background=True, ready_url="http://localhost:5173", timeout_seconds=30))
    assert outcome.ready is True and result.exit_code == 0
    assert any("nohup" in c["command"] for c in env.sandbox.commands.calls)
    assert ("status", "Dev server is ready.\n") in out


# contract-test: direct surface=rest_api assertions=code-run.cloud.commands
def test_model_sees_write_back_and_truncated_output():
    pytest.importorskip("toon_format")  # the code tasks package needs the full worker image
    from backend.apps.code.tasks import cloud_command_execution as cce

    outcome = psc.SandboxCommandOutcome(
        exit_code=0, duration_seconds=1.0, sandbox_id="s", reused=True, state=None,
        write_back={"committed": ["a.ts"], "merged": [], "conflicts": [], "rejected": []})
    fields = cce.command_status_fields(outcome)
    assert fields["write_back"]["committed"] == ["a.ts"] and fields["changed_files"] == []
    completion = cce.command_completion(
        {"output": "x" * 200_000}, {"status": "finished", **fields}, {"argv": ["npm", "test"], "cwd": "."})
    assert completion["output_truncated"] and len(completion["output"]) < 70_000
    assert completion["write_back"]["committed"] == ["a.ts"]


# contract-test: direct surface=rest_api assertions=code-run.cloud.commands
def test_pipeline_skips_the_client_snapshot_only_for_sandbox_users():
    plain = {"argv": ["npm", "test"], "files": [{"path": "forged", "code": "x"}], "project_sandbox": True}
    cleaned = pts.without_forged_snapshot(plain)
    assert "files" not in cleaned and "project_sandbox" not in cleaned
    assert pts.needs_snapshot(cleaned) is True  # workspace path: the client sends the snapshot
    sandboxed = pts.use_project_sandbox(cleaned)
    assert pts.needs_snapshot(sandboxed) is False and sandboxed["project_sandbox"] is True


@pytest.mark.parametrize("decision,focus,expected", [
    ("allowed", {"project_id": "p1"}, True),
    ("declined", {"project_id": "p1"}, False),
    (None, {"project_id": "p1"}, False),
    ("allowed", {"project_id": "p1", "source_id": "m1"}, False),
    ("allowed", None, False),
])
# contract-test: direct surface=rest_api assertions=code-run.cloud.commands
def test_sandbox_gate(monkeypatch, decision, focus, expected):
    async def get_decision(user_id, directus_service=None):
        return {"decision": decision}

    monkeypatch.setattr(gate.e2b_upload_consent, "get_decision", get_decision)
    result = asyncio.run(gate.sandbox_applies_to_command(user_id="u1", focus=focus, directus_service=None))
    assert result is expected
