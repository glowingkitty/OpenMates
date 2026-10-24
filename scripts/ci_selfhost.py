"""Run the existing installer smoke contract inside the bounded GitHub queue.

The candidate workflow remains the source of installer commands and assertions.
This adapter supplies the Actions setup context already installed by our harness,
executes its shell steps, and returns honest source-bound results and cleanup.
It never starts a stack outside a GitHub-hosted runner or reads operator state.
See docs/architecture/isolated-github-tests.md.
"""

from __future__ import annotations

import hashlib
import ctypes
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import socket
import stat
import subprocess
import time
import tempfile
import urllib.request

from ci_environment import require_runner

EXPRESSION = re.compile(r"\$\{\{\s*([^}]+?)\s*\}\}")
EXPECTED_SETUP_ACTIONS = {"actions/checkout@v4", "actions/setup-node@v4", "pnpm/action-setup@v4", "actions/upload-artifact@v4"}
INSTALL_PATHS = ("/tmp/openmates-selfhost-source", "/tmp/openmates-selfhost-image")
NATIVE_SOURCE_INSTALL_PATH = "/tmp/openmates-native-selfhost-source"
NATIVE_STATE_DIR = "/tmp/openmates-native-selfhost-profile"
NATIVE_ENV = ("NATIVE_CLI_PATH", "NATIVE_SOURCE_INSTALL_PATH", "NATIVE_STATE_DIR")
OWNED_TERM_SECONDS = 3
OWNED_KILL_SECONDS = 3
SELFHOST_WORK_SECONDS = 105 * 60
SELFHOST_CLEANUP_SECONDS = 117 * 60
STEP_SECONDS = 3000
CLEANUP_COMMAND_SECONDS = 180
SHUTDOWN_RESERVE_SECONDS = OWNED_TERM_SECONDS + OWNED_KILL_SECONDS + 1
MAX_WORKFLOW_STEPS = 128
STEP_NAMES = frozenset({
    "Install workspace dependencies", "Build current branch CLI", "Build exact-source Rust self-host CLI",
    "Install published CLI from npm", "Stage OpenObserve image for self-hosted install",
    "Source-mode timing baseline", "Native source-mode install lifecycle", "Build local image-mode images",
    "Image-mode self-hosted install and timing", "Preserve existing protocol epochs across restart and update",
    "Preserve epoch 0 across restart", "Preserve epoch 0 across update",
    "Preserve epoch 1 across restart", "Preserve epoch 1 across update", "Restore ready epoch fixture",
    "Summarize setup timing", "Check server status JSON", "Check backend and web Docker containers",
    "Verify Chrome browser", "Run self-hosted smoke spec", "Show self-hosted status and logs",
    "Uninstall self-hosted edition",
})


class SelfhostDeadline(RuntimeError):
    pass


class SelfhostBudget:
    """One trusted clock, including outer setup; never reset by a workflow step."""
    def __init__(self, environment):
        try:
            self.started = float(environment["CI_SELFHOST_STARTED_MONOTONIC"])
            self.work = float(environment["CI_SELFHOST_WORK_DEADLINE_MONOTONIC"])
            self.cleanup = float(environment["CI_SELFHOST_CLEANUP_DEADLINE_MONOTONIC"])
        except (KeyError, TypeError, ValueError):
            raise SelfhostDeadline("Self-host clock unavailable") from None
        if (not all(math.isfinite(value) for value in (self.started, self.work, self.cleanup))
                or self.started <= 0 or self.started > time.monotonic()
                or abs(self.work - self.started - SELFHOST_WORK_SECONDS) > 0.01
                or abs(self.cleanup - self.started - SELFHOST_CLEANUP_SECONDS) > 0.01):
            raise SelfhostDeadline("Self-host clock invalid")

    def timeout(self, maximum, *, cleanup=False):
        remaining = (self.cleanup if cleanup else self.work) - time.monotonic() - SHUTDOWN_RESERVE_SECONDS
        if remaining <= 0:
            raise SelfhostDeadline("Self-host deadline exhausted")
        return min(maximum, remaining)

    def elapsed_ms(self):
        return max(0, int((time.monotonic() - self.started) * 1000))


