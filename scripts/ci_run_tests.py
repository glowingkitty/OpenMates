"""Run an isolated CI batch and retain source-bound, honest test outcomes.

The web server and API are on the GitHub VM. Account setup executes the real
CLI signup and key initialization flow against that API; temporary secrets stay
in a private directory excluded from artifacts. No shared account pool is read.
See docs/plans/isolated-github-tests/plan.yml.
"""

from __future__ import annotations

import json
import re
import ast
import hashlib
import os
from pathlib import Path
import secrets
import socket
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
# Real signup endpoint permits five email requests per minute per runner IP.
SIGNUP_INTERVAL_SECONDS = 15
_last_signup_started = None


def reject_inherited_accounts():
    """Cold jobs must provision identities, never inherit a shared account pool."""
    prefixes = ("TEST_ACCOUNT", "OPENMATES_TEST_ACCOUNT_", "E2E_SIGNUP_INVITE_CODE", "OPENMATES_CLI_SIGNUP_")
    if any(key.startswith(prefixes) for key in os.environ):
        raise RuntimeError("Inherited test credentials are forbidden; provision fresh runner accounts")


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


def reserved_account_slot(name: str) -> int:
    """Read the existing candidate account policy without importing its old runner."""
    tree = ast.parse((ROOT / "scripts/run_tests.py").read_text())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "RESERVED_PLAYWRIGHT_ACCOUNTS_BY_SPEC"
            for target in node.targets
        ):
            return int(ast.literal_eval(node.value).get(name, 1))
    raise RuntimeError("Candidate lacks reserved account policy; refusing shared-account fallback")


def provision_api_key(account: dict) -> str:
    """Issue an expiring key through the real SDK using the new CLI session."""
    require_runner()
    sdk = (ROOT / "frontend/packages/openmates-cli/dist/index.js").as_uri()
    program = """
const { OpenMatesClient, OpenMates } = await import(process.argv[1]);
const { platform, arch } = await import("node:os");
const client = new OpenMatesClient({apiUrl: process.argv[2]});
if (!client.hasSession()) throw new Error('Fresh CLI session is missing');
const FIXTURE_CREDIT_LIMIT = 1000;
const FIXTURE_KEY_LIFETIME_MS = 60 * 60 * 1000;
const result = await client.createApiKey({
  name: 'Disposable CI fixture', fullAccess: true,
  creditLimit: {period: 'lifetime', credits: FIXTURE_CREDIT_LIMIT},
  expiresAt: new Date(Date.now() + FIXTURE_KEY_LIFETIME_MS).toISOString()
});
// Register the actual CLI device with a read-only request, then approve only
// that device through its fresh owner's authenticated first-party session.
const deviceId = "cli:" + platform() + ":" + arch();
const api = new OpenMates({apiKey: result.api_key, apiUrl: process.argv[2], sdkName: "cli", deviceId});
try { await api.chats.list({limit: 1}); }
catch (error) { if (error.status !== 403) throw error; }
const devices = await client.settingsGet("api-key-devices");
const owned = devices.devices.filter(d => d.api_key_id === result.key.id && d.machine_identifier === deviceId);
if (owned.length !== 1) throw new Error("Fresh CLI device registration was not unique");
if (!owned[0].approved_at) await client.settingsPost("api-key-devices/" + owned[0].id + "/approve", {});
const verified = await client.settingsGet("api-key-devices");
if (!verified.devices.some(d => d.id === owned[0].id && d.approved_at)) throw new Error("Fresh CLI device approval failed");
await api.chats.list({limit: 1});
process.stdout.write(JSON.stringify({api_key: result.api_key}));
"""
    result = subprocess.run(
        ["node", "--input-type=module", "-e", program, sdk, API],
        env={**os.environ, "OPENMATES_STATE_DIR": account["OPENMATES_STATE_DIR"]},
        capture_output=True, text=True, timeout=60,
    )
    if result.returncode:
        raise RuntimeError("Fresh-account SDK API key issuance failed; no shared-key fallback")
    key = json.loads(result.stdout).get("api_key")
    if not isinstance(key, str) or not key.startswith("sk-api-"):
        raise RuntimeError("Fresh-account SDK returned no API key")
    return key


def pace_signup():
    """Respect the real shared-IP limit without disabling product rate limits."""
    global _last_signup_started
    now = time.monotonic()
    if _last_signup_started is not None:
        remaining = SIGNUP_INTERVAL_SECONDS - (now - _last_signup_started)
        if remaining > 0:
            time.sleep(remaining)
    _last_signup_started = time.monotonic()


def provision_account(slot: int, *, identity_index: int) -> dict:
    """Use real client crypto/auth; only receipt of the private email code is local."""
    pace_signup()
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
    email = profile["services"]["api"]["environment"][f"OPENMATES_TEST_ACCOUNT_CI_{identity_index}_EMAIL"]
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
                    # SvelteKit server routes are real; bind their client entries
                    # to immutable built bytes instead of expecting static SPA HTML.
                    assets = set(re.findall(r"_app/immutable/entry/[A-Za-z0-9_.-]+\.js", body.decode()))
                    if not assets:
                        raise RuntimeError("Frontend HTML lacks candidate entry assets")
                    asset_hashes = {}
                    for asset in sorted(assets):
                        built = WEB / "build" / asset
                        with urllib.request.urlopen(APP + "/" + asset, timeout=5) as asset_response:
                            data = asset_response.read()
                        if not built.is_file() or data != built.read_bytes():
                            raise RuntimeError("Served frontend entry differs from candidate build")
                        asset_hashes[asset] = hashlib.sha256(data).hexdigest()
                    evidence_path = RESULTS / "ci-environment.json"
                    evidence = json.loads(evidence_path.read_text())
                    evidence["frontend"] = {
                        "url": APP,
                        "source_commit": evidence["source_commit"],
                        "renderer": "sveltekit-preview",
                        "entry_asset_sha256": asset_hashes,
                        "served_index_sha256": hashlib.sha256(body).hexdigest(),
                    }
                    evidence_path.write_text(json.dumps(evidence, indent=2))
                    return
        except OSError:
            pass
        time.sleep(1)
    raise RuntimeError("Local web app did not become ready")


