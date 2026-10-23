# contract-test-file: tooling
"""Guard installer admission and expression handling without starting a stack.

The original installer steps remain owned by the source workflow. The adapter
must reject unsupported Actions inputs and any non-GitHub execution before
reading installation state. Queue accounting is shared with ordinary E2E.
See docs/architecture/isolated-github-tests.md.
"""

import json
import os
import shutil
import subprocess
import sys
from types import SimpleNamespace
from pathlib import Path

import pytest
from scripts import ci_environment


def module(monkeypatch):
    monkeypatch.setitem(sys.modules, "ci_environment", ci_environment)
    from scripts import ci_selfhost
    return ci_selfhost


def test_only_explicit_nonsecret_workflow_expressions_expand(monkeypatch):
    runner = module(monkeypatch)
    assert runner.expand('${{ github.workspace }}/${{ env.TAG }}', {'TAG': 'local'}, Path('/runner/subject'), 'a' * 40) == '/runner/subject/local'
    assert runner.expand('${{ github.sha }}', {}, Path('/runner'), 'a' * 40) == 'a' * 40
    with pytest.raises(ValueError, match='Unsupported'):
        runner.expand('${{ secrets.PROVIDER_KEY }}', {}, Path('/runner'), 'a' * 40)


def test_installer_refuses_local_execution_before_any_state_read(monkeypatch):
    runner = module(monkeypatch)
    monkeypatch.delenv('GITHUB_ACTIONS', raising=False)
    with pytest.raises(RuntimeError, match='GitHub-hosted'):
        runner.run(Path('/nonexistent'), [])


def test_installer_has_separate_queue_mode_and_exact_spec(tmp_path):
    from scripts.ci_coordinator import Queue
    from scripts.ci_coverage import execution_mode, partition
    queue = Queue(tmp_path / 'queue.sqlite3')
    spec = 'selfhost-smoke.spec.ts'
    assert partition([spec]) == ([spec], {})
    assert execution_mode(spec) == 'selfhost'
    queue.enqueue('fixture', 'a' * 40, [spec], 'selfhost')
    with pytest.raises(ValueError, match='exactly'):
        queue.enqueue('fixture', 'a' * 40, ['other.spec.ts'], 'selfhost')


def native_env(runner, source):
    return {
        "SOURCE_INSTALL_PATH": runner.INSTALL_PATHS[0],
        "IMAGE_INSTALL_PATH": runner.INSTALL_PATHS[1],
        "NATIVE_SOURCE_INSTALL_PATH": runner.NATIVE_SOURCE_INSTALL_PATH,
        "NATIVE_STATE_DIR": runner.NATIVE_STATE_DIR,
        "NATIVE_CLI_PATH": str(source / "frontend/packages/openmates-tui-native/target/release/openmates"),
    }


def test_cleanup_admission_keeps_legacy_workflows_and_rejects_native_path_drift(monkeypatch, tmp_path):
    runner = module(monkeypatch)
    env = native_env(runner, tmp_path)
    legacy = {key: env[key] for key in ("SOURCE_INSTALL_PATH", "IMAGE_INSTALL_PATH")}
    assert runner.admit_cleanup(tmp_path, legacy, env) is False
    assert runner.admit_cleanup(tmp_path, env, env) is True
    for key in env:
        changed = {**env, key: "/unapproved"}
        with pytest.raises(RuntimeError, match="paths changed"):
            runner.admit_cleanup(tmp_path, changed, changed)
    for key in runner.NATIVE_ENV:
        partial = {name: value for name, value in env.items() if name != key}
        with pytest.raises(RuntimeError, match="Native installer paths"):
            runner.admit_cleanup(tmp_path, partial, env)


