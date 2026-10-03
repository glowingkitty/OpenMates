"""Run an isolated CI batch and retain source-bound, honest test outcomes.

The web server and API are on the GitHub VM. Account setup executes the real
CLI signup and key initialization flow against that API; temporary secrets stay
in a private directory excluded from artifacts. No shared account pool is read.
See docs/plans/isolated-github-tests/plan.yml.
"""

from __future__ import annotations

import json
import base64
import hmac
import re
import ast
import hashlib
import os
from pathlib import Path
import secrets
import socket
import struct
import subprocess
import sys
import time
import urllib.request

from ci_environment import COMPOSE_PATH, SOURCE, compose, require_runner
try:
    from scripts.ci_pytest_targets import validate_pytest_targets
except ModuleNotFoundError:
    from ci_pytest_targets import validate_pytest_targets

ROOT = Path(SOURCE)
WEB = ROOT / "frontend/apps/web_app"
RESULTS = ROOT / "test-results"
API = "http://localhost:8000"
APP = "http://localhost:5173"
# Real signup endpoint permits five email requests per minute per runner IP.
SIGNUP_INTERVAL_SECONDS = 15
FIXTURE_CREDITS = 1000
_last_signup_started = None
CAPACITY_EPOCH_SPECS = frozenset({
    "storage-capacity-replay.spec.ts",
    "storage-capacity-target.spec.ts",
    "storage-recovery-replay.spec.ts",
})

VITEST_TARGET_ROOTS = {
    "ui": ("frontend", "packages", "ui", "src"),
    "web_app": ("frontend", "apps", "web_app", "src"),
    "openmates-cli": ("frontend", "packages", "openmates-cli", "tests"),
}


def validate_vitest_targets(raw: object, *, root: Path = ROOT) -> dict[str, list[str]]:
    """Admit existing exact unit files in the three trusted frontend packages."""
    if not isinstance(raw, list) or len(raw) > 30:
        raise ValueError("Vitest selection must be a bounded list of exact test paths")
    selected: dict[str, list[str]] = {name: [] for name in VITEST_TARGET_ROOTS}
    for target in raw:
        if not isinstance(target, str) or not target or "\\" in target:
            raise ValueError("Vitest selection contains an invalid test path")
        path = Path(target)
        if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
            raise ValueError("Vitest selection contains path traversal")
        group = next((name for name, prefix in VITEST_TARGET_ROOTS.items()
                      if path.parts[:len(prefix)] == prefix and len(path.parts) > len(prefix)), None)
        if group is None or not re.fullmatch(r"[A-Za-z0-9_.-]+\.test\.tsx?", path.name):
            raise ValueError("Vitest selection contains an unsupported test kind")
        if group == "openmates-cli" and not path.name.endswith(".test.ts"):
            raise ValueError("Vitest selection contains an unsupported test kind")
        candidate = root / path
        if not candidate.is_file() or not candidate.resolve().is_relative_to(root.resolve()):
            raise ValueError("Vitest selection must name an existing repository test file")
        if target not in selected[group]:
            selected[group].append(target)
    return selected


def run_selected_vitest(selection: dict[str, list[str]]) -> list[dict]:
    """Run selected UI/web Vitest files and CLI node:test files in package cwd."""
    results: list[dict] = []
    if selection["ui"] or selection["web_app"]:
        subprocess.run(["pnpm", "exec", "svelte-kit", "sync"], cwd=WEB, check=True)
    for group, directory in (("ui", ROOT / "frontend/packages/ui"), ("web_app", WEB)):
        targets = selection[group]
        if not targets:
            continue
        relative = [str(Path(target).relative_to(directory.relative_to(ROOT))) for target in targets]
        result = subprocess.run(
            ["pnpm", "exec", "vitest", "run", *relative, "--reporter=json",
             "--outputFile=" + str(RESULTS / f"ci-unit-{group}.json")],
            cwd=directory, timeout=300,
        )
        results.append({"suite": str(directory.relative_to(ROOT)), "exit_code": result.returncode,
                        "selected_tests": targets, "selection_mode": "focused"})
    if selection["openmates-cli"]:
        cli = ROOT / "frontend/packages/openmates-cli"
        relative = [str(Path(target).relative_to(cli.relative_to(ROOT)))
                    for target in selection["openmates-cli"]]
        # The provisioning contract invokes dist/cli.js as a subprocess. Build
        # only the selected CLI package before its node:test files run.
        subprocess.run(["pnpm", "run", "build"], cwd=cli, check=True, timeout=300)
        with (RESULTS / "ci-unit-cli-selected.log").open("w") as output:
            result = subprocess.run(
                ["node", "--test", "--experimental-strip-types", "--loader", "./tests/loader.mjs",
                 *relative], cwd=cli, stdout=output, stderr=subprocess.STDOUT, timeout=300,
            )
        results.append({"suite": "cli-selected", "exit_code": result.returncode,
                        "selected_tests": selection["openmates-cli"], "selection_mode": "focused"})
    return results