def record_steps(path, steps):
    """Atomically retain only bounded, source-owned progress, never command text."""
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, prefix=".selfhost-progress-", delete=False) as handle:
        temporary = Path(handle.name)
        json.dump(steps, handle, separators=(",", ":"))
        handle.flush()
        os.fsync(handle.fileno())
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


class OwnedProcessCleanupError(RuntimeError):
    pass


def _process_identity(pid):
    directory = Path("/proc") / str(pid)
    fields = (directory / "stat").read_text().rsplit(") ", 1)[1].split()
    return {"pid": pid, "birth": fields[19], "pgid": int(fields[2]),
            "sid": int(fields[3]), "uid": directory.stat().st_uid, "state": fields[0]}


def _session_members(owner):
    rows = list(Path("/proc").iterdir())
    if len(rows) > 32768:
        raise OwnedProcessCleanupError("Owned process scan bound exceeded")
    result = []
    for row in rows:
        if not row.name.isdecimal():
            continue
        try:
            identity = _process_identity(int(row.name))
        except (FileNotFoundError, ProcessLookupError):
            continue
        if identity["sid"] == owner["sid"] and int(identity["birth"]) >= int(owner["birth"]):
            result.append(identity)
    return result


def _terminate_owned(child, owner):
    def signal_session(signum):
        current = _process_identity(child.pid)
        if (any(current[key] != owner[key] for key in ("pid", "birth", "pgid", "sid", "uid"))
                or owner["pid"] <= 1 or owner["pid"] in (os.getpid(), os.getpgrp(), os.getsid(0))):
            raise OwnedProcessCleanupError("Owned process identity changed")
        for row in _session_members(owner):
            if row["state"] in ("Z", "X"):
                continue
            try:
                descriptor = os.pidfd_open(row["pid"])
            except ProcessLookupError:
                continue
            try:
                try:
                    current = _process_identity(row["pid"])
                except (FileNotFoundError, ProcessLookupError):
                    continue
                if all(current[key] == row[key] for key in ("pid", "birth", "pgid", "sid", "uid")):
                    try:
                        signal.pidfd_send_signal(descriptor, signum)
                    except ProcessLookupError:
                        pass
            finally:
                os.close(descriptor)

    # waitid(WNOWAIT) leaves the leader unreaped: its birth-matching PID anchors
    # this private session until all signals are finished, even if the
    # shell exited while a grandchild continues to write.
    signal_session(signal.SIGTERM)
    deadline = time.monotonic() + OWNED_TERM_SECONDS
    while any(row["state"] not in ("Z", "X") for row in _session_members(owner)):
        if time.monotonic() >= deadline:
            break
        time.sleep(0.02)
    deadline = time.monotonic() + OWNED_KILL_SECONDS
    while any(row["state"] not in ("Z", "X") for row in _session_members(owner)):
        # Rust server operations create their own process groups. PID handles
        # cover every group in this owned session without a PGID-reuse race.
        signal_session(signal.SIGKILL)
        if time.monotonic() >= deadline:
            raise OwnedProcessCleanupError("Owned processes did not stop")
        time.sleep(0.02)
    members = _session_members(owner)
    child.wait(timeout=OWNED_KILL_SECONDS)
    for row in members:
        if row["pid"] == child.pid:
            continue
        while True:
            try:
                current = _process_identity(row["pid"])
            except (FileNotFoundError, ProcessLookupError):
                break
            if any(current[key] != row[key] for key in ("pid", "birth", "pgid", "sid", "uid")):
                break  # A reused PID is never reaped or signalled.
            try:
                reaped, _ = os.waitpid(row["pid"], os.WNOHANG)
            except ChildProcessError:
                raise OwnedProcessCleanupError("Owned descendant was not adopted") from None
            if reaped:
                break
            if time.monotonic() >= deadline:
                raise OwnedProcessCleanupError("Owned descendant was not reaped")
            time.sleep(0.02)


