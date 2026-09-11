"""Run the existing installer smoke contract inside the bounded GitHub queue.

The candidate workflow remains the source of installer commands and assertions.
This adapter supplies the Actions setup context already installed by our harness,
executes its shell steps, and returns honest source-bound results and cleanup.
It never starts a stack outside a GitHub-hosted runner or reads operator state.
See docs/architecture/isolated-github-tests.md.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import urllib.request

from ci_environment import require_runner

EXPRESSION = re.compile(r"\$\{\{\s*([^}]+?)\s*\}\}")
EXPECTED_SETUP_ACTIONS = {"actions/checkout@v4", "actions/setup-node@v4", "pnpm/action-setup@v4", "actions/upload-artifact@v4"}
INSTALL_PATHS = ("/tmp/openmates-selfhost-source", "/tmp/openmates-selfhost-image")


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


def capture_environment(source: Path, commit: str, workflow_hash: str, destination: Path):
    check_egress()
    services = {}
    for name in ("api", "webapp", "cms"):
        info = json.loads(subprocess.check_output(["docker", "inspect", name], text=True))[0]
        if not info["State"]["Running"]:
            raise RuntimeError("Installer service stopped: " + name)
        configured_image = info["Config"]["Image"]
        if not configured_image.endswith(":selfhost-smoke-" + commit):
            raise RuntimeError("Installed image is not the current source build: " + name)
        services[name] = {"image": info["Image"], "tag": configured_image}
    for url in ("http://localhost:8000/health", "http://localhost:5173"):
        with urllib.request.urlopen(url, timeout=15) as response:
            if response.status != 200:
                raise RuntimeError("Installed runner endpoint is not healthy")
    destination.write_text(json.dumps({
        "source_commit": commit, "harness_commit": os.environ.get("CI_HARNESS_COMMIT"),
        "runner_environment": "github-hosted", "runtime_profile": "selfhost-installer",
        "shared_dev_dns": "rejected", "shared_dev_https": "rejected",
        "workflow_sha256": workflow_hash, "services": services,
        "frontend": {"source_commit": commit, "url": "http://localhost:5173", "renderer": "installed-image"},
        "api_url": "http://localhost:8000", "source_context": str(source),
    }, indent=2))


def run(source: Path, results: list):
    require_runner()
    check_egress()
    import yaml

    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=source, text=True).strip()
    workflow_path = source / ".github/workflows/selfhost-smoke.yml"
    workflow_bytes = workflow_path.read_bytes()
    workflow = yaml.safe_load(workflow_bytes)["jobs"]["install-smoke"]
    if workflow["runs-on"] != "ubuntu-latest":
        raise RuntimeError("Installer contract must use GitHub-hosted Ubuntu")
    output = source / "test-results"
    private = output / "ci-private"
    private.mkdir(parents=True, exist_ok=True, mode=0o700)
    env = {**os.environ, "GITHUB_WORKSPACE": str(source), "GITHUB_SHA": commit}
    for key, value in workflow.get("env", {}).items():
        env[key] = expand(value, env, source, commit)
    if tuple(env[key] for key in ("SOURCE_INSTALL_PATH", "IMAGE_INSTALL_PATH")) != INSTALL_PATHS:
        raise RuntimeError("Installer paths changed; review the cleanup contract")
    steps = []
    failed = False
    try:
        for step in workflow["steps"]:
            if "uses" in step:
                if step["uses"] not in EXPECTED_SETUP_ACTIONS:
                    raise RuntimeError("New installer setup action needs harness support")
                continue
            if step.get("if") not in (None, "always()"):
                raise RuntimeError("Unsupported conditional installer step")
            if failed and step.get("if") != "always()":
                continue
            name = step.get("name", "unnamed")
            step_env = dict(env)
            for key, value in step.get("env", {}).items():
                step_env[key] = expand(value, step_env, source, commit)
            cwd = (source / step.get("working-directory", ".")).resolve()
            if not cwd.is_relative_to(source.resolve()):
                raise RuntimeError("Installer working directory escaped source")
            command = expand(step["run"], step_env, source, commit)
            with (private / "installer.log").open("a") as log:
                result = subprocess.run(["bash", "-eo", "pipefail", "-c", command], cwd=cwd, env=step_env,
                                        stdout=log, stderr=subprocess.STDOUT, timeout=3000)
            steps.append({"step": name, "exit_code": result.returncode})
            print(json.dumps(steps[-1]), flush=True)
            failed = failed or result.returncode != 0
            if name == "Check backend and web Docker containers" and not failed:
                capture_environment(source, commit, hashlib.sha256(workflow_bytes).hexdigest(), output / "ci-environment.json")
    finally:
        # The original always() cleanup may mask errors; verify the actual result.
        # Retry cleanup through the supported CLI if an earlier step raised.
        cli = source / "frontend/packages/openmates-cli/dist/cli.js"
        cleanup_failures = []
        for install in INSTALL_PATHS:
            if Path(install).exists():
                with (private / "cleanup.log").open("a") as log:
                    result = subprocess.run(["node", str(cli), "server", "uninstall", "--path", install, "--yes"],
                                            cwd=source, env=env, stdout=log, stderr=subprocess.STDOUT, timeout=180)
                if result.returncode:
                    cleanup_failures.append(install)
        for kind, command in (("containers", ["docker", "ps", "-aq"]), ("volumes", ["docker", "volume", "ls", "-q"])):
            remaining = subprocess.check_output([*command, "--filter", "label=com.docker.compose.project"], text=True).strip()
            if remaining:
                cleanup_failures.append(kind)
        shutil.rmtree(private)
        (output / "ci-cleanup.json").write_text(json.dumps({"run_id": os.environ["GITHUB_RUN_ID"],
            "harness_commit": os.environ.get("CI_HARNESS_COMMIT"),
            "containers_remaining": 0 if "containers" not in cleanup_failures else "nonzero",
            "volumes_remaining": 0 if "volumes" not in cleanup_failures else "nonzero",
            "private_account_files_removed": True, "errors": cleanup_failures}))
        (output / "ci-selfhost-steps.json").write_text(json.dumps(steps, indent=2))
        if cleanup_failures:
            raise RuntimeError("Installer cleanup incomplete: " + ", ".join(cleanup_failures))
    report = output / "selfhost-smoke-playwright.json"
    stats = json.loads(report.read_text()).get("stats", {}) if report.is_file() else {}
    if report.is_file():
        shutil.copyfile(report, output / "ci-spec-selfhost.json")
    complete = bool(stats.get("expected", 0) + stats.get("unexpected", 0)) and not stats.get("skipped", 0)
    results.append({"spec": "selfhost-smoke.spec.ts", "stats": stats, "coverage_complete": complete,
                    "exit_code": int(failed or not complete or bool(stats.get("unexpected", 0)))})