def verify_artifact_profile(specs: list[str]):
    from ci_coverage import ARTIFACT_SPECS
    if not specs or not set(specs).issubset(ARTIFACT_SPECS):
        raise ValueError("Artifact-only mode cannot run application specs")
    for host in ("api.dev.openmates.org", "app.dev.openmates.org"):
        if set(socket.gethostbyname_ex(host)[2]) != {"127.0.0.2"}:
            raise RuntimeError("Shared-dev DNS was not rejected for artifact proof")
        try:
            connection = socket.create_connection((host, 443), timeout=2)
        except OSError:
            continue
        connection.close()
        raise RuntimeError("Shared-dev HTTPS reachable during artifact proof")


def run_e2e(specs: list[str], *, artifact=False, results=None):
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
    if artifact:
        verify_artifact_profile(specs)
    if results is None:
        results = []
    with (RESULTS / "ci-web.log").open("w") as log:
        app_server = None if artifact else subprocess.Popen(
            ["pnpm", "exec", "vite", "preview", "--host", "127.0.0.1", "--port", "5174", "--strictPort"],
            cwd=WEB, stdout=log, stderr=log,
        )
        child = None if artifact else subprocess.Popen(
            [
                sys.executable,
                str(Path(__file__).with_name("ci_static_web.py")),
                str(WEB / "build"),
                "--sveltekit",
            ],
            cwd=WEB,
            stdout=log,
            stderr=log,
        )
        try:
            if child is not None:
                wait_web(child)
            for index, name in enumerate(specs):
                source = (WEB / "tests" / name).read_text()
                env = {**os.environ, "PLAYWRIGHT_TEST_API_URL": API}
                account_free = artifact or (
                    "// playwright-account: not_required reason=isolated_component_preview"
                    in source
                )
                if not account_free:
                    primary = provision_account(14, identity_index=2 * index)
                    if "OPENMATES_TEST_ACCOUNT_API_KEY" in source:
                        primary["OPENMATES_TEST_ACCOUNT_API_KEY"] = provision_api_key(primary)
                    secondary = provision_account(15, identity_index=2 * index + 1)
                    env.update(primary)
                    env["PLAYWRIGHT_WORKER_SLOT"] = "1"
                    env["OPENMATES_TEST_ACCOUNT_SOURCE_SLOT"] = str(reserved_account_slot(name))
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
                account_evidence = {"legacy_credentials_absent": True, "provisioning": "none" if account_free else "real-cli-signup-crypto-totp", "identity_hashes": []}
                if not account_free:
                    identities = [hashlib.sha256(item["OPENMATES_TEST_ACCOUNT_EMAIL"].encode()).hexdigest() for item in (primary, secondary)]
                    if len(set(identities)) != 2:
                        raise RuntimeError("Isolated batch received duplicate account identities")
                    account_evidence["identity_hashes"] = identities
                    account_evidence["api_key_provisioned"] = "OPENMATES_TEST_ACCOUNT_API_KEY" in primary
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
                        "accounts": account_evidence,
                        "exit_code": result.returncode if executed and not stats.get("skipped", 0) else 1,
                        "coverage_complete": bool(executed) and not stats.get("skipped", 0),
                        "stats": stats,
                        "error": ("Selected cases were skipped; coverage is incomplete" if stats.get("skipped", 0)
                                  else None if executed else "No tests executed; skipped coverage is not a pass"),
                    }
                )
        finally:
            for process in (child, app_server):
                if process is not None:
                    process.terminate()
                    try:
                        process.wait(timeout=15)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
    return results


def main():
    require_runner()
    RESULTS.mkdir(exist_ok=True)
    mode = os.environ["CI_TEST_MODE"]
    results = []
    error = None
    try:
        if mode in ("e2e", "artifact"):
            reject_inherited_accounts()
            results = run_e2e(json.loads(os.environ["CI_SPECS_JSON"]), artifact=mode == "artifact", results=results)
        elif mode == "selfhost":
            reject_inherited_accounts()
            from ci_selfhost import run
            run(ROOT, results)
        elif mode == "codex":
            result = subprocess.run(["node", str(Path(__file__).with_name("ci_codex_fixture.mjs")), "verify"], cwd=ROOT)
            receipt = json.loads((RESULTS / "ci-codex.json").read_text())
            if receipt.get("inference_requested") is not False or receipt.get("status") != "ready":
                raise RuntimeError("Codex metadata fixture lacks no-inference evidence")
            results.append({"suite": "codex-metadata", "exit_code": result.returncode, "thread_id": receipt["thread_id"], "inference_requested": False})
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
        "runtime_profile": mode,
        "artifact_shared_dev_rejected": mode == "artifact" and not error,
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