def configure_proof_dimensions():
    """Use canonical full-frame dimensions, never legacy browser-chrome insets.

    Read only literal dimensions from the trusted harness profile definitions;
    importing the media tool would require unrelated rendering dependencies.
    Playwright uses these same values for viewport and recording size.
    """
    profile = os.environ.get("PLAYWRIGHT_PROOF_VIDEO_PROFILE", "")
    if not profile:
        return None
    if profile not in ("web-phone", "web-laptop"):
        raise ValueError("Unsupported isolated proof profile")
    tree = ast.parse(Path(__file__).with_name("spec_demo.py").read_text())
    assignment = next(
        node for node in tree.body if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "DEVICE_PROFILES" for target in node.targets)
    )
    definition = next(value for key, value in zip(assignment.value.keys, assignment.value.values)
                      if ast.literal_eval(key) == profile)
    dimensions = {ast.literal_eval(key): ast.literal_eval(value)
                  for key, value in zip(definition.keys, definition.values)
                  if ast.literal_eval(key) in ("width", "height")}
    if set(dimensions) != {"width", "height"} or any(type(value) is not int or value <= 0 for value in dimensions.values()):
        raise ValueError("Invalid canonical proof dimensions")
    for axis, value in dimensions.items():
        os.environ[f"PLAYWRIGHT_VIDEO_{axis.upper()}"] = str(value)
    return dimensions


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
    # Signup just enrolled this authenticator. Wait for a fresh time step so
    # the account-wide one-use TOTP guard cannot mistake setup for a replay.
    time.sleep(30 - (time.time() % 30) + 1)
    totp_code = generate_ci_totp(account["OPENMATES_TEST_ACCOUNT_OTP_KEY"])
    sdk = (ROOT / "frontend/packages/openmates-cli/dist/index.js").as_uri()
    program = """
const { OpenMatesClient, OpenMates } = await import(process.argv[1]);
const { platform, arch } = await import("node:os");
const client = new OpenMatesClient({apiUrl: process.argv[2]});
if (!client.hasSession()) throw new Error('Fresh CLI session is missing');
await client.verifyTotpForCurrentSession(process.env.OPENMATES_CI_SENSITIVE_TOTP_CODE);
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
        env={**os.environ, "OPENMATES_STATE_DIR": account["OPENMATES_STATE_DIR"],
             "OPENMATES_CI_SENSITIVE_TOTP_CODE": totp_code},
        capture_output=True, text=True, timeout=60,
    )
    if result.returncode:
        raise RuntimeError("Fresh-account SDK API key issuance failed; no shared-key fallback")
    key = json.loads(result.stdout).get("api_key")
    if not isinstance(key, str) or not key.startswith("sk-api-"):
        raise RuntimeError("Fresh-account SDK returned no API key")
    return key


def generate_ci_totp(secret: str, *, timestamp: float | None = None) -> str:
    """RFC 6238 SHA-1 code for the disposable account's enrolled authenticator."""
    normalized = secret.strip().upper().replace(" ", "")
    key = base64.b32decode(normalized + "=" * ((-len(normalized)) % 8), casefold=True)
    counter = int(time.time() if timestamp is None else timestamp) // 30
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return f"{value % 1_000_000:06d}"


