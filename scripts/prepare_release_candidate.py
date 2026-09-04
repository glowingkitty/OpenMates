#!/usr/bin/env python3
"""Prepare and attest the Docker-backed dev release candidate.

The script runs only on the dev host, keeps Docker access outside GitHub Actions,
and publishes a commit-scoped status consumed by release-core-journeys.yml.
It fails closed before publishing success if Git, Docker, or health checks drift.
See docs/specs/release-core-journeys-gate/spec.yml.
"""

from __future__ import annotations

import argparse
import importlib.util
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


def resolve_control_plane_root(checkout_root: Path) -> Path:
    """Resolve the main checkout that owns the registered dev runtime."""
    result = subprocess.run(
        ["git", "rev-parse", "--git-common-dir"],
        cwd=checkout_root,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return checkout_root
    common_dir = Path(result.stdout.strip())
    if not common_dir.is_absolute():
        common_dir = checkout_root / common_dir
    common_dir = common_dir.resolve()
    return common_dir.parent if common_dir.name == ".git" else checkout_root


PROJECT_ROOT = resolve_control_plane_root(Path(__file__).resolve().parent.parent)
PRODUCT_RUNTIME_CHECKOUT = PROJECT_ROOT.parent / ".openmates-runtime" / "product-stack"
CORE_SERVICES = (
    "api",
    "task-worker",
    "user-init-worker",
    "core-worker",
    "user-tasks-worker",
    "reminder-worker",
    "task-scheduler",
    "app-ai-worker",
)
BACKEND_RUNTIME_PATHS = ("backend", "shared", "frontend/packages/ui/src/i18n")
RELEASE_STATUS_CONTEXT = "Dev Release Candidate / Prepared"
API_HEALTH_URL = "https://api.dev.openmates.org/health"
DEV_API_URL = "https://api.dev.openmates.org"
HEALTH_TIMEOUT_SECONDS = 120
HEALTH_POLL_SECONDS = 5


class PreparationError(RuntimeError):
    """Raised when the dev backend cannot be safely attested."""


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


def run_command(command: Sequence[str], *, check: bool = True) -> CommandResult:
    """Run one command from the repository root without invoking a shell."""
    result = subprocess.run(
        list(command),
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    )
    command_result = CommandResult(result.returncode, result.stdout, result.stderr)
    if check and result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
        raise PreparationError(f"Command failed: {' '.join(command)}: {detail}")
    return command_result


def preflight_release_candidate(expected_commit: str = "") -> str:
    """Require a clean dev checkout aligned with origin/dev and the requested SHA."""
    branch = run_command(["git", "branch", "--show-current"]).stdout.strip()
    if branch != "dev":
        raise PreparationError(f"release candidate must be prepared from dev, got {branch or 'detached HEAD'}")

    dirty = run_command(
        ["git", "status", "--porcelain", "--", *BACKEND_RUNTIME_PATHS]
    ).stdout.strip()
    if dirty:
        raise PreparationError(
            "backend runtime paths are not clean; commit or remove scoped changes before preparation"
        )

    head = run_command(["git", "rev-parse", "HEAD"]).stdout.strip()
    remote = run_command(["git", "rev-parse", "origin/dev"]).stdout.strip()
    if head != remote:
        raise PreparationError(f"dev HEAD {head[:9]} does not match origin/dev {remote[:9]}")
    if expected_commit and head != expected_commit:
        raise PreparationError(f"expected commit {expected_commit}, dev HEAD is {head}")
    return head


def managed_setup_command(session: str) -> list[str]:
    return [
        sys.executable,
        "scripts/sessions.py",
        "docker",
        "run-setup",
        "--session",
        session,
        "--service",
        "cms-setup",
        "--build",
    ]


def managed_prepare_command(session: str) -> list[str]:
    command = [
        sys.executable,
        "scripts/sessions.py",
        "docker",
        "restart",
        "--session",
        session,
        "--build",
    ]
    for service in CORE_SERVICES:
        command.extend(["--service", service])
    return command


def verify_product_runtime_commit(commit: str) -> None:
    """Require coordinated Docker operations to use the attested dev commit."""
    result = run_command(
        ["git", "-C", str(PRODUCT_RUNTIME_CHECKOUT), "rev-parse", "HEAD"]
    )
    runtime_commit = result.stdout.strip()
    if runtime_commit != commit:
        raise PreparationError(
            f"product runtime {runtime_commit[:9]} does not match release commit {commit[:9]}"
        )


def github_status_command(
    commit: str,
    state: str,
    description: str,
    repository_url: str,
) -> list[str]:
    return [
        "gh",
        "api",
        "--method",
        "POST",
        f"repos/{{owner}}/{{repo}}/statuses/{commit}",
        "-f",
        f"state={state}",
        "-f",
        f"context={RELEASE_STATUS_CONTEXT}",
        "-f",
        f"description={description[:140]}",
        "-f",
        f"target_url={repository_url.rstrip('/')}/commit/{commit}",
    ]


def publish_status(commit: str, state: str, description: str) -> None:
    repository_url = run_command(
        ["gh", "repo", "view", "--json", "url", "--jq", ".url"]
    ).stdout.strip()
    if not repository_url:
        raise PreparationError("could not resolve the GitHub repository URL for status auditability")
    run_command(github_status_command(commit, state, description, repository_url))


def load_test_runner():
    """Load scripts/run_tests.py so this command reuses its canonical Vercel gate."""
    runner_path = PROJECT_ROOT / "scripts" / "run_tests.py"
    spec = importlib.util.spec_from_file_location("release_candidate_run_tests", runner_path)
    if spec is None or spec.loader is None:
        raise PreparationError(f"could not load Vercel deployment gate from {runner_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def wait_for_exact_vercel(commit: str) -> None:
    """Use the existing local Vercel gate to prove dev is Ready at the exact SHA."""
    module = load_test_runner()
    ready, reason = module._wait_for_vercel_deployment(commit, module._read_env_file())
    if not ready:
        raise PreparationError(reason or f"Vercel is not Ready for {commit}")


def containers_are_running() -> bool:
    for service in CORE_SERVICES:
        result = run_command(
            ["docker", "inspect", "--format={{.State.Running}}", service],
            check=False,
        )
        if result.returncode != 0 or result.stdout.strip() != "true":
            return False
    return True


def api_is_healthy() -> bool:
    request = urllib.request.Request(API_HEALTH_URL, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return int(getattr(response, "status", response.getcode())) < 500
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def wait_for_health() -> None:
    deadline = time.monotonic() + HEALTH_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if containers_are_running() and api_is_healthy():
            return
        time.sleep(HEALTH_POLL_SECONDS)
    raise PreparationError(
        f"core services did not become healthy within {HEALTH_TIMEOUT_SECONDS} seconds"
    )


def verify_cloud_overlay() -> None:
    """Fail attestation unless hosted dev billing routes and worker markers are active."""
    run_command(
        [
            sys.executable,
            "scripts/api_tests/test_cloud_overlay_boot.py",
            "--api-url",
            DEV_API_URL,
            "--cli-overlay",
            "--redact",
        ]
    )


def prepare_release_candidate(session: str, expected_commit: str = "") -> str:
    run_command(["git", "fetch", "origin", "dev"])
    commit = preflight_release_candidate(expected_commit)
    try:
        publish_status(commit, "pending", "Preparing exact frontend and core dev services")
        wait_for_exact_vercel(commit)
        preflight_release_candidate(commit)
        run_command(managed_setup_command(session))
        run_command(managed_prepare_command(session))
        verify_product_runtime_commit(commit)
        preflight_release_candidate(commit)
        wait_for_health()
        verify_cloud_overlay()
        publish_status(commit, "success", "Exact frontend and core dev services are healthy")
        return commit
    except Exception as exc:
        try:
            publish_status(commit, "failure", f"Backend preparation failed: {exc}")
        except Exception as status_exc:
            raise PreparationError(f"{exc}; failure status could not be published: {status_exc}") from exc
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare the dev backend for the core release gate")
    parser.add_argument("--session", required=True, help="Active sessions.py session ID used for the Docker lock")
    parser.add_argument("--expected-commit", default="", help="Optional full dev commit SHA that must be prepared")
    args = parser.parse_args()
    try:
        commit = prepare_release_candidate(args.session, args.expected_commit)
    except PreparationError as exc:
        print(f"Release candidate preparation failed: {exc}", file=sys.stderr)
        return 1
    print(f"Prepared and attested dev backend at {commit}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