def run_owned_command(command, *, cwd, env, stdout, timeout):
    if not hasattr(os, "pidfd_open") or not hasattr(signal, "pidfd_send_signal"):
        raise OwnedProcessCleanupError("Owned subprocess PID handles unavailable")
    libc = ctypes.CDLL(None, use_errno=True)
    previous = ctypes.c_int()
    if libc.prctl(37, ctypes.byref(previous), 0, 0, 0) != 0 or libc.prctl(36, 1, 0, 0, 0) != 0:
        raise OwnedProcessCleanupError("Owned subprocess adoption unavailable")
    child = None
    try:
        child = subprocess.Popen(command, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                 stdout=stdout, stderr=subprocess.STDOUT, start_new_session=True)
        owner = _process_identity(child.pid)
        if owner["pgid"] != child.pid or owner["sid"] != child.pid or owner["uid"] != os.geteuid():
            raise OwnedProcessCleanupError("Owned subprocess session unavailable")
        try:
            deadline = time.monotonic() + timeout
            while os.waitid(os.P_PID, child.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT) is None:
                if time.monotonic() >= deadline:
                    raise subprocess.TimeoutExpired(command, timeout)
                time.sleep(0.02)
        finally:
            try:
                _terminate_owned(child, owner)
            except (OSError, subprocess.SubprocessError, OwnedProcessCleanupError):
                raise OwnedProcessCleanupError("Owned subprocess cleanup failed") from None
        return subprocess.CompletedProcess(command, child.returncode)
    finally:
        if libc.prctl(36, previous.value, 0, 0, 0) != 0:
            raise OwnedProcessCleanupError("Owned subprocess adoption restore failed")


def admit_cleanup(source: Path, declared: dict, env: dict) -> bool:
    if tuple(env.get(key) for key in ("SOURCE_INSTALL_PATH", "IMAGE_INSTALL_PATH")) != INSTALL_PATHS:
        raise RuntimeError("Installer paths changed; review the cleanup contract")
    native = any(key in declared for key in NATIVE_ENV)
    if native and (
        not all(key in declared for key in NATIVE_ENV)
        or env.get("NATIVE_CLI_PATH") != str(source / "frontend/packages/openmates-tui-native/target/release/openmates")
        or env.get("NATIVE_SOURCE_INSTALL_PATH") != NATIVE_SOURCE_INSTALL_PATH
        or env.get("NATIVE_STATE_DIR") != NATIVE_STATE_DIR
    ):
        raise RuntimeError("Native installer paths changed; review the cleanup contract")
    return native


def cleanup_command(source: Path, env: dict, install: str, native: bool = False) -> list[str]:
    allowed = INSTALL_PATHS + ((NATIVE_SOURCE_INSTALL_PATH,) if native else ())
    if install not in allowed:
        raise RuntimeError("Installer cleanup path is not admitted")
    if native and install != INSTALL_PATHS[0]:
        binary = source / "frontend/packages/openmates-tui-native/target/release/openmates"
        if (env.get("NATIVE_CLI_PATH") != str(binary)
                or env.get("NATIVE_STATE_DIR") != NATIVE_STATE_DIR
                or binary.is_symlink() or not binary.is_file()
                or not os.access(binary, os.X_OK)):
            raise RuntimeError("Native cleanup requires the exact compiled Rust executable and profile")
        return [str(binary), "--state-dir", NATIVE_STATE_DIR, "server", "uninstall", "--path", install, "--yes"]
    return ["node", str(source / "frontend/packages/openmates-cli/dist/cli.js"), "server", "uninstall", "--path", install, "--yes"]


