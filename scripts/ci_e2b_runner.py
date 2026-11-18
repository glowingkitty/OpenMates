#!/usr/bin/env python3
"""One-job E2B sandboxes that act as GitHub Actions runners for CI overflow.

When every GitHub-hosted slot is busy, the CI coordinator calls `start()` for a
queued component or pytest job. That registers a single-use just-in-time (JIT)
runner with labels `openmates-e2b` and `openmates-e2b-<token>`, then spawns a
detached `launch` process which holds one slot of the shared dev E2B cap
(`e2b_dev_capacity`), creates a sandbox from the `openmates-ci-runner` template,
starts the official runner (`run.sh --jitconfig`) and owns the sandbox until the
single job ends, no job was picked up, or the deadline passes. The launcher always
kills the sandbox, removes the registration if it still exists and records spend.

The JIT config is a credential: it travels only through a 0600 file that the
launcher deletes after reading it, and is never logged or put on a command line
of a long-lived local process.

Usage (the coordinator imports `start`/`available`; humans use the CLI):
  python3 scripts/ci_e2b_runner.py status
  <heavy-remote venv python> scripts/ci_e2b_runner.py template
  <heavy-remote venv python> scripts/ci_e2b_runner.py launch ...   (internal)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import agent_question  # noqa: E402 - sibling module; path set up above
import discord_webhook  # noqa: E402
import e2b_dev_capacity  # noqa: E402
import host_load_guard  # noqa: E402

TEMPLATE_ALIAS = "openmates-ci-runner"
RUNNER_LABEL = "openmates-e2b"
RUNNER_VERSION = "2.338.2"
OVERFLOW_MODES = frozenset({"component", "pytest", "e2e"})
SANDBOX_CPUS = 8
SANDBOX_MEMORY_MB = 8192
# A run at 90% of sandbox memory, or with a kernel OOM kill, is reported to the owner.
MEMORY_ALERT_MB = int(SANDBOX_MEMORY_MB * 0.9)
ALERT_WEBHOOK_KEYS = ("DISCORD_WEBHOOK_DEV_NIGHTLY", "DISCORD_WEBHOOK_DAILY_MEETING")
RUNNER_DIR = "/home/user/actions-runner"
READY_WAIT_SECONDS = 20
NO_JOB_SECONDS = 600
POLL_SECONDS = 5
MEMORY_POLL_SECONDS = 15
DEADLINE_EXTRA_MINUTES = 15
VENV_PYTHON = Path.home() / ".cache" / "openmates" / "heavy-remote" / "venv" / "bin" / "python"
SCRIPT = Path(__file__).resolve()


def job_label(token: str) -> str:
    """Unique runner label/name for one job: `openmates-e2b-<token>` in [a-z0-9-], at most 60 chars."""
    clean = re.sub(r"[^a-z0-9-]+", "-", token.lower()).strip("-")
    return f"{RUNNER_LABEL}-{clean}"[:60].rstrip("-")


def state_root() -> Path:
    path = host_load_guard.canonical_root() / "logs" / "ci-coordinator" / "e2b"
    path.mkdir(parents=True, exist_ok=True)
    return path


def state_path(label: str) -> Path:
    return state_root() / f"{label}.json"


def write_state(label: str, **fields) -> dict:
    path = state_path(label)
    data = json.loads(path.read_text()) if path.exists() else {}
    data.update(fields)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data))
    tmp.replace(path)
    return data


def read_state(label: str) -> dict:
    path = state_path(label)
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def overflow_enabled() -> bool:
    """Automatic overflow switch: `logs/ci-coordinator/e2b-overflow.json` {"enabled": true}.

    Off by default so a broken runner path never fails other chats' jobs; jobs
    submitted with `--runner e2b` use E2B regardless.
    """
    path = state_root().parent / "e2b-overflow.json"
    try:
        return json.loads(path.read_text()).get("enabled") is True
    except (OSError, json.JSONDecodeError, AttributeError):
        return False


def available() -> bool:
    """Non-binding: a dev E2B slot looks free and the daily budget is not used up."""
    config = e2b_dev_capacity.settings()
    if e2b_dev_capacity.budget_exhausted(config):
        return False
    return len(e2b_dev_capacity.held_slots()) < config.dev_slots


# --------------------------------------------------------------------------
# GitHub runner registration.
# --------------------------------------------------------------------------

def register_runner(repo: str, label: str) -> tuple[int, str, str]:
    """Create a JIT runner; returns (runner id, runner name, encoded jit config)."""
    body = {"name": label, "runner_group_id": 1, "labels": [RUNNER_LABEL, label], "work_folder": "_work"}
    result = subprocess.run(
        ["gh", "api", "--method", "POST", f"repos/{repo}/actions/runners/generate-jitconfig", "--input", "-"],
        input=json.dumps(body), capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise RuntimeError(f"generate-jitconfig failed: {result.stderr.strip()[:300]}")
    data = json.loads(result.stdout)
    return int(data["runner"]["id"]), data["runner"]["name"], data["encoded_jit_config"]


def delete_runner(repo: str, runner_id: int) -> None:
    """Remove a registration; a runner that already finished its job is gone (404), which is fine."""
    result = subprocess.run(["gh", "api", "--method", "DELETE", f"repos/{repo}/actions/runners/{runner_id}"],
                            capture_output=True, text=True, timeout=60)
    if result.returncode != 0 and "404" not in result.stderr and "Not Found" not in result.stderr:
        print(f"ci_e2b_runner: could not delete runner {runner_id}: {result.stderr.strip()[:200]}",
              file=sys.stderr, flush=True)


# --------------------------------------------------------------------------
# Coordinator side.
# --------------------------------------------------------------------------

def spawn_launcher(argv: list[str], log: Path) -> subprocess.Popen:
    with log.open("ab") as out:
        return subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=out, stderr=out, start_new_session=True)


def start(repo: str, token: str, timeout_minutes: int, root: Path, *, no_job_seconds: int = NO_JOB_SECONDS,
          ready_wait: float = READY_WAIT_SECONDS, mode: str = "", specs: list[str] | None = None) -> dict | None:
    """Register a JIT runner and start its sandbox. None when no sandbox could be started.

    `mode` and `specs` are recorded in the runner state so memory reports name the job.
    """
    label = job_label(token)
    state_path(label).unlink(missing_ok=True)
    try:
        runner_id, runner_name, jit = register_runner(repo, label)
    except (RuntimeError, OSError, subprocess.TimeoutExpired, json.JSONDecodeError, KeyError) as exc:
        print(f"ci_e2b_runner: no runner registered for {label}: {exc}", file=sys.stderr, flush=True)
        return None
    cfg = state_root() / f"{label}.cfg"
    fd = os.open(cfg, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as handle:
        handle.write(jit)
    del jit
    python = str(VENV_PYTHON) if VENV_PYTHON.exists() else sys.executable
    argv = [python, str(SCRIPT), "launch", "--repo", repo, "--label", label, "--runner-id", str(runner_id),
            "--timeout-minutes", str(timeout_minutes), "--config-file", str(cfg),
            "--no-job-seconds", str(no_job_seconds)]
    write_state(label, state="starting", runner_id=runner_id, runner_name=runner_name, repo=repo,
                mode=mode, specs=list(specs or []))
    launcher = spawn_launcher(argv, state_root() / f"{label}.log")
    deadline = time.monotonic() + ready_wait
    state: dict = {}
    while time.monotonic() < deadline:
        state = read_state(label)
        if state.get("state") == "ready" or state.get("state") in ("failed", "done", "timeout"):
            break
        if launcher.poll() is not None:
            state = read_state(label)
            break
        time.sleep(0.5)
    if state.get("state") == "ready":
        return {"label": label, "runner_id": runner_id, "runner_name": runner_name,
                "sandbox_id": state.get("sandbox_id", ""), "state_file": str(state_path(label))}
    if launcher.poll() is None:
        launcher.kill()
        launcher.wait()
    cfg.unlink(missing_ok=True)
    delete_runner(repo, runner_id)
    write_state(label, state="failed", reason=state.get("reason", "launcher not ready in time"))
    return None


# --------------------------------------------------------------------------
# Launcher (detached process).
# --------------------------------------------------------------------------

def runner_script() -> str:
    """Shell wrapper run in the sandbox: read the config, delete its file, run one job."""
    return (f"cd {RUNNER_DIR} && CFG=$(cat /home/user/.jit) && rm -f /home/user/.jit && "
            "(./run.sh --jitconfig \"$CFG\" > /home/user/runner.log 2>&1; echo $? > /home/user/runner.exit)")


OOM_PROBE = "sudo -n dmesg 2>/dev/null | grep -ciE 'out of memory|oom-kill' || true"


PROBE = ("if [ -f /home/user/runner.exit ]; then echo exit; else echo run; fi; "
         "if pgrep -f '[R]unner.Worker' >/dev/null; then echo worker; else echo noworker; fi; "
         "free -m | awk '/^Mem:/ {print $3}'")


def parse_probe(text: str) -> dict:
    lines = text.split()
    return {"exited": "exit" in lines, "worker": "worker" in lines,
            "used_mb": int(lines[-1]) if lines and lines[-1].isdigit() else 0}


def sandbox_errors() -> tuple[type[BaseException], ...]:
    """Failures of sandbox calls that the launcher records instead of crashing on."""
    try:
        from e2b import SandboxException, TimeoutException
    except ImportError:
        return (OSError, RuntimeError)
    return (OSError, RuntimeError, SandboxException, TimeoutException)


def run_launch(args: argparse.Namespace, *, create_sandbox=None, now=time.monotonic, sleep=time.sleep) -> int:
    """Own one sandbox for one job. Always cleans up and records spend."""
    from_args = args
    label, repo = args.label, args.repo
    cfg_path = Path(from_args.config_file)
    jit = cfg_path.read_text()
    cfg_path.unlink(missing_ok=True)
    slot = e2b_dev_capacity.try_acquire(f"ci-runner {label}")
    if slot is None:
        write_state(label, state="failed", reason="no dev E2B slot free")
        delete_runner(repo, from_args.runner_id)
        return 1
    if e2b_dev_capacity.budget_exhausted():
        slot.release()
        write_state(label, state="failed", reason="daily E2B budget exhausted")
        delete_runner(repo, from_args.runner_id)
        return 1
    started = now()
    sandbox = None
    final = "failed"
    peak_mb = 0
    try:
        sandbox = (create_sandbox or create_e2b_sandbox)(from_args.timeout_minutes + DEADLINE_EXTRA_MINUTES, label)
        sandbox.files.write("/home/user/.jit", jit)
        del jit
        sandbox.commands.run("chmod 600 /home/user/.jit; (pgrep -x dockerd >/dev/null || sudo -n sh -c "
                             "'nohup dockerd >/var/log/dockerd.log 2>&1 &') >/dev/null 2>&1; true", timeout=60)
        sandbox.commands.run(runner_script(), background=True, timeout=0)
        write_state(label, state="ready", sandbox_id=sandbox.sandbox_id, started=time.time())
        deadline = started + from_args.timeout_minutes * 60
        worker_seen = False
        next_mem = started
        while True:
            sleep(POLL_SECONDS)
            probe = parse_probe(sandbox.commands.run(PROBE, timeout=30).stdout)
            peak_mb = max(peak_mb, probe["used_mb"])
            worker_seen = worker_seen or probe["worker"]
            if now() >= next_mem:
                write_state(label, peak_memory_mb=peak_mb)
                next_mem = now() + MEMORY_POLL_SECONDS
            if probe["exited"]:
                final = "done"
                break
            if not worker_seen and now() - started > from_args.no_job_seconds:
                final = "timeout"
                write_state(label, reason="no job picked up")
                break
            if now() >= deadline:
                final = "timeout"
                write_state(label, reason="deadline passed")
                break
    except sandbox_errors() as exc:
        write_state(label, reason=f"{type(exc).__name__}: {str(exc)[:200]}")
    finally:
        oom_kills = 0
        if sandbox is not None:
            try:
                out = sandbox.commands.run(OOM_PROBE, timeout=30).stdout.strip()
                oom_kills = int(out) if out.isdigit() else 0
            except sandbox_errors() as exc:
                print(f"ci_e2b_runner: OOM probe failed for {label}: {exc}", file=sys.stderr)
            try:
                sandbox.kill()
            except sandbox_errors() as exc:
                print(f"ci_e2b_runner: could not kill sandbox {sandbox.sandbox_id}: {exc}", file=sys.stderr)
        delete_runner(repo, from_args.runner_id)
        seconds = now() - started
        cost = e2b_dev_capacity.record_spend(seconds, SANDBOX_CPUS, SANDBOX_MEMORY_MB) if sandbox is not None else 0.0
        slot.release()
        state = write_state(label, state=final, seconds=round(seconds, 1), cost_usd=round(cost, 4),
                            peak_memory_mb=peak_mb, oom_kills=oom_kills, ended=time.time())
        report_memory(label, state)
    return 0 if final == "done" else 1


def memory_alert(state: dict) -> str | None:
    """Owner-facing alert text when a run reached the sandbox memory limit, else None."""
    peak, oom = int(state.get("peak_memory_mb") or 0), int(state.get("oom_kills") or 0)
    if peak < MEMORY_ALERT_MB and not oom:
        return None
    specs = ", ".join(state.get("specs") or []) or "unknown spec"
    return (f"E2B CI runner at its memory limit: {state.get('mode') or 'unknown mode'} job ({specs}) peaked at "
            f"{peak} of {SANDBOX_MEMORY_MB} MB, kernel OOM kills: {oom}. This spec may need a GitHub-hosted runner.")


def report_memory(label: str, state: dict, *, post=None) -> bool:
    """Append a memory alert to memory-alerts.jsonl and push it to Discord. True when an alert was raised."""
    text = memory_alert(state)
    if text is None:
        return False
    url = next((value for key in ALERT_WEBHOOK_KEYS if (value := agent_question.configured_value(
        host_load_guard.canonical_root(), key))), "")
    sent = (post or discord_webhook.post_message)(webhook_url=url, payload={"content": text}) if url else None
    with (state_root() / "memory-alerts.jsonl").open("a") as out:
        out.write(json.dumps({"at": time.time(), "label": label, "mode": state.get("mode", ""),
                              "specs": state.get("specs", []), "peak_memory_mb": state.get("peak_memory_mb"),
                              "oom_kills": state.get("oom_kills", 0), "notified": bool(sent)}) + "\n")
    return True


def create_e2b_sandbox(timeout_minutes: int, label: str):
    from e2b import Sandbox

    import heavy_remote

    return Sandbox.create(template=TEMPLATE_ALIAS, timeout=timeout_minutes * 60, api_key=heavy_remote.e2b_api_key(),
                          metadata={"purpose": "ci-runner", "label": label})


# --------------------------------------------------------------------------
# Template and status.
# --------------------------------------------------------------------------

APT_PACKAGES = ["sudo", "git", "curl", "wget", "jq", "zip", "unzip", "zstd", "xz-utils", "python3", "python3-pip",
                "python3-venv", "build-essential", "ca-certificates", "gnupg", "docker.io", "docker-compose-v2",
                "docker-buildx", "gh", "lsb-release", "ffmpeg", "xvfb", "dnsutils", "pkg-config", "libssl-dev",
                "rsync", "file", "iproute2", "procps"]
# GitHub's ubuntu-24.04 image ships these; workflow steps call them directly.
RUSTUP_PATH = "/home/user/.cargo/bin"


def template_definition():
    from e2b import Template

    tarball = f"actions-runner-linux-x64-{RUNNER_VERSION}.tar.gz"
    url = f"https://github.com/actions/runner/releases/download/v{RUNNER_VERSION}/{tarball}"
    return (
        Template().from_image("ubuntu:24.04")
        .set_user("root")
        .run_cmd("apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends "
                 + " ".join(APT_PACKAGES) + " && rm -rf /var/lib/apt/lists/*")
        .run_cmd("id user >/dev/null 2>&1 || useradd -m -s /bin/bash user; "
                 "echo 'user ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/user && chmod 440 /etc/sudoers.d/user; "
                 "getent group docker >/dev/null || groupadd docker; usermod -aG docker user")
        .run_cmd(f"mkdir -p {RUNNER_DIR} && curl -fsSL {url} | tar xz -C {RUNNER_DIR} && "
                 f"{RUNNER_DIR}/bin/installdependencies.sh && chown -R user:user /home/user")
        .set_user("user")
        .set_workdir("/home/user")
        .run_cmd("curl -fsSL https://sh.rustup.rs | sh -s -- -y --profile minimal --default-toolchain none")
        # The runner reads PATH for every job from `.path`; keep rustup/cargo on it like the hosted image.
        .run_cmd(f"echo '{RUSTUP_PATH}:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin' > {RUNNER_DIR}/.path")
    )


def build_template() -> int:
    from e2b import Template

    import heavy_remote

    started = time.monotonic()
    info = Template.build(template_definition(), name=TEMPLATE_ALIAS, cpu_count=SANDBOX_CPUS,
                          memory_mb=SANDBOX_MEMORY_MB, api_key=heavy_remote.e2b_api_key())
    print(f"ci_e2b_runner: built {TEMPLATE_ALIAS} {info.template_id} in {time.monotonic() - started:.0f}s")
    return 0


def print_memory() -> int:
    """Finished runs by peak memory, heaviest first, against the sandbox limit."""
    rows = []
    for path in state_root().glob("*.json"):
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if data.get("state") in ("done", "timeout", "failed") and data.get("peak_memory_mb"):
            rows.append(data)
    for data in sorted(rows, key=lambda item: -int(item["peak_memory_mb"])):
        flag = "ALERT" if memory_alert(data) else "ok"
        print(f"{data['peak_memory_mb']:>6} MB / {SANDBOX_MEMORY_MB}  {flag:<5}  {data.get('mode') or '-':<9}  "
              f"oom={data.get('oom_kills', 0)}  {', '.join(data.get('specs') or []) or '-'}")
    return 0


def print_status() -> int:
    for path in sorted(state_root().glob("*.json")):
        print(path.stem, path.read_text())
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    sub.add_parser("template")
    sub.add_parser("memory", help="finished runs by peak memory against the 8 GB sandbox limit")
    launch = sub.add_parser("launch")
    launch.add_argument("--repo", required=True)
    launch.add_argument("--label", required=True)
    launch.add_argument("--runner-id", type=int, required=True)
    launch.add_argument("--timeout-minutes", type=int, required=True)
    launch.add_argument("--config-file", required=True)
    launch.add_argument("--no-job-seconds", type=int, default=NO_JOB_SECONDS)
    args = parser.parse_args(argv)
    if args.cmd == "launch":
        # SIGTERM must unwind through run_launch's cleanup (kill sandbox, delete registration, record spend).
        signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
    if args.cmd == "status":
        return print_status()
    if args.cmd == "memory":
        return print_memory()
    if args.cmd == "template":
        return build_template()
    return run_launch(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