def test_native_cleanup_uses_exact_executable_and_never_falls_back(monkeypatch, tmp_path):
    runner = module(monkeypatch)
    env = native_env(runner, tmp_path)
    installs = (runner.INSTALL_PATHS[1], runner.NATIVE_SOURCE_INSTALL_PATH)
    for install in runner.INSTALL_PATHS:
        assert runner.cleanup_command(tmp_path, env, install)[0] == "node"
    for install in installs:
        with pytest.raises(RuntimeError, match="compiled Rust"):
            runner.cleanup_command(tmp_path, env, install, native=True)
    binary = Path(env["NATIVE_CLI_PATH"])
    binary.parent.mkdir(parents=True)
    binary.write_text("inert synthetic executable")
    binary.chmod(0o600)
    with pytest.raises(RuntimeError, match="compiled Rust"):
        runner.cleanup_command(tmp_path, env, installs[0], native=True)
    binary.chmod(0o700)
    for install in installs:
        command = runner.cleanup_command(tmp_path, env, install, native=True)
        assert command == [str(binary), "--state-dir", runner.NATIVE_STATE_DIR, "server", "uninstall", "--path", install, "--yes"]
    binary.unlink()
    target = tmp_path / "other-executable"
    target.write_text("unselected synthetic executable")
    target.chmod(0o700)
    binary.symlink_to(target)
    with pytest.raises(RuntimeError, match="compiled Rust"):
        runner.cleanup_command(tmp_path, env, installs[0], native=True)
    with pytest.raises(RuntimeError, match="not admitted"):
        runner.cleanup_command(tmp_path, env, "/unapproved", native=True)


def test_native_profile_cleanup_preserves_symlink_targets_and_refuses_root_links(monkeypatch, tmp_path):
    runner = module(monkeypatch)
    profile = tmp_path / "profile"
    monkeypatch.setattr(runner, "NATIVE_STATE_DIR", str(profile))
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "preserve"
    sentinel.write_text("synthetic outside state")
    profile.mkdir()
    (profile / "child-link").symlink_to(outside, target_is_directory=True)
    runner.remove_native_profile(str(profile))
    assert not profile.exists() and sentinel.exists()
    runner.remove_native_profile(str(profile))  # absent state is already clean
    profile.symlink_to(outside, target_is_directory=True)
    with pytest.raises(RuntimeError, match="refused"):
        runner.remove_native_profile(str(profile))
    assert profile.is_symlink() and sentinel.exists()
    with pytest.raises(RuntimeError, match="not admitted"):
        runner.remove_native_profile(str(outside))
    parent_link = tmp_path / "parent-link"
    parent_link.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(OSError):
        runner._remove_private_directory(parent_link / "outside")
    assert sentinel.exists()


def test_private_cleanup_refuses_foreign_owner_or_file(monkeypatch, tmp_path):
    runner = module(monkeypatch)
    directory = tmp_path / "foreign"
    directory.mkdir()
    original = os.stat

    def foreign(path, *args, **kwargs):
        info = original(path, *args, **kwargs)
        if path == directory.name and kwargs.get("follow_symlinks") is False:
            return SimpleNamespace(st_mode=info.st_mode, st_uid=os.geteuid() + 1)
        return info

    with monkeypatch.context() as scope:
        scope.setattr(runner.os, "stat", foreign)
        with pytest.raises(RuntimeError, match="foreign owner"):
            runner._remove_private_directory(directory)
    file = tmp_path / "file"
    file.write_text("preserve")
    with pytest.raises(RuntimeError, match="non-directory"):
        runner._remove_private_directory(file)
    assert directory.exists() and file.read_text() == "preserve"