def _remove_private_directory(path: Path):
    # Ubuntu's fd-based rmtree refuses a swapped root symlink and unlinks child
    # symlinks without visiting their targets. Anchor its parent without follow.
    if not shutil.rmtree.avoids_symlink_attacks:
        raise RuntimeError("Private cleanup requires symlink-resistant rmtree")
    parent = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        try:
            info = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
        except FileNotFoundError:
            return
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid():
            raise RuntimeError("Private cleanup refused a symlink, non-directory or foreign owner")
        shutil.rmtree(path.name, dir_fd=parent)
        if os.path.lexists(path):
            raise RuntimeError("Private cleanup left state behind")
    finally:
        os.close(parent)


def remove_native_profile(path: str):
    if path != NATIVE_STATE_DIR:
        raise RuntimeError("Native profile cleanup path is not admitted")
    _remove_private_directory(Path(path))


def expand(value: str, env: dict, source: Path, commit: str) -> str:
    """Resolve only the existing workflow's explicit, non-secret Actions inputs."""
    def replace(match):
        expression = match.group(1).strip()
        if expression == "github.workspace":
            return str(source)
        if expression == "github.sha":
            return commit
        if expression.startswith("env.") and expression[4:] in env:
            return env[expression[4:]]
        raise ValueError("Unsupported installer workflow expression: " + expression)
    return EXPRESSION.sub(replace, str(value))


def check_egress():
    for host in ("api.dev.openmates.org", "app.dev.openmates.org"):
        if set(socket.gethostbyname_ex(host)[2]) != {"127.0.0.2"}:
            raise RuntimeError("Installer shared-dev DNS isolation is missing")
        try:
            connection = socket.create_connection((host, 443), timeout=2)
        except OSError:
            continue
        connection.close()
        raise RuntimeError("Installer shared-dev HTTPS is reachable")


def capture_environment(source: Path, commit: str, workflow_hash: str, destination: Path, *, native: bool = False, budget=None):
    check_egress()
    services = {}
    for name in ("api", "webapp", "cms"):
        info = json.loads(subprocess.check_output(["docker", "inspect", name], text=True,
                          timeout=budget.timeout(30) if budget else 30))[0]
        if not info["State"]["Running"]:
            raise RuntimeError("Installer service stopped: " + name)
        configured_image = info["Config"]["Image"]
        if not configured_image.endswith(":selfhost-smoke-" + commit):
            raise RuntimeError("Installed image is not the current source build: " + name)
        services[name] = {"image": info["Image"], "tag": configured_image}
    for url in ("http://localhost:8000/health", "http://localhost:5173"):
        with urllib.request.urlopen(url, timeout=budget.timeout(15) if budget else 15) as response:
            if response.status != 200:
                raise RuntimeError("Installed runner endpoint is not healthy")
    native_identity = {}
    if native:
        binary = source / "frontend/packages/openmates-tui-native/target/release/openmates"
        native_identity["native_cli_sha256"] = hashlib.sha256(binary.read_bytes()).hexdigest()
    destination.write_text(json.dumps({
        "source_commit": commit, "harness_commit": os.environ.get("CI_HARNESS_COMMIT"),
        "runner_environment": "github-hosted", "runtime_profile": "selfhost-installer",
        "shared_dev_dns": "rejected", "shared_dev_https": "rejected",
        "workflow_sha256": workflow_hash, "services": services, **native_identity,
        "frontend": {"source_commit": commit, "url": "http://localhost:5173", "renderer": "installed-image"},
        "api_url": "http://localhost:8000", "source_context": str(source),
    }, indent=2))


