"""Run an isolated CI batch and retain source-bound, honest test outcomes.

The web server and API are on the GitHub VM. Account setup executes the real
CLI signup and key initialization flow against that API; temporary secrets stay
in a private directory excluded from artifacts. No shared account pool is read.
See docs/plans/isolated-github-tests/plan.yml.
"""

from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time
import urllib.request

from ci_environment import COMPOSE_PATH, SOURCE, compose, require_runner

ROOT = Path(SOURCE)
WEB = ROOT / "frontend/apps/web_app"
RESULTS = ROOT / "test-results"
API = "http://localhost:8000"
APP = "http://localhost:5173"


def request(url, data=None, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(
        url,
        data=json.dumps(data).encode() if data is not None else None,
        headers=headers,
    )
    with urllib.request.urlopen(req, timeout=20) as response:
        return json.load(response)


def cms_admin_token(profile: dict) -> str:
    """Authenticate fixture writes using this runner's generated CMS identity."""
    environment = profile["services"]["api"]["environment"]
    response = request(
        "http://localhost:8055/auth/login",
        {
            "email": environment["DATABASE_ADMIN_EMAIL"],
            "password": environment["DATABASE_ADMIN_PASSWORD"],
            "mode": "json",
        },
    )
    token = response.get("data", {}).get("access_token")
    if not isinstance(token, str) or not token:
        raise RuntimeError("Runner-local CMS did not issue an admin access token")
    identity = request("http://localhost:8055/users/me", token=token)
    if identity.get("data", {}).get("email") != environment["DATABASE_ADMIN_EMAIL"]:
        raise RuntimeError("Runner-local CMS fixture identity mismatch")
    return token


def provision_account(slot: int) -> dict:
    """Use real client crypto/auth; only receipt of the private email code is local."""
    profile = json.loads(COMPOSE_PATH.read_text())
    token = cms_admin_token(profile)
    invite = secrets.token_hex(9)
    request(
        "http://localhost:8055/items/invite_codes",
        {"code": invite, "remaining_uses": 1, "is_admin": False},
        token,
    )
    private = COMPOSE_PATH.parent
    artifact = private / f"account-{slot}-{secrets.token_hex(4)}.env"
    email = f"ci-{secrets.token_hex(8)}@example.com"
    env = {
        **os.environ,
        "OPENMATES_CLI_SIGNUP_INVITE_CODE": invite,
        "NO_COLOR": "1",
        "OPENMATES_STATE_DIR": str(private / f"state-{slot}-{secrets.token_hex(8)}"),
    }
    command = [
        "node",
        str(ROOT / "frontend/packages/openmates-cli/dist/cli.js"),
        "--api-url",
        API,
        "e2e",
        "provision-auth-accounts",
        "--slot",
        str(slot),
        "--artifact",
        str(artifact),
        "--email",
        email,
        "--username",
        "ci" + secrets.token_hex(8),
        "--force",
    ]
    # Keep signup secrets and security setup output out of public workflow logs.
    with (private / f"provision-{slot}.log").open("w") as log:
        child = subprocess.Popen(
            command,
            cwd=ROOT,
            env=env,
            stdin=subprocess.PIPE,
            stdout=log,
            stderr=log,
            text=True,
        )
        try:
            deadline = time.monotonic() + 120
            while time.monotonic() < deadline:
                if child.poll() is not None:
                    raise RuntimeError(
                        f"Account provisioning exited early ({child.returncode}); private diagnostics retained until runner teardown"
                    )
                password = profile["services"]["cache"]["command"][2]
                # The real email worker generated this code. Reading only this new
                # account key avoids an external inbox dependency in fixture setup.
                result = compose(
                    "exec",
                    "-T",
                    "-e",
                    "REDISCLI_AUTH=" + password,
                    "cache",
                    "redis-cli",
                    "--raw",
                    "GET",
                    "email_verification:" + email,
                    capture=True,
                )
                value = result.stdout.strip().strip('"')
                if len(value) == 6 and value.isdigit():
                    child.stdin.write(value + "\n")
                    child.stdin.flush()
                    break
                time.sleep(2)
            else:
                raise RuntimeError("Private signup email code was not generated")
            if child.wait(timeout=120):
                raise RuntimeError("Real CLI signup/security initialization failed")
        finally:
            if child.poll() is None:
                child.kill()
                child.wait()
    values = dict(
        line.split("=", 1)
        for line in artifact.read_text().splitlines()
        if line and not line.startswith("#")
    )
    prefix = f"OPENMATES_TEST_ACCOUNT_{slot}_"
    mapped = {
        key.replace(prefix, "OPENMATES_TEST_ACCOUNT_"): value
        for key, value in values.items()
    }
    fixture_invite = secrets.token_hex(9)
    request(
        "http://localhost:8055/items/invite_codes",
        {"code": fixture_invite, "remaining_uses": 20, "is_admin": False},
        token,
    )
    mapped["E2E_SIGNUP_INVITE_CODE"] = fixture_invite
    mapped["OPENMATES_CLI_SIGNUP_INVITE_CODE"] = fixture_invite
    mapped["OPENMATES_STATE_DIR"] = env["OPENMATES_STATE_DIR"]
    return mapped


def wait_web(child):
    for _ in range(60):
        if child.poll() is not None:
            raise RuntimeError("Local web server exited before readiness")
        try:
            with urllib.request.urlopen(APP, timeout=2) as response:
                if response.status == 200:
                    body = response.read()
                    built = WEB / "build/index.html"
                    if body != built.read_bytes():
                        raise RuntimeError(
                            "Served frontend differs from the candidate build"
                        )
                    evidence_path = RESULTS / "ci-environment.json"
                    evidence = json.loads(evidence_path.read_text())
                    evidence["frontend"] = {
                        "url": APP,
                        "source_commit": evidence["source_commit"],
                        "served_index_sha256": hashlib.sha256(body).hexdigest(),
                    }
                    evidence_path.write_text(json.dumps(evidence, indent=2))
                    return
        except OSError:
            pass
        time.sleep(1)
    raise RuntimeError("Local web app did not become ready")


def run_e2e(specs: list[str]):
    if not specs:
        raise ValueError("An explicit nonempty spec batch is required")
    for name in specs:
        path = (WEB / "tests" / name).resolve()
        if (
            not path.is_relative_to(WEB / "tests")
            or not path.is_file()
            or not name.endswith(".spec.ts")
        ):
            raise ValueError("Invalid spec selection")
    results = []
    with (RESULTS / "ci-web.log").open("w") as log:
        child = subprocess.Popen(
            [
                "pnpm",
                "exec",
                "vite",
                "preview",
                "--host",
                "127.0.0.1",
                "--port",
                "5173",
                "--strictPort",
            ],
            cwd=WEB,
            stdout=log,
            stderr=log,
        )
        try:
            wait_web(child)
            for index, name in enumerate(specs):
                source = (WEB / "tests" / name).read_text()
                env = dict(os.environ)
                account_free = (
                    "// playwright-account: not_required reason=isolated_component_preview"
                    in source
                )
                if not account_free:
                    primary = provision_account(14)
                    secondary = provision_account(15)
                    env.update(primary)
                    env.update(
                        {
                            k.replace(
                                "OPENMATES_TEST_ACCOUNT_", "OPENMATES_TEST_ACCOUNT_1_"
                            ): v
                            for k, v in primary.items()
                            if k.startswith("OPENMATES_TEST_ACCOUNT_")
                        }
                    )
                    env.update(
                        {
                            k.replace(
                                "OPENMATES_TEST_ACCOUNT_", "OPENMATES_TEST_ACCOUNT_2_"
                            ): v
                            for k, v in secondary.items()
                            if k.startswith("OPENMATES_TEST_ACCOUNT_")
                        }
                    )
                env["PLAYWRIGHT_JSON_OUTPUT_NAME"] = str(
                    RESULTS / f"ci-spec-{index}.json"
                )
                result = subprocess.run(
                    [
                        "pnpm",
                        "exec",
                        "playwright",
                        "test",
                        "tests/" + name,
                        "--workers=1",
                        "--reporter=json",
                        "--output",
                        f"test-results/ci-{index}",
                    ],
                    cwd=WEB,
                    env=env,
                    timeout=1200,
                )
                report_path = RESULTS / f"ci-spec-{index}.json"
                report = (
                    json.loads(report_path.read_text()) if report_path.is_file() else {}
                )
                stats = report.get("stats", {})
                executed = (
                    int(stats.get("expected", 0))
                    + int(stats.get("unexpected", 0))
                    + int(stats.get("flaky", 0))
                )
                results.append(
                    {
                        "spec": name,
                        "exit_code": result.returncode if executed else 1,
                        "stats": stats,
                        "error": None
                        if executed
                        else "No tests executed; skipped coverage is not a pass",
                    }
                )
        finally:
            child.terminate()
            try:
                child.wait(timeout=15)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
    return results


def main():
    require_runner()
    RESULTS.mkdir(exist_ok=True)
    mode = os.environ["CI_TEST_MODE"]
    results = []
    error = None
    try:
        if mode == "e2e":
            results = run_e2e(json.loads(os.environ["CI_SPECS_JSON"]))
        elif mode == "pytest":
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pip",
                    "install",
                    "-r",
                    "backend/requirements-dev.txt",
                    "-r",
                    "backend/core/api/requirements.txt",
                    "-e",
                    "packages/openmates-python",
                ],
                cwd=ROOT,
                check=True,
            )
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    "backend/tests",
                    "-m",
                    "not integration and not slow and not vault and not benchmark and not provider_contract",
                    "--json-report",
                    "--json-report-file=test-results/ci-pytest.json",
                    "--ignore=backend/tests/fixtures",
                    "--ignore=backend/tests/provider_contracts",
                    "--ignore=backend/tests/test_encryption_service.py",
                    "--ignore=backend/tests/test_integration_encryption.py",
                    "--ignore=backend/tests/test_status_service_v2.py",
                    "--continue-on-collection-errors",
                ],
                cwd=ROOT,
            )
            results = [{"suite": mode, "exit_code": result.returncode}]
            # Preserve the SDK account coverage in the existing daily unit workflow.
            sdk = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    "packages/openmates-python/tests/test_account_import.py",
                    "packages/openmates-python/tests/test_account_export.py",
                    "--json-report",
                    "--json-report-file=test-results/ci-unit-sdk.json",
                ],
                cwd=ROOT,
            )
            results.append(
                {"suite": "python-sdk-accounts", "exit_code": sdk.returncode}
            )
        elif mode == "vitest":
            subprocess.run(["pnpm", "exec", "svelte-kit", "sync"], cwd=WEB, check=True)
            for directory in [ROOT / "frontend/packages/ui", WEB]:
                result = subprocess.run(
                    [
                        "pnpm",
                        "exec",
                        "vitest",
                        "run",
                        "--reporter=json",
                        "--outputFile="
                        + str(RESULTS / f"ci-unit-{directory.name}.json"),
                    ],
                    cwd=directory,
                    timeout=300,
                )
                results.append(
                    {
                        "suite": str(directory.relative_to(ROOT)),
                        "exit_code": result.returncode,
                    }
                )
            cli = ROOT / "frontend/packages/openmates-cli"
            with (RESULTS / "ci-unit-cli.log").open("w") as output:
                result = subprocess.run(
                    [
                        "node",
                        "--test",
                        "--experimental-strip-types",
                        "--loader",
                        "./tests/loader.mjs",
                        "tests/account-import.test.ts",
                        "tests/account-import-sdk.test.ts",
                    ],
                    cwd=cli,
                    stdout=output,
                    stderr=subprocess.STDOUT,
                    timeout=300,
                )
            results.append({"suite": "cli-accounts", "exit_code": result.returncode})
        else:
            raise ValueError("Unknown test mode")
    except Exception as exc:
        error = str(exc)
    payload = {
        "source_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "run_id": os.environ["GITHUB_RUN_ID"],
        "environment": "github-isolated",
        "harness_commit": os.environ.get("CI_HARNESS_COMMIT"),
        "proof_profile": os.environ.get("PLAYWRIGHT_PROOF_VIDEO_PROFILE", ""),
        "results": results,
        "error": error,
        "success": bool(results)
        and not error
        and all(r["exit_code"] == 0 for r in results),
    }
    (RESULTS / "ci-results.json").write_text(json.dumps(payload, indent=2))
    if error:
        print(error, file=sys.stderr)
    return 0 if payload["success"] else 1


if __name__ == "__main__":
    sys.exit(main())