@pytest.fixture
def inert_run(monkeypatch, tmp_path):
    """All commands are recorded mocks; only this test's tmp_path is removed."""
    import yaml

    runner = module(monkeypatch)
    source = tmp_path / "subject"
    source.mkdir()
    installs = (str(tmp_path / "legacy-source"), str(tmp_path / "image"))
    monkeypatch.setattr(runner, "INSTALL_PATHS", installs)
    monkeypatch.setattr(runner, "NATIVE_SOURCE_INSTALL_PATH", str(tmp_path / "native-source"))
    monkeypatch.setattr(runner, "NATIVE_STATE_DIR", str(tmp_path / "native-profile"))
    env = native_env(runner, source)
    binary = Path(env["NATIVE_CLI_PATH"])
    binary.parent.mkdir(parents=True)
    binary.write_text("inert synthetic executable; never executed")
    binary.chmod(0o700)
    profile = Path(runner.NATIVE_STATE_DIR)
    profile.mkdir()
    (profile / "synthetic-private-key").write_text("synthetic")
    for install in (*installs, runner.NATIVE_SOURCE_INSTALL_PATH):
        path = Path(install)
        path.mkdir()
        (path / ".env").write_text("synthetic private installer state")
    output = source / "test-results"
    output.mkdir()
    (output / "selfhost-smoke-playwright.json").write_text(json.dumps({"stats": {"expected": 1}}))
    workflow = source / ".github/workflows/selfhost-smoke.yml"
    workflow.parent.mkdir(parents=True)
    calls = []
    options = {"native": True, "step_error": None, "cleanup_error": None, "resource_error": None}

    def command(args, **kwargs):
        calls.append(list(args))
        if args[0] == "bash":
            assert kwargs["timeout"] == 3000
            if args[-1] == "work" and options["step_error"]:
                if options["step_error"] == "timeout":
                    raise subprocess.TimeoutExpired(args, 3000)
                raise OSError("synthetic step failure")
            return SimpleNamespace(returncode=0)
        assert "--path" in args
        assert kwargs["timeout"] == 180
        install = Path(args[args.index("--path") + 1])
        assert install.is_relative_to(tmp_path)
        if str(install) == installs[1] and options["cleanup_error"]:
            fault = options["cleanup_error"]
            if fault == "timeout":
                raise subprocess.TimeoutExpired(args, 180)
            if fault == "oserror":
                raise OSError("synthetic cleanup failure")
            return SimpleNamespace(returncode=1 if fault == "nonzero" else 0)
        shutil.rmtree(install)
        return SimpleNamespace(returncode=0)

    def read(args, **kwargs):
        if args[0] == "git":
            return "a" * 40
        calls.append(list(args))
        assert args[0] == "docker"
        if options["resource_error"] == args[1]:
            raise subprocess.TimeoutExpired(args, 30)
        return ""

    monkeypatch.setattr(runner, "require_runner", lambda: None)
    monkeypatch.setattr(runner, "check_egress", lambda: None)
    monkeypatch.setattr(runner, "run_owned_command", command)
    monkeypatch.setattr(runner.subprocess, "check_output", read)
    monkeypatch.setenv("GITHUB_RUN_ID", "inert-selfhost")

    def execute():
        declared = env if options["native"] else {key: env[key] for key in ("SOURCE_INSTALL_PATH", "IMAGE_INSTALL_PATH")}
        workflow.write_text(yaml.safe_dump({"jobs": {"install-smoke": {"runs-on": "ubuntu-latest", "env": declared, "steps": [
            {"name": "work", "run": "work"},
            {"name": "ordinary", "run": "ordinary"},
            {"name": "always", "if": "always()", "run": "always"},
        ]}}}))
        results = []
        runner.run(source, results)
        return results

    return SimpleNamespace(runner=runner, source=source, env=env, binary=binary, profile=profile,
                           calls=calls, options=options, execute=execute, output=output, installs=installs)


def receipt(fixture):
    return json.loads((fixture.output / "ci-cleanup.json").read_text())


def test_legacy_workflow_cleanup_stays_node_and_does_not_own_native_profile(inert_run, monkeypatch):
    f = inert_run
    f.options["native"] = False
    for key in f.runner.NATIVE_ENV:
        monkeypatch.setenv(key, "unselected-inherited-value")
    results = f.execute()
    commands = [call for call in f.calls if "--path" in call]
    assert len(commands) == 2 and all(call[0] == "node" for call in commands)
    assert f.profile.exists() and Path(f.runner.NATIVE_SOURCE_INSTALL_PATH).exists()
    assert results[0]["exit_code"] == 0
    assert receipt(f)["private_account_files_removed"] is True


def test_native_workflow_cleanup_success_records_complete_proof(inert_run):
    f = inert_run
    results = f.execute()
    commands = [call for call in f.calls if "--path" in call]
    assert [call[0] for call in commands] == ["node", str(f.binary), str(f.binary)]
    assert not any(Path(install).exists() for install in (*f.installs, f.runner.NATIVE_SOURCE_INSTALL_PATH))
    assert not f.profile.exists() and not (f.output / "ci-private").exists()
    assert receipt(f)["private_account_files_removed"] is True
    assert receipt(f)["errors"] == []
    assert results[0]["exit_code"] == 0


@pytest.mark.parametrize("failure", ["timeout", "oserror"])
def test_raised_workflow_step_still_runs_always_and_all_owned_cleanup(inert_run, failure):
    f = inert_run
    f.options["step_error"] = failure
    results = f.execute()
    commands = [call for call in f.calls if "--path" in call]
    assert [call[0] for call in commands] == ["node", str(f.binary), str(f.binary)]
    assert any(call[-1] == "always" for call in f.calls)
    assert not any(call[-1] == "ordinary" for call in f.calls)
    assert not f.profile.exists() and not (f.output / "ci-private").exists()
    assert receipt(f)["private_account_files_removed"] is True
    assert results[0]["exit_code"] == 1
    steps = json.loads((f.output / "ci-selfhost-steps.json").read_text())
    assert steps[0]["error"] == ("timeout" if failure == "timeout" else "process_start_failed")