def run(source: Path, results: list):
    require_runner()
    budget = SelfhostBudget(os.environ)
    check_egress()
    import yaml

    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=source, text=True).strip()
    run_id = os.environ["GITHUB_RUN_ID"]
    if not re.fullmatch(r"[0-9a-f]{40}", commit) or not re.fullmatch(r"[1-9][0-9]{0,20}", run_id):
        raise RuntimeError("Self-host observed subject identity invalid")
    workflow_path = source / ".github/workflows/selfhost-smoke.yml"
    workflow_bytes = workflow_path.read_bytes()
    workflow = yaml.safe_load(workflow_bytes)["jobs"]["install-smoke"]
    if workflow["runs-on"] != "ubuntu-latest":
        raise RuntimeError("Installer contract must use GitHub-hosted Ubuntu")
    if len(workflow["steps"]) > MAX_WORKFLOW_STEPS:
        raise RuntimeError("Installer workflow step bound exceeded")
    output = source / "test-results"
    private = output / "ci-private"
    env = {**os.environ, "GITHUB_WORKSPACE": str(source), "GITHUB_SHA": commit}
    for key, value in workflow.get("env", {}).items():
        env[key] = expand(value, env, source, commit)
    native = admit_cleanup(source, workflow.get("env", {}), env)
    installs = INSTALL_PATHS + ((NATIVE_SOURCE_INSTALL_PATH,) if native else ())
    private.mkdir(parents=True, exist_ok=True, mode=0o700)
    steps = []
    failed = False
    exhausted = False
    owned_processes_removed = True
    try:
        for index, step in enumerate(workflow["steps"]):
            if "uses" in step:
                if step["uses"] not in EXPECTED_SETUP_ACTIONS:
                    raise RuntimeError("New installer setup action needs harness support")
                continue
            if step.get("if") not in (None, "always()"):
                raise RuntimeError("Unsupported conditional installer step")
            if failed and step.get("if") != "always()":
                continue
            name = step.get("name", "unnamed")
            progress = {"step": name if name in STEP_NAMES else "Unrecognized installer step",
                        "step_index": index, "phase": "started", "source_commit": commit,
                        "run_id": run_id, "started_elapsed_ms": budget.elapsed_ms()}
            step_env = dict(env)
            for key, value in step.get("env", {}).items():
                step_env[key] = expand(value, step_env, source, commit)
            cwd = (source / step.get("working-directory", ".")).resolve()
            if not cwd.is_relative_to(source.resolve()):
                raise RuntimeError("Installer working directory escaped source")
            command = expand(step["run"], step_env, source, commit)
            try:
                timeout = budget.timeout(STEP_SECONDS)
            except SelfhostDeadline:
                failed = exhausted = True
                progress.update(phase="not_started", exit_code=1, error="work_deadline_exhausted")
                steps.append(progress)
                record_steps(output / "ci-selfhost-steps.json", steps)
                print(json.dumps(progress), flush=True)
                break
            steps.append(progress)
            record_steps(output / "ci-selfhost-steps.json", steps)
            print(json.dumps(progress), flush=True)
            with (private / "installer.log").open("a") as log:
                try:
                    result = run_owned_command(["bash", "-eo", "pipefail", "-c", command], cwd=cwd, env=step_env,
                                               stdout=log, timeout=timeout)
                    status = {"exit_code": result.returncode}
                except OwnedProcessCleanupError:
                    owned_processes_removed = False
                    status = {"exit_code": 1, "error": "owned_process_cleanup_failed"}
                except (OSError, subprocess.TimeoutExpired) as error:
                    status = {"exit_code": 1,
                              "error": "timeout" if isinstance(error, subprocess.TimeoutExpired) else "process_start_failed"}
            progress.update(status, phase="completed", completed_elapsed_ms=budget.elapsed_ms())
            record_steps(output / "ci-selfhost-steps.json", steps)
            print(json.dumps(steps[-1]), flush=True)
            failed = failed or status["exit_code"] != 0
            if name == "Check backend and web Docker containers" and not failed:
                capture_environment(source, commit, hashlib.sha256(workflow_bytes).hexdigest(), output / "ci-environment.json", native=native, budget=budget)
    finally:
        # The original always() cleanup may mask errors; verify the actual result.
        # Retry cleanup through the supported CLI if an earlier step raised.
        cleanup_failures = []
        def save_cleanup_progress():
            try:
                record_steps(output / "ci-selfhost-steps.json", steps)
            except OSError:
                if "progress-receipt" not in cleanup_failures:
                    cleanup_failures.append("progress-receipt")
        installations_removed = True
        for cleanup_index, install in enumerate(installs):
            if os.path.lexists(install):
                removed = False
                cleanup_progress = {"step": "Owned installer cleanup", "step_index": MAX_WORKFLOW_STEPS + cleanup_index,
                                    "phase": "started", "source_commit": commit, "run_id": run_id,
                                    "started_elapsed_ms": budget.elapsed_ms()}
                steps.append(cleanup_progress)
                save_cleanup_progress()
                print(json.dumps(cleanup_progress), flush=True)
                try:
                    with (private / "cleanup.log").open("a") as log:
                        if Path(install).is_symlink():
                            raise RuntimeError("Installer cleanup refused a root symlink")
                        result = run_owned_command(cleanup_command(source, env, install, native),
                                                   cwd=source, env=env, stdout=log,
                                                   timeout=budget.timeout(CLEANUP_COMMAND_SECONDS, cleanup=True))
                        removed = result.returncode == 0 and not os.path.lexists(install)
                except OwnedProcessCleanupError:
                    owned_processes_removed = False
                except (RuntimeError, OSError, subprocess.TimeoutExpired):
                    # A failed cleanup or unavailable private log cannot skip
                    # another installation/profile or select another CLI.
                    pass
                cleanup_progress.update(phase="completed", exit_code=0 if removed else 1,
                                        completed_elapsed_ms=budget.elapsed_ms())
                if not removed:
                    cleanup_progress["error"] = "owned_cleanup_incomplete"
                save_cleanup_progress()
                print(json.dumps(cleanup_progress), flush=True)
                if not removed:
                    cleanup_failures.append(install)
                    installations_removed = False
        remaining_resources = {}
        for kind, command in (("containers", ["docker", "ps", "-aq"]), ("volumes", ["docker", "volume", "ls", "-q"])):
            try:
                remaining = subprocess.check_output([*command, "--filter", "label=com.docker.compose.project"],
                                                    text=True, timeout=budget.timeout(30, cleanup=True)).strip()
                remaining_resources[kind] = "nonzero" if remaining else 0
            except (OSError, subprocess.SubprocessError, SelfhostDeadline):
                remaining_resources[kind] = "unknown"
            if remaining_resources[kind] != 0:
                cleanup_failures.append(kind)
        private_removed = installations_removed and owned_processes_removed
        if not owned_processes_removed:
            cleanup_failures.append("owned-processes")
        if native and owned_processes_removed:
            try:
                budget.timeout(1, cleanup=True)
                remove_native_profile(env["NATIVE_STATE_DIR"])
            except (RuntimeError, OSError):
                cleanup_failures.append("native-profile")
                private_removed = False
        if owned_processes_removed:
            try:
                budget.timeout(1, cleanup=True)
                _remove_private_directory(private)
            except (RuntimeError, OSError):
                cleanup_failures.append("ci-private")
                private_removed = False
        (output / "ci-cleanup.json").write_text(json.dumps({"run_id": os.environ["GITHUB_RUN_ID"],
            "harness_commit": os.environ.get("CI_HARNESS_COMMIT"),
            "containers_remaining": remaining_resources["containers"],
            "volumes_remaining": remaining_resources["volumes"],
            "private_account_files_removed": private_removed, "errors": cleanup_failures}))
        save_cleanup_progress()
        if cleanup_failures:
            raise RuntimeError("Installer cleanup incomplete: " + ", ".join(cleanup_failures))
    report = output / "selfhost-smoke-playwright.json"
    stats = json.loads(report.read_text()).get("stats", {}) if report.is_file() else {}
    if report.is_file():
        shutil.copyfile(report, output / "ci-spec-selfhost.json")
    complete = (not failed and not exhausted and bool(stats.get("expected", 0) + stats.get("unexpected", 0))
                and not stats.get("skipped", 0))
    results.append({"spec": "selfhost-smoke.spec.ts", "stats": stats, "coverage_complete": complete,
                    "exit_code": int(failed or not complete or bool(stats.get("unexpected", 0)))})
