"""Trusted exact-target GitHub provisioning; never installs a dev-host provider."""

import json
import os
from pathlib import Path
import signal
import subprocess
import time

SPEC = "cli-rust-native-keyring.spec.ts"
PACKAGES = (
    "gnome-keyring",
    "dbus-daemon",
    "libglib2.0-bin",
    "zutty",
    "fonts-dejavu-core",
    "x11-xserver-utils",
    "xdotool",
    "ffmpeg",
    "xvfb",
    "util-linux",
)
ATTEMPT_MS = 18 * 60_000
FINALIZE_MS = 60_000


def admitted(specs, env):
    return (
        specs == [SPEC]
        and env.get("CI_TEST_MODE") == "e2e"
        and env.get("GITHUB_ACTIONS") == "true"
        and env.get("CI") == "true"
        and env.get("RUNNER_ENVIRONMENT") == "github-hosted"
        and env.get("OPENMATES_CI_ISOLATED") == "1"
    )


def command(argv, env, deadline):
    # No shell or inherited account/provider credentials reach apt tools.
    if time.monotonic() >= deadline:
        raise RuntimeError("native_keyring_package_deadline")
    child = subprocess.Popen(
        argv,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    try:
        out, err = child.communicate(timeout=max(0.1, deadline - time.monotonic()))
        if child.returncode or len(out) > 1024 * 1024 or len(err) > 1024 * 1024:
            raise RuntimeError("native_keyring_package_command_failed")
        return out
    finally:
        if child.poll() is None:
            # Our unreaped direct child pins its PID/process-group identity.
            os.killpg(child.pid, signal.SIGTERM)
            try:
                child.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                child.communicate(timeout=5)


def prepare(specs, root, environ=None):
    env = os.environ if environ is None else environ
    if not admitted(specs, env):
        raise RuntimeError("native_keyring_exact_isolated_target_required")
    root = Path(root)
    started = time.monotonic()
    deadline = min(started + 180, started + (ATTEMPT_MS - FINALIZE_MS) / 1000)
    safe = {
        "PATH": "/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "HOME": "/root",
        "DEBIAN_FRONTEND": "noninteractive",
    }
    flags = [
        "-o",
        "Acquire::AllowInsecureRepositories=false",
        "-o",
        "APT::Get::AllowUnauthenticated=false",
        "-o",
        "Acquire::Retries=0",
        "-o",
        "Acquire::http::Timeout=20",
        "-o",
        "Acquire::https::Timeout=20",
    ]
    command(
        ["/usr/bin/sudo", "--non-interactive", "/usr/bin/apt-get", *flags, "update"],
        safe,
        deadline,
    )
    command(
        [
            "/usr/bin/sudo",
            "--non-interactive",
            "/usr/bin/apt-get",
            *flags,
            "install",
            "--yes",
            "--no-install-recommends",
            *PACKAGES,
        ],
        safe,
        deadline,
    )
    installed = command(
        ["/usr/bin/dpkg-query", "-W", "-f=${Package}=${Version}\n", *PACKAGES],
        safe,
        deadline,
    ).decode("ascii")
    policy = command(
        ["/usr/bin/apt-cache", "policy", *PACKAGES], safe, deadline
    ).decode("ascii")
    # Do not infer architecture or an exact package version from the dev host.
    receipt = {
        "schemaVersion": 1,
        "kind": "native-keyring-packaged-provider",
        "status": "passed",
        "packages": installed.splitlines(),
        "aptPolicy": policy,
        "authentication": "APT repository signature verification required; insecure/unauthenticated disabled",
        "scope": SPEC,
        "elapsedMs": round((time.monotonic() - started) * 1000),
        "attemptStartedMonotonicMs": started * 1000,
        "attemptMs": ATTEMPT_MS,
        "finalizationMs": FINALIZE_MS,
        "workDeadlineMonotonicMs": started * 1000 + ATTEMPT_MS - FINALIZE_MS,
    }
    output = root / "test-results/ci-native-keyring-packages.json"
    with output.open("x") as stream:
        json.dump(receipt, stream, sort_keys=True)
    output.chmod(0o600)