@pytest.mark.parametrize("failure", ["timeout", "oserror", "nonzero", "leftover"])
def test_native_cleanup_failure_never_uses_node_and_does_not_skip_other_cleanup(inert_run, failure):
    f = inert_run
    f.options["cleanup_error"] = failure
    with pytest.raises(RuntimeError, match="cleanup incomplete"):
        f.execute()
    commands = [call for call in f.calls if "--path" in call]
    assert [call[0] for call in commands] == ["node", str(f.binary), str(f.binary)]
    assert not Path(f.runner.NATIVE_SOURCE_INSTALL_PATH).exists()
    assert not f.profile.exists() and not (f.output / "ci-private").exists()
    assert receipt(f)["private_account_files_removed"] is False
    assert receipt(f)["errors"] == [f.installs[1]]


def test_missing_native_executable_records_both_failures_without_node_fallback(inert_run):
    f = inert_run
    f.binary.unlink()
    with pytest.raises(RuntimeError, match="cleanup incomplete"):
        f.execute()
    commands = [call for call in f.calls if "--path" in call]
    assert len(commands) == 1 and commands[0][0] == "node"
    assert receipt(f)["errors"] == [f.installs[1], f.runner.NATIVE_SOURCE_INSTALL_PATH]
    assert receipt(f)["private_account_files_removed"] is False
    assert not f.profile.exists() and not (f.output / "ci-private").exists()


def test_install_root_symlink_is_refused_without_visiting_its_target(inert_run):
    f = inert_run
    outside = f.source.parent / "outside"
    outside.mkdir()
    (outside / "preserve").write_text("synthetic")
    image = Path(f.installs[1])
    shutil.rmtree(image)
    image.symlink_to(outside, target_is_directory=True)
    with pytest.raises(RuntimeError, match="cleanup incomplete"):
        f.execute()
    assert image.is_symlink() and (outside / "preserve").exists()
    assert not Path(f.runner.NATIVE_SOURCE_INSTALL_PATH).exists()
    assert receipt(f)["private_account_files_removed"] is False


def test_unavailable_cleanup_log_does_not_skip_remaining_owned_cleanup(inert_run, monkeypatch):
    f = inert_run
    attempts = []
    original = Path.open

    def refuse(path, *args, **kwargs):
        if path == f.output / "ci-private/cleanup.log":
            attempts.append(path)
            raise PermissionError("synthetic log refusal")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", refuse)
    with pytest.raises(RuntimeError, match="cleanup incomplete"):
        f.execute()
    assert len(attempts) == 3
    assert receipt(f)["errors"] == [*f.installs, f.runner.NATIVE_SOURCE_INSTALL_PATH]
    assert receipt(f)["private_account_files_removed"] is False
    assert not f.profile.exists() and not (f.output / "ci-private").exists()


@pytest.mark.parametrize("failure", ["native-profile", "ci-private", "containers", "volumes"])
def test_cleanup_receipt_refuses_unverified_private_or_resource_cleanup(inert_run, monkeypatch, failure):
    f = inert_run
    outside = f.source.parent / "outside"
    outside.mkdir()
    (outside / "preserve").write_text("synthetic")
    if failure == "native-profile":
        shutil.rmtree(f.profile)
        f.profile.symlink_to(outside, target_is_directory=True)
    elif failure == "ci-private":
        original = f.runner._remove_private_directory

        def refuse(path):
            if path.name == "ci-private":
                raise OSError("synthetic private deletion failure")
            return original(path)

        monkeypatch.setattr(f.runner, "_remove_private_directory", refuse)
    else:
        f.options["resource_error"] = "ps" if failure == "containers" else "volume"
    with pytest.raises(RuntimeError, match="cleanup incomplete"):
        f.execute()
    data = receipt(f)
    assert failure in data["errors"]
    if failure in ("native-profile", "ci-private"):
        assert data["private_account_files_removed"] is False
    else:
        assert data[failure + "_remaining"] == "unknown"
        assert data["private_account_files_removed"] is True
    assert (outside / "preserve").exists()