def accept_fixture_credits(account: dict) -> int:
    """Accept the new invite gift through genuine first-party authentication.

    Credits exist only in the disposable database. They enable original chat
    controls while provider credentials and outbound replay restrictions remain
    unchanged. Never patch encrypted balances or bypass the product gift flow.
    """
    require_runner()
    sdk = (ROOT / "frontend/packages/openmates-cli/dist/index.js").as_uri()
    program = """
const { OpenMatesClient } = await import(process.argv[1]);
const client = new OpenMatesClient({apiUrl: process.argv[2]});
if (!client.hasSession()) throw new Error('Fresh CLI session is missing');
// The first authenticated request may refresh and retire the signup cookie.
// Use the SDK's session endpoint so any replacement is saved before raw fetch.
await client.whoAmI();
const cookie = Object.entries(client.getSession().cookies).map(([k,v]) => k + '=' + v).join('; ');
const response = await fetch(process.argv[2] + '/v1/auth/accept-gift', {
  method: 'POST', headers: {Cookie: cookie, Origin: 'http://localhost:5173'}
});
if (!response.ok) throw new Error('Fresh signup gift acceptance failed: ' + response.status);
const result = await response.json();
if (result.success !== true || result.current_credits !== Number(process.argv[3]))
  throw new Error('Fresh signup credit balance differs from the bounded fixture');
process.stdout.write(JSON.stringify({credits: result.current_credits}));
"""
    result = subprocess.run(
        ["node", "--input-type=module", "-e", program, sdk, API, str(FIXTURE_CREDITS)],
        env={**os.environ, "OPENMATES_STATE_DIR": account["OPENMATES_STATE_DIR"]},
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode:
        raise RuntimeError("Fresh-account signup gift acceptance failed; no balance bypass")
    credits = json.loads(result.stdout).get("credits")
    if credits != FIXTURE_CREDITS:
        raise RuntimeError("Fresh-account credit fixture balance mismatch")
    return credits


def provision_shared_archive(account: dict) -> str:
    """Seed synthetic encrypted archive rows, then share via the genuine client."""
    require_runner()
    result = subprocess.run(
        ["node", "--experimental-strip-types", str(Path(__file__).with_name("ci_shared_chat_fixture.mjs")), str(ROOT)],
        env={**os.environ, "OPENMATES_STATE_DIR": account["OPENMATES_STATE_DIR"],
             "OPENMATES_CI_FIXTURE_CMS_TOKEN": cms_admin_token(json.loads(COMPOSE_PATH.read_text()))},
        capture_output=True, text=True, timeout=120,
    )
    if result.returncode:
        raise RuntimeError("Fresh encrypted shared archive provisioning failed; no historical shared-dev fallback")
    url = json.loads(result.stdout).get("url", "")
    if not url.startswith(APP + "/share/chat/") or "#key=" not in url:
        raise RuntimeError("Shared archive fixture returned a non-local or unencrypted URL")
    return url


def provision_startup_sync_chats(account: dict) -> None:
    """Seed disposable encrypted history before a startup browser sync begins."""
    require_runner()
    result = subprocess.run(
        ["node", "--experimental-strip-types", str(Path(__file__).with_name("ci_startup_sync_fixture.mjs")), str(ROOT)],
        env={**os.environ, "OPENMATES_STATE_DIR": account["OPENMATES_STATE_DIR"],
             "OPENMATES_CI_FIXTURE_CMS_TOKEN": cms_admin_token(json.loads(COMPOSE_PATH.read_text()))},
        capture_output=True, text=True, timeout=180,
    )
    if result.returncode:
        raise RuntimeError("Fresh encrypted startup chat provisioning failed; no shared-account fallback")
    summary = json.loads(result.stdout)
    if summary.get("chats") != 22 or summary.get("messages") != 32:
        raise RuntimeError("Encrypted startup chat fixture has the wrong bounded shape")


def activate_isolated_recovery_epoch() -> dict:
    """Activate v1 only inside the disposable signed recovery replay stack."""
    require_runner()
    profile = json.loads(COMPOSE_PATH.read_text())
    api_env = profile["services"]["api"]["environment"]
    expected = {
        "OPENMATES_CI_ISOLATED": "1",
        "OPENMATES_STORAGE_CAPACITY_FIXTURES": "true",
        "MOCK_EXTERNAL_APIS": "true",
        "SERVER_ENVIRONMENT": "development",
        "S3_ENDPOINT_URL": "http://storage.ci.test:9000",
        "CMS_URL": "http://cms:8055",
        "VAULT_URL": "http://vault:8200",
    }
    if any(api_env.get(key) != value for key, value in expected.items()):
        raise RuntimeError("Recovery epoch fixture requires the exact isolated capacity profile")
    program = """
import asyncio
import json
import os
from backend.core.api.app.services.chat_recovery_service import ChatRecoveryService
from backend.core.api.app.services.chat_recovery_cutover import ChatRecoveryCutoverController
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.directus import DirectusService

async def main():
    if (os.getenv('OPENMATES_CI_ISOLATED') != '1'
            or os.getenv('OPENMATES_STORAGE_CAPACITY_FIXTURES') != 'true'
            or os.getenv('OPENMATES_CI_RECOVERY_EPOCH_FIXTURE') != '1'
            or os.getenv('S3_ENDPOINT_URL') != 'http://storage.ci.test:9000'
            or os.getenv('SERVER_ENVIRONMENT', 'production') in ('production', 'prod')):
        raise RuntimeError('Recovery epoch activation requires disposable isolated fixtures')
    cache = CacheService()
    directus = DirectusService(cache_service=cache)
    try:
        service = ChatRecoveryService(directus)
        state = await service.execute('get_cutover_state', {'protocol_version': 1})
        if state.get('protocol_epoch') != 0 or state.get('legacy_in_flight') != 0 or state.get('sends_paused'):
            raise RuntimeError('Recovery fixture cutover state is not a fresh idle epoch zero')
        paused = False
        try:
            await service.execute('set_sends_paused', {'protocol_version': 1, 'sends_paused': True})
            paused = True
            activated = await service.execute(
                'activate_protocol_epoch', {'protocol_version': 1, 'target_epoch': 1},
            )
            if activated.get('protocol_epoch') != 1 or activated.get('activated') is not True:
                raise RuntimeError('Recovery fixture epoch one was not activated')
        finally:
            if paused:
                await service.execute('set_sends_paused', {'protocol_version': 1, 'sends_paused': False})
        controller = ChatRecoveryCutoverController(cache, directus)
        final = await controller.get_state(authoritative=True)
        cached = await controller.get_state()
        if (final.get('protocol_epoch') != 1 or final.get('sends_paused')
                or cached.get('protocol_epoch') != 1 or cached.get('sends_paused')):
            raise RuntimeError('Recovery fixture epoch one is not open for sends')
    finally:
        await directus.close()
        await cache.close()
    print(json.dumps({'protocol_epoch': 1, 'sends_paused': False, 'legacy_in_flight': 0}))

asyncio.run(main())
"""
    try:
        result = compose(
            "exec", "-T", "-e", "OPENMATES_CI_RECOVERY_EPOCH_FIXTURE=1",
            "api", "python", "-c", program, capture=True, timeout=60,
        )
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""
        (RESULTS / "ci-private" / "recovery-epoch.stderr.log").write_text(
            stderr[-100_000:], encoding="utf-8",
        )
        frames = re.findall(
            r'File "<string>", line ([0-9]+), in ([A-Za-z_][A-Za-z_0-9]*)', stderr,
        )
        line, function = frames[-1] if frames else ("unknown", "unknown")
        terminal = stderr.strip().splitlines()[-1] if stderr.strip() else ""
        error_type_match = re.match(r"([A-Za-z_][A-Za-z_0-9.]*)(?::|$)", terminal)
        error_type = error_type_match.group(1) if error_type_match else "unknown"
        raise RuntimeError(
            f"Disposable recovery epoch activation failed at {function}:{line} ({error_type})"
        ) from None
    try:
        receipt = json.loads(result.stdout.splitlines()[-1])
    except (IndexError, json.JSONDecodeError) as exc:
        raise RuntimeError("Disposable recovery epoch activation omitted its receipt") from exc
    if receipt != {"protocol_epoch": 1, "sends_paused": False, "legacy_in_flight": 0}:
        raise RuntimeError("Disposable recovery epoch activation was incomplete")
    return receipt


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
        {"code": invite, "remaining_uses": 1, "is_admin": False, "gifted_credits": FIXTURE_CREDITS},
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
    # The web signup input accepts exactly twelve alphanumeric characters and
    # sends them to the API in XXXX-XXXX-XXXX form.
    invite_chars = secrets.token_hex(6).upper()
    fixture_invite = f"{invite_chars[:4]}-{invite_chars[4:8]}-{invite_chars[8:]}"
    request(
        "http://localhost:8055/items/invite_codes",
        {"code": fixture_invite, "remaining_uses": 20, "is_admin": False},
        token,
    )
    mapped["E2E_SIGNUP_INVITE_CODE"] = fixture_invite
    mapped["OPENMATES_CLI_SIGNUP_INVITE_CODE"] = fixture_invite
    mapped["OPENMATES_STATE_DIR"] = env["OPENMATES_STATE_DIR"]
    accept_fixture_credits(mapped)
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


def wait_component_web(child):
    """Record exact-source evidence for the runner-local Vite component host."""
    verify_shared_dev_rejected()
    for _ in range(90):
        if child.poll() is not None:
            raise RuntimeError("Component Vite server exited before readiness")
        try:
            with urllib.request.urlopen(APP, timeout=2) as response:
                if response.status == 200:
                    source_commit = subprocess.check_output(
                        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
                    ).strip()
                    evidence = {
                        "source_commit": source_commit,
                        "run_id": os.environ["GITHUB_RUN_ID"],
                        "environment": "github-isolated",
                        "harness_commit": os.environ.get("CI_HARNESS_COMMIT"),
                        "runner_environment": os.environ["RUNNER_ENVIRONMENT"],
                        "shared_dev_https": "rejected",
                        "services": {},
                        "frontend": {
                            "url": APP,
                            "source_commit": source_commit,
                            "renderer": "vite-dev",
                        },
                    }
                    (RESULTS / "ci-environment.json").write_text(
                        json.dumps(evidence, indent=2)
                    )
                    return
        except OSError:
            pass
        time.sleep(1)
    raise RuntimeError("Component Vite server did not become ready")


def verify_shared_dev_rejected():
    for host in ("api.dev.openmates.org", "app.dev.openmates.org"):
        if set(socket.gethostbyname_ex(host)[2]) != {"127.0.0.2"}:
            raise RuntimeError("Shared-dev DNS was not rejected for artifact proof")
        try:
            connection = socket.create_connection((host, 443), timeout=2)
        except OSError:
            continue
        connection.close()
        raise RuntimeError("Shared-dev HTTPS reachable during artifact proof")


def verify_artifact_profile(specs: list[str]):
    from ci_coverage import ARTIFACT_SPECS
    if not specs or not set(specs).issubset(ARTIFACT_SPECS):
        raise ValueError("Artifact-only mode cannot run application specs")
    verify_shared_dev_rejected()


def run_e2e(
    specs: list[str],
    *,
    artifact=False,
    component=False,
    visual_smoke=False,
    results=None,
):
    if not specs:
        raise ValueError("An explicit nonempty spec batch is required")
    if visual_smoke:
        from ci_visual_smoke import validate_targets
        validate_targets(specs)
    for name in ([] if visual_smoke else specs):
        path = (WEB / "tests" / name).resolve()
        if (
            not path.is_relative_to(WEB / "tests")
            or not path.is_file()
            or not name.endswith(".spec.ts")
        ):
            raise ValueError("Invalid spec selection")
    if artifact:
        verify_artifact_profile(specs)
    if component:
        from ci_coverage import COMPONENT_MARKER

        for name in specs:
            if COMPONENT_MARKER not in (WEB / "tests" / name).read_text():
                raise ValueError("Component mode requires the isolated component marker")
    if results is None:
        results = []
    with (RESULTS / "ci-web.log").open("w") as log:
        app_server = None
        if component:
            child = subprocess.Popen(
                [
                    "pnpm",
                    "exec",
                    "vite",
                    "dev",
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
        else:
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
                (wait_component_web if component else wait_web)(child)
            if visual_smoke:
                from ci_visual_smoke import capture
                results.extend(capture(specs, WEB, RESULTS))
                return results
            for index, name in enumerate(specs):
                source = (WEB / "tests" / name).read_text()
                env = {**os.environ, "PLAYWRIGHT_TEST_API_URL": API}
                recovery_epoch_receipt = None
                if not (component or artifact):
                    profile = json.loads(COMPOSE_PATH.read_text())
                    if "mailpit" in profile["services"]:
                        env["OPENMATES_CI_MAILPIT_URL"] = "http://127.0.0.1:8025"
                        env["OPENMATES_CI_MAIL_TEST_ADDRESS"] = "ci-inbox@example.com"
                        env["SIGNUP_TEST_EMAIL_DOMAINS"] = profile["services"]["api"]["environment"]["SIGNUP_TEST_EMAIL_DOMAINS"]
                if name in CAPACITY_EPOCH_SPECS:
                    env["E2E_STORAGE_CAPACITY"] = "1"
                    env["E2E_STORAGE_CAPACITY_TARGET"] = "1" if name == "storage-capacity-target.spec.ts" else "0"
                local_signup_assertion = not (component or artifact) and name == "signup-skip-2fa-flow.spec.ts" and "mailpit" in profile["services"]
                account_free = component or artifact or (
                    "// playwright-account: not_required reason=isolated_component_preview"
                    in source
                )
                if not account_free:
                    primary = provision_account(14, identity_index=2 * index)
                    if "OPENMATES_TEST_ACCOUNT_API_KEY" in source and not local_signup_assertion:
                        primary["OPENMATES_TEST_ACCOUNT_API_KEY"] = provision_api_key(primary)
                    secondary = provision_account(15, identity_index=2 * index + 1)
                    if name in CAPACITY_EPOCH_SPECS:
                        recovery_epoch_receipt = activate_isolated_recovery_epoch()
                    env.update(primary)
                    if local_signup_assertion:
                        # The backend and browser share only this runner-generated
                        # assertion secret; no live or SDK key is needed here.
                        env["OPENMATES_TEST_ACCOUNT_API_KEY"] = profile["services"]["api"]["environment"]["OPENMATES_TEST_ACCOUNT_API_KEY"]
                    if name in {"shared-chat-open.spec.ts", "shared-chat-bounded-history.spec.ts", "startup-sync-contract.spec.ts"}:
                        env["OPENMATES_CI_SHARED_CHAT_URL"] = provision_shared_archive(primary)
                    if name == "startup-sync-contract.spec.ts":
                        provision_startup_sync_chats(primary)
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
                    account_evidence["credits_per_identity"] = FIXTURE_CREDITS
                    account_evidence["credits_provisioning"] = "real-signup-invite-gift-acceptance"
                    account_evidence["api_key_provisioned"] = "OPENMATES_TEST_ACCOUNT_API_KEY" in primary
                    if recovery_epoch_receipt is not None:
                        account_evidence["recovery_protocol_epoch"] = recovery_epoch_receipt["protocol_epoch"]
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
                if results[-1]["exit_code"] and not (artifact or component):
                    try:
                        capture_failed_spec_diagnostics(index)
                    except (RuntimeError, subprocess.TimeoutExpired) as exc:
                        results[-1]["diagnostic_error"] = str(exc)
                if name in {"storage-capacity-replay.spec.ts", "storage-capacity-target.spec.ts"} and results[-1]["exit_code"] == 0:
                    try:
                        results.append(run_storage_capacity(identity_start=2 * len(specs),
                                                            full=name == "storage-capacity-target.spec.ts"))
                    except Exception as exc:
                        results.append({"suite": "storage-capacity", "exit_code": 1,
                                        "failure": f"{type(exc).__name__}: {exc}"})
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


def capture_failed_spec_diagnostics(index):
    """Keep the failure's server evidence before the next fresh login replaces it."""
    env = {**os.environ, "CI_DIAGNOSTIC_LABEL": f"spec-{index}"}
    result = subprocess.run(
        [sys.executable, str(Path(__file__).with_name("ci_environment.py")), "logs"],
        env=env, capture_output=True, timeout=90,
    )
    if result.returncode:
        raise RuntimeError("Failed to retain bounded per-spec stack diagnostics")


def run_storage_capacity(*, identity_start: int, full: bool) -> dict:
    """Run a small pilot or explicit full target on the disposable isolated stack."""
    private = RESULTS / "ci-private"
    version_adapter = ROOT / "scripts/storage_capacity_version_adapter.mjs"
    page_adapter = ROOT / "scripts/storage_capacity_page_adapter.mjs"
    for adapter in (version_adapter, page_adapter):
        if not adapter.is_file():
            raise RuntimeError("Capacity output adapter missing before account provisioning")
    cli = ROOT / "frontend/packages/openmates-cli"
    if not (cli / "dist/index.js").is_file():
        raise RuntimeError("Capacity run requires the isolated CLI build; submit CI with prepare_cli=true")
    helper_build = subprocess.run(
        ["pnpm", "exec", "tsup", "src/crypto.ts", "src/objectSlugs.ts",
         "--format", "esm", "--out-dir", "dist/capacity-helpers"],
        cwd=cli, capture_output=True, text=True,
    )
    if helper_build.returncode or not all(
        (cli / "dist/capacity-helpers" / name).is_file() for name in ("crypto.js", "objectSlugs.js")
    ):
        raise RuntimeError("Failed to build test-only CLI crypto helpers")
    try:
        archive_probe = compose(
            "exec", "-T", "api", "python", "/app/scripts/storage_archive_integration.py",
            capture=True, timeout=300,
        )
    except subprocess.CalledProcessError as exc:
        # compose(check=True) raises before the returncode branch below. Keep
        # the full traceback private and publish only source location/type.
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""
        (private / "capacity-archive-probe.stderr.log").write_text(
            stderr[-200_000:], encoding="utf-8",
        )
        frames = re.findall(
            r'File "/app/scripts/storage_archive_integration[.]py", line ([0-9]+), in ([A-Za-z_][A-Za-z_0-9]*)',
            stderr,
        )
        line, function = frames[-1] if frames else ("unknown", "unknown")
        terminal = stderr.strip().splitlines()[-1] if stderr.strip() else ""
        error_type_match = re.match(r"([A-Za-z_][A-Za-z_0-9.]*)(?::|$)", terminal)
        error_type = error_type_match.group(1) if error_type_match else "unknown"
        raise RuntimeError(
            f"Disposable archive DB/S3 transaction probe failed at {function}:{line} ({error_type})"
        ) from None
    try:
        archive_probe_receipt = json.loads(archive_probe.stdout.splitlines()[-1])
    except (IndexError, json.JSONDecodeError) as exc:
        raise RuntimeError("Disposable archive probe omitted a bounded JSON receipt") from exc
    if archive_probe_receipt.get("passed") is not True:
        raise RuntimeError("Disposable archive DB/S3 transaction probe was incomplete")
    (RESULTS / "ci-storage-archive-probe.json").write_text(
        json.dumps(archive_probe_receipt, indent=2), encoding="utf-8",
    )
    environment = json.loads((RESULTS / "ci-environment.json").read_text())
    capacity = environment.get("storage_capacity") or {}
    if capacity.get("provider_network") != "internal" or capacity.get("provider_credentials") != "absent":
        raise RuntimeError("Capacity run lacks independent zero-inference network proof")
    users = int(os.environ.get("CI_STORAGE_CAPACITY_USERS", "1000" if full else "2"))
    concurrency = int(os.environ.get("CI_STORAGE_CAPACITY_CONCURRENCY", "500" if full else "2"))
    if full and (users != 1000 or concurrency != 500):
        raise RuntimeError("Full capacity mode requires 1000 users and 500 worker slots")
    profile = os.environ.get("CI_STORAGE_CAPACITY_PROFILE", "accelerated")
    if profile not in {"accelerated", "burst", "sustained"}:
        raise RuntimeError("Unsupported capacity rate profile")
    states = []
    for index in range(users):
        account = provision_account(100 + index, identity_index=identity_start + index)
        states.append({"state_dir": account["OPENMATES_STATE_DIR"], "allowlisted": True})
    states_path = private / "capacity-states.json"
    states_path.write_text(json.dumps(states), encoding="utf-8")
    states_path.chmod(0o600)
    metrics_before = _capacity_runtime_metrics()
    plan_path = private / "capacity-plan.json"
    results_path = private / "capacity-results.jsonl"
    report_path = RESULTS / "ci-storage-capacity.json"
    plan_cmd = [sys.executable, "scripts/storage_capacity.py", "plan", "--plan", str(plan_path),
                "--users", str(users), "--concurrency", str(concurrency), "--profile", profile]
    if not full:
        pilot_rounds = int(os.environ.get("CI_STORAGE_CAPACITY_PILOT_ROUNDS", "30"))
        if not 2 <= pilot_rounds <= 100:
            raise RuntimeError("Capacity pilot rounds must be 2..100")
        pilot_artifacts = min(pilot_rounds, 4)
        plan_cmd.extend(["--rounds", str(pilot_rounds), "--embeds", str(pilot_artifacts),
                         "--versions", str(pilot_artifacts), "--round-bytes", "20000", "--pilot"])
    subprocess.run(plan_cmd, cwd=ROOT, check=True, capture_output=True, text=True)
    run_env = {**os.environ,
               "OPENMATES_CAPACITY_STATES_JSON": str(states_path),
               "OPENMATES_CAPACITY_VERSION_ADAPTER": str(version_adapter),
               "OPENMATES_CAPACITY_PAGE_ADAPTER": str(page_adapter),
               "OPENMATES_CAPACITY_API_URL": API,
               "OPENMATES_CAPACITY_CLIENT_REPLAY": "1",
               "OPENMATES_CAPACITY_NETWORK_DENY": "confirmed",
               "OPENMATES_CAPACITY_NO_PROVIDER_CREDENTIALS": "confirmed"}
    run_cmd = [sys.executable, "scripts/storage_capacity.py", "run", "--plan", str(plan_path),
               "--results", str(results_path), "--receipts", str(private / "capacity-receipts"),
               "--client-command", "node", "scripts/storage_capacity_client.mjs"]
    result = subprocess.run(run_cmd, cwd=ROOT, env=run_env, capture_output=True, text=True)
    (private / "capacity-run.stderr.log").write_text(result.stderr[-200_000:], encoding="utf-8")
    metrics_after = _capacity_runtime_metrics()
    try:
        report = json.loads(result.stdout.splitlines()[-1])
    except (IndexError, json.JSONDecodeError):
        report = {"passed": False, "failure": "capacity run failed before a complete report"}
    report["infrastructure"] = _capacity_metric_delta(metrics_before, metrics_after)
    if full and report["infrastructure"].get("object_store_operations") is None:
        report["passed"] = False
        report["target_achieved"] = False
        report.setdefault("failures", []).append("raw object-store operation counters unavailable")
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return {"suite": "storage-capacity-target" if full else "storage-capacity-pilot",
            "exit_code": 0 if result.returncode == 0 and report.get("passed") else 1, "report": report}


def _capacity_runtime_metrics() -> dict:
    """Snapshot objective isolated DB/WAL and object-store counters."""
    import urllib.request

    metrics: dict[str, object] = {}
    try:
        db = compose("exec", "-T", "cms-database", "psql", "-U", "openmates", "-d", "openmates",
                     "-At", "-c", "select pg_database_size(current_database()), pg_current_wal_lsn()",
                     capture=True, timeout=15).stdout.strip()
        size, lsn = db.split("|", 1)
        metrics["database_bytes"] = int(size)
        high, low = lsn.split("/", 1)
        metrics["wal_position_bytes"] = int(high, 16) * 2**32 + int(low, 16)
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    try:
        ai_container = compose("ps", "-q", "ai-worker", capture=True).stdout.strip()
        if ai_container:
            metrics["ai_worker_memory"] = subprocess.check_output(
                ["docker", "stats", "--no-stream", "--format", "{{.MemUsage}}", ai_container],
                text=True, timeout=10,
            ).strip()
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        with urllib.request.urlopen("http://127.0.0.1:9000/metrics", timeout=5) as response:
            body = response.read(2_000_000).decode("utf-8", "replace")
        operations = 0.0
        matched = False
        for line in body.splitlines():
            if line.startswith("#") or not re.search(r"(?i)(s3|object).*(request|operation).*_total", line):
                continue
            try:
                operations += float(line.rsplit(None, 1)[-1])
                matched = True
            except ValueError:
                continue
        if matched:
            metrics["object_store_operations"] = operations
    except (OSError, ValueError):
        pass
    return metrics


def _capacity_metric_delta(before: dict, after: dict) -> dict:
    report = {}
    for key in ("database_bytes", "wal_position_bytes", "object_store_operations"):
        old, new = before.get(key), after.get(key)
        report[key] = new - old if isinstance(old, (int, float)) and isinstance(new, (int, float)) else None
    report["ai_worker_memory_before"] = before.get("ai_worker_memory")
    report["ai_worker_memory_after"] = after.get("ai_worker_memory")
    return report


def pytest_failures(report_path: Path) -> list[str]:
    """Return exact failed test/collector node IDs from pytest-json-report."""
    if not report_path.is_file():
        return []
    report = json.loads(report_path.read_text())
    failed = []
    for section in ("tests", "collectors"):
        for item in report.get(section, []):
            if item.get("outcome") == "failed" and item.get("nodeid"):
                failed.append(item["nodeid"])
    return list(dict.fromkeys(failed))


def main():
    require_runner()
    RESULTS.mkdir(exist_ok=True)
    mode = os.environ["CI_TEST_MODE"]
    results = []
    error = None
    proof_dimensions = None
    try:
        proof_dimensions = configure_proof_dimensions()
        if mode in ("component", "e2e", "artifact", "visual-smoke"):
            reject_inherited_accounts()
            selection = json.loads(os.environ["CI_SPECS_JSON"])
            if mode == "visual-smoke":
                results = run_e2e(selection, visual_smoke=True, results=results)
            else:
                results = run_e2e(
                    selection,
                    artifact=mode == "artifact",
                    component=mode == "component",
                    results=results,
                )
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
            selection = validate_pytest_targets(
                json.loads(os.environ.get("CI_SPECS_JSON", "[]")), root=ROOT
            )
            install_command = [
                sys.executable,
                "-m",
                "pip",
                "install",
                "-r",
                "backend/requirements-dev.txt",
                "-r",
                "backend/core/api/requirements.txt",
            ]
            # Backend-only focused tests do not import the Python SDK. Its
            # separate TOON pin conflicts with the backend's declared Git
            # dependency when both are resolved in one pip transaction.
            if not (selection and all(target.startswith("backend/tests/") for target in selection)):
                install_command.extend(["-e", "packages/openmates-python"])
            subprocess.run(
                install_command,
                cwd=ROOT,
                check=True,
            )
            pytest_selection = selection or ["backend/tests"]
            pytest_policy = [] if selection else [
                "-m",
                "not integration and not slow and not vault and not benchmark and not provider_contract",
                "--ignore=backend/tests/fixtures",
                "--ignore=backend/tests/provider_contracts",
                "--ignore=backend/tests/test_encryption_service.py",
                "--ignore=backend/tests/test_integration_encryption.py",
                "--ignore=backend/tests/test_status_service_v2.py",
                "--continue-on-collection-errors",
            ]
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    *pytest_selection,
                    "--json-report",
                    "--json-report-file=test-results/ci-pytest.json",
                    *pytest_policy,
                ],
                cwd=ROOT,
            )
            failed_tests = pytest_failures(RESULTS / "ci-pytest.json")
            results = [{
                "suite": mode,
                "exit_code": result.returncode,
                "selected_tests": selection,
                "selection_mode": "focused" if selection else "broad",
                "failed_tests": failed_tests,
                "failure": (
                    None
                    if result.returncode == 0
                    else "pytest failed; inspect ci-pytest.json"
                ),
            }]
            # Preserve the SDK account coverage in the existing daily unit workflow.
            if not selection:
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
        elif mode == "vitest" and any((selection := validate_vitest_targets(
            json.loads(os.environ.get("CI_SPECS_JSON", "[]")), root=ROOT
        )).values()):
            results.extend(run_selected_vitest(selection))
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
            with (RESULTS / "ci-unit-cli-plans.log").open("w") as output:
                plan_result = subprocess.run(
                    [
                        "node",
                        "--test",
                        "--experimental-strip-types",
                        "--loader",
                        "./tests/loader.mjs",
                        "tests/plans.test.ts",
                        "tests/sdk-plans.test.ts",
                        "tests/sdk-cleartext-boundary.test.ts",
                        "tests/sdk.test.ts",
                        "tests/teams-permissions.test.ts",
                        "tests/cli.test.ts",
                    ],
                    cwd=cli,
                    stdout=output,
                    stderr=subprocess.STDOUT,
                    timeout=300,
                )
            results.append({"suite": "cli-plans", "exit_code": plan_result.returncode})
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
        "proof_dimensions": proof_dimensions,
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
