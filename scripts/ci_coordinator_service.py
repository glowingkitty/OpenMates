#!/usr/bin/env python3
"""Install and audit the persistent, linger-backed isolated CI coordinator."""

# contract-test-file: infrastructure

from __future__ import annotations

import argparse
import fcntl
import hashlib
import os
from pathlib import Path
import pwd
import subprocess
import sys


UNIT_NAME = "openmates-ci-coordinator.service"
CODE_FINGERPRINT_ENV = "OPENMATES_CI_CODE_FINGERPRINT"


def code_fingerprint(root: Path) -> str:
    """Identify coordinator and CI helper code without reading queue data."""
    digest = hashlib.sha256()
    paths = sorted((root / "scripts").glob("ci_*.py"))
    if not (root / "scripts/ci_coordinator.py").is_file():
        raise ValueError("coordinator source unavailable")
    for path in paths:
        content = path.read_bytes()
        digest.update(path.name.encode() + b"\0" + str(len(content)).encode() + b"\0" + content)
    return digest.hexdigest()


def running_code_fingerprint(pid: int) -> str | None:
    """Read only the startup marker; never expose the process environment."""
    try:
        with Path(f"/proc/{pid}/environ").open("rb") as stream:
            environment = stream.read(1024 * 1024 + 1)
        if len(environment) > 1024 * 1024:
            return None
        prefix = CODE_FINGERPRINT_ENV.encode() + b"="
        values = [entry[len(prefix):] for entry in environment.split(b"\0") if entry.startswith(prefix)]
        return values[0].decode("ascii") if len(values) == 1 else None
    except (OSError, UnicodeError):
        return None


def canonical_root() -> Path:
    checkout = Path(__file__).resolve().parents[1]
    common = subprocess.check_output(
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
        cwd=checkout, text=True,
    ).strip()
    return Path(common).parent


def user_manager_env(uid: int | None = None) -> dict[str, str]:
    uid = os.getuid() if uid is None else uid
    runtime = f"/run/user/{uid}"
    return {
        **os.environ,
        "XDG_RUNTIME_DIR": runtime,
        "DBUS_SESSION_BUS_ADDRESS": f"unix:path={runtime}/bus",
    }


def render_unit(root: Path) -> str:
    root = root.resolve()
    return "\n".join([
        "[Unit]",
        "Description=OpenMates isolated GitHub CI coordinator",
        "Wants=network-online.target",
        "After=network-online.target",
        "",
        "[Service]",
        "Type=simple",
        f"WorkingDirectory={root}",
        f"ExecStart={sys.executable} {root}/scripts/ci_coordinator.py serve",
        "Restart=on-failure",
        "RestartSec=10",
        "MemoryMax=256M",
        "Environment=PYTHONUNBUFFERED=1",
        f"Environment={CODE_FINGERPRINT_ENV}={code_fingerprint(root)}",
        "",
        "[Install]",
        "WantedBy=default.target",
        "",
    ])


def manager(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["systemctl", "--user", *args], env=user_manager_env(),
        capture_output=True, text=True, check=False,
    )


def lingering_enabled() -> bool:
    name = pwd.getpwuid(os.getuid()).pw_name
    result = subprocess.run(
        ["loginctl", "show-user", name, "-p", "Linger", "--value"],
        capture_output=True, text=True, check=False,
    )
    return result.returncode == 0 and result.stdout.strip() == "yes"


def check(root: Path, unit_path: Path) -> list[str]:
    failures = []
    if not lingering_enabled():
        failures.append("user lingering disabled")
    if not unit_path.is_file() or unit_path.read_text() != render_unit(root):
        failures.append("persistent unit missing or drifted")
    if manager("is-enabled", "--quiet", UNIT_NAME).returncode:
        failures.append("persistent unit not enabled")
    if manager("is-active", "--quiet", UNIT_NAME).returncode:
        failures.append("coordinator not active")
    fragment = manager("show", UNIT_NAME, "-p", "FragmentPath", "--value")
    if fragment.returncode or fragment.stdout.strip() != str(unit_path):
        failures.append("running coordinator is not the persistent unit")
    process = manager("show", UNIT_NAME, "-p", "MainPID", "--value")
    try:
        pid = int(process.stdout.strip()) if process.returncode == 0 else 0
    except ValueError:
        pid = 0
    if pid <= 0 or running_code_fingerprint(pid) != code_fingerprint(root):
        failures.append("coordinator loaded code missing or stale; reinstall to reload safely")
    return failures


def install(root: Path, unit_path: Path) -> list[str]:
    if not lingering_enabled():
        return ["user lingering disabled; enable it before installing the coordinator"]
    unit_path.parent.mkdir(parents=True, exist_ok=True)
    if not check(root, unit_path):
        return []
    # Stop the transient owner under the coordinator's existing serialized
    # lock. The durable queue and dispatched GitHub runs are left untouched.
    lock_path = root / "logs/ci-coordinator/queue.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        stopped = manager("stop", UNIT_NAME)
        if stopped.returncode and "not loaded" not in stopped.stderr:
            return ["could not stop prior coordinator"]
        temporary = unit_path.with_suffix(".tmp")
        temporary.write_text(render_unit(root))
        temporary.replace(unit_path)
        for command in (("daemon-reload",), ("enable", "--now", UNIT_NAME)):
            result = manager(*command)
            if result.returncode:
                return ["systemd " + " ".join(command) + " failed"]
    return check(root, unit_path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--check", action="store_true")
    action.add_argument("--install", action="store_true")
    parser.add_argument("--root", type=Path, default=canonical_root())
    args = parser.parse_args()
    root = args.root.resolve()
    unit_path = Path.home() / ".config/systemd/user" / UNIT_NAME
    failures = install(root, unit_path) if args.install else check(root, unit_path)
    print("coordinator_service=ok" if not failures else "coordinator_service=failed: " + "; ".join(failures))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