@pytest.mark.parametrize("mode", ["success", "nonzero", "timeout"])
@pytest.mark.parametrize("new_group", [False, True])
def test_owned_runner_reaps_inert_writer_after_leader_exit_or_timeout(monkeypatch, tmp_path, mode, new_group):
    runner = module(monkeypatch)
    libc = runner.ctypes.CDLL(None)
    before = runner.ctypes.c_int()
    assert libc.prctl(37, runner.ctypes.byref(before), 0, 0, 0) == 0
    monkeypatch.setattr(runner, "OWNED_TERM_SECONDS", 0.05)
    monkeypatch.setattr(runner, "OWNED_KILL_SECONDS", 2)
    profile = tmp_path / "profile"
    profile.mkdir()
    log = tmp_path / "owned.log"
    program = """
import json, os, signal, sys, time
from pathlib import Path
read, write = os.pipe()
child = os.fork()
if child == 0:
    os.close(read)
    if sys.argv[3] == 'new-group':
        os.setpgid(0, 0)
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    os.write(write, b'R'); os.close(write)
    while True:
        Path(sys.argv[1]).write_text('inert writer')
        time.sleep(0.01)
os.close(write); assert os.read(read, 1) == b'R'; os.close(read)
print(json.dumps({'leader': os.getpid(), 'descendant': child}), flush=True)
if sys.argv[2] == 'success':
    os._exit(0)
if sys.argv[2] == 'nonzero':
    os._exit(7)
signal.pause()
"""
    sentinel = subprocess.Popen(
        [sys.executable, "-c", "import signal;print('READY',flush=True);signal.pause()"],
        stdout=subprocess.PIPE, start_new_session=True,
    )
    try:
        assert sentinel.stdout.readline() == b"READY\n"
        with log.open("wb") as output:
            args = [sys.executable, "-c", program, str(profile / "marker"), mode, "new-group" if new_group else "same-group"]
            if mode == "timeout":
                with pytest.raises(subprocess.TimeoutExpired):
                    runner.run_owned_command(args, cwd=tmp_path, env={"PATH": os.defpath}, stdout=output, timeout=0.5)
            else:
                result = runner.run_owned_command(args, cwd=tmp_path, env={"PATH": os.defpath}, stdout=output, timeout=5)
                assert result.returncode == (0 if mode == "success" else 7)
        identities = json.loads(log.read_text())
        assert all(not Path(f"/proc/{pid}").exists() for pid in identities.values())
        assert sentinel.poll() is None
        after = runner.ctypes.c_int()
        assert libc.prctl(37, runner.ctypes.byref(after), 0, 0, 0) == 0
        assert after.value == before.value
        shutil.rmtree(profile)
        assert not profile.exists()  # no surviving writer can recreate it
    finally:
        sentinel.kill()
        sentinel.wait(timeout=3)
        sentinel.stdout.close()


@pytest.mark.parametrize("field", ["birth", "pgid", "sid", "uid"])
def test_reused_or_foreign_leader_identity_is_refused_before_any_signal(monkeypatch, field):
    runner = module(monkeypatch)
    owner = {"pid": 424242, "birth": "10", "pgid": 424242, "sid": 424242, "uid": os.geteuid(), "state": "Z"}
    changed = {**owner, field: "11" if field == "birth" else owner[field] + 1}
    monkeypatch.setattr(runner, "_process_identity", lambda _pid: changed)
    monkeypatch.setattr(runner, "_session_members", lambda _owner: pytest.fail("unowned session scan"))
    monkeypatch.setattr(runner.os, "pidfd_open", lambda *_: pytest.fail("unowned PID handle"))
    with pytest.raises(runner.OwnedProcessCleanupError, match="identity changed"):
        runner._terminate_owned(SimpleNamespace(pid=owner["pid"]), owner)


@pytest.mark.parametrize("phase", ["step", "uninstall"])
def test_unverified_owned_process_shutdown_retains_private_state_and_refuses_claim(inert_run, monkeypatch, phase):
    f = inert_run
    original = f.runner.run_owned_command

    def fail(args, **kwargs):
        if ((phase == "step" and args[0] == "bash" and args[-1] == "work")
                or (phase == "uninstall" and "--path" in args and args[args.index("--path") + 1] == f.installs[1])):
            raise f.runner.OwnedProcessCleanupError("synthetic process shutdown refusal")
        return original(args, **kwargs)

    monkeypatch.setattr(f.runner, "run_owned_command", fail)
    with pytest.raises(RuntimeError, match="cleanup incomplete"):
        f.execute()
    assert receipt(f)["private_account_files_removed"] is False
    assert "owned-processes" in receipt(f)["errors"]
    assert f.profile.exists() and (f.output / "ci-private").exists()
    assert not Path(f.runner.NATIVE_SOURCE_INSTALL_PATH).exists()
