#!/usr/bin/env python3
"""Per-run throwaway dev test accounts for real-inference test scripts.

Purpose: real-AI test scripts use the personal dev test account by default. When
that account is leased by someone else, ``acquire_real_test_account`` provisions
a brand-new account for this run (invite code with gifted credits, genuine CLI
signup, gift accepted through the product endpoint). ``finish_real_test_account``
releases the leases, exports the account's chats to a reviewable backup directory
and deletes the account with all its data (the backup stays).

Safety: throwaway accounts exist only when the API container reports
SERVER_ENVIRONMENT=development. Emails use a domain read at runtime from the dev
API's SIGNUP_TEST_EMAIL_DOMAINS; no domain, email or secret is stored in the
repository or printed. Every created account is recorded in a flock'd registry so
``sweep`` can export and delete accounts of crashed runs. Backups older than 7
days are removed by the same sweep.

CLI:
  python3 scripts/dev_test_account.py sweep [--dry-run]
  python3 scripts/dev_test_account.py provision --test-name NAME
  python3 scripts/dev_test_account.py finish --email EMAIL --test-name NAME
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

ROOT = Path(__file__).resolve().parents[1]
HOME = Path.home() / ".openmates"
REGISTRY = HOME / "test-accounts" / "registry.json"
BACKUPS = HOME / "test-chat-backups"
API_URL = "https://api.dev.openmates.org"
CMS_URL = "http://localhost:8055"
GIFTED_CREDITS = 20000  # dev-only credits; enough for image/video real runs
LOGIN_ATTEMPTS = 4
EXPORT_MAX_PAGES = 20
LOGIN_RATE_LIMIT_PAUSE_SECONDS = 45
STALE_ACCOUNT_AFTER = timedelta(hours=2)
BACKUP_RETENTION = timedelta(days=7)
SIGNUP_SLOT = 14
LeaseTuple = tuple[str, str, set[str], str]


class ThrowawayAccountError(RuntimeError):
    """A throwaway account could not be provisioned, exported or deleted."""


@dataclass
class RealTestAccount:
    """Account a real-inference run logs in with, plus the leases it holds."""

    kind: str
    environment: dict[str, str]
    leases: list[LeaseTuple]
    test_name: str = ""
    email: str = ""
    created_at: str = ""
    extra: dict[str, str] = field(default_factory=dict)


# --- registry ---------------------------------------------------------------


@contextmanager
def _registry_locked():
    REGISTRY.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (REGISTRY.parent / "registry.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def _read_registry() -> list[dict]:
    if not REGISTRY.exists():
        return []
    return json.loads(REGISTRY.read_text())


def _write_registry(entries: list[dict]) -> None:
    temporary = REGISTRY.with_suffix(".tmp")
    temporary.write_text(json.dumps(entries, indent=2))
    os.chmod(temporary, 0o600)
    temporary.replace(REGISTRY)


def registry_update(email: str, **changes: str) -> None:
    """Create or update the registry entry of ``email`` under the file lock."""
    with _registry_locked():
        entries = _read_registry()
        for entry in entries:
            if entry["email"] == email:
                entry.update(changes)
                break
        else:
            entries.append({"email": email, **changes})
        _write_registry(entries)


def registry_entries() -> list[dict]:
    with _registry_locked():
        return _read_registry()


# --- environment access (replaced by fakes in tests) -------------------------


def _docker(*args: str, stdin: str | None = None, timeout: int = 60) -> str:
    result = subprocess.run(
        ["docker", *args], input=stdin, capture_output=True, text=True, timeout=timeout, check=False
    )
    if result.returncode:
        lines = (result.stderr + "\n" + result.stdout).strip().splitlines()
        errors = [line for line in lines if re.search(r"ERROR|Error|error|failed|\u274c", line)]
        last = (errors or lines)[-1:] or [f"exit {result.returncode}"]
        detail = re.sub(r"[\w.%+-]+@[\w.-]+", "<email>", last[0].strip())[:200]
        raise ThrowawayAccountError(f"docker {args[0]} {args[1] if len(args) > 1 else ''} failed: {detail}")
    return result.stdout


def server_is_development() -> bool:
    return _docker("exec", "api", "printenv", "SERVER_ENVIRONMENT").strip() == "development"


def _test_email_domain() -> str:
    domains = _docker("exec", "api", "printenv", "SIGNUP_TEST_EMAIL_DOMAINS").strip()
    first = domains.split(",")[0].strip().lstrip("@")
    if not first:
        raise ThrowawayAccountError("signup_test_email_domains_empty")
    return first


def _runtime():
    import code_run_real_test

    return code_run_real_test


def personal_environment() -> dict[str, str]:
    return _runtime().personal_test_environment()


def _lease(prefix: str, name: str, session_id: str, resources: set[str], mode: str, timeout: int) -> LeaseTuple:
    runtime = _runtime()
    owner = f"repository-session-{session_id}"
    lease_id = f"{prefix}-{name}-{secrets.token_hex(6)}"
    runtime.sessions.acquire_test_resource_lease(lease_id, owner, resources, mode=mode, timeout=timeout)
    return (lease_id, owner, resources, mode)


def release_leases(leases: list[LeaseTuple]) -> list[str]:
    """Release leases in reverse order; returns lease ids that failed to release."""
    failed: list[str] = []
    for lease_id, *_ in reversed(leases):
        try:
            _runtime().sessions.release_test_resource_lease(lease_id)
        except RuntimeError:
            failed.append(lease_id)
    return failed


def wait_for_personal_leases(prefix: str, session_id: str, timeout: int) -> list[LeaseTuple]:
    return _runtime().personal_dev_leases(prefix, session_id, timeout=timeout)


def try_personal_account_lease(prefix: str, session_id: str) -> LeaseTuple | None:
    """Lease the personal account without waiting; None when someone holds it."""
    try:
        return _lease(prefix, "account", session_id, {"playwright-account:personal-dev"}, "exclusive", 0)
    except RuntimeError:
        return None


def stack_lease(prefix: str, session_id: str, timeout: int) -> LeaseTuple:
    return _lease(prefix, "stack", session_id, {_runtime().sessions.DOCKER_RESOURCE_DEV_STACK}, "shared", timeout)


# --- provisioning -----------------------------------------------------------

_INVITE_PROGRAM = """
import json, os, sys, urllib.request
base = os.getenv('CMS_URL', 'http://cms:8055').rstrip('/')
email = os.getenv('DIRECTUS_ADMIN_EMAIL') or os.getenv('DATABASE_ADMIN_EMAIL')
password = os.getenv('DIRECTUS_ADMIN_PASSWORD') or os.getenv('DATABASE_ADMIN_PASSWORD')
assert email and password
def call(path, body, token=None):
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    req = urllib.request.Request(base + path, data=json.dumps(body).encode(), headers=headers, method='POST')
    return json.loads(urllib.request.urlopen(req, timeout=15).read().decode())
token = call('/auth/login', {'email': email, 'password': password})['data']['access_token']
code, credits = sys.argv[1], int(sys.argv[2])
call('/items/invite_codes', {'code': code, 'remaining_uses': 1, 'is_admin': False, 'gifted_credits': credits}, token)
"""


def _create_invite(code: str) -> None:
    """Create a single-use gifted-credit invite from inside the API container (admin auth stays there)."""
    _docker("exec", "api", "python3", "-c", _INVITE_PROGRAM, code, str(GIFTED_CREDITS), timeout=60)


def _cache_password() -> str:
    args = json.loads(_docker("inspect", "cache", "--format", "{{json .Args}}"))
    return args[args.index("--requirepass") + 1]


def _verification_code(email: str, password: str) -> str:
    return _docker(
        "exec", "-e", "REDISCLI_AUTH=" + password, "cache", "redis-cli", "--raw", "GET",
        "email_verification:" + email,
    ).strip().strip('"')


def _read_env_artifact(path: Path, slot: int) -> dict[str, str]:
    values = dict(
        line.split("=", 1) for line in path.read_text().splitlines() if line and not line.startswith("#")
    )
    prefix = f"OPENMATES_TEST_ACCOUNT_{slot}_"
    mapped = {
        key.replace(prefix, "OPENMATES_TEST_ACCOUNT_"): value.strip().strip("\"'")
        for key, value in values.items()
        if key.startswith(prefix)
    }
    for suffix in ("EMAIL", "PASSWORD", "OTP_KEY"):
        if not mapped.get(f"OPENMATES_TEST_ACCOUNT_{suffix}"):
            raise ThrowawayAccountError("provisioned_credentials_incomplete")
    return mapped


def provision_throwaway(test_name: str) -> dict[str, str]:
    """Create a fresh dev account through the real CLI signup; returns login env values."""
    if not server_is_development():
        raise ThrowawayAccountError("throwaway_accounts_require_development_server")
    email = f"devtest-{secrets.token_hex(6)}@{_test_email_domain()}"
    registry_update(email, created_at=datetime.now(UTC).isoformat(), status="provisioned", test_name=test_name)
    invite = secrets.token_hex(9)
    _create_invite(invite)
    private = Path(tempfile.mkdtemp(prefix="devtest-provision-"))
    os.chmod(private, 0o700)
    try:
        artifact = private / "account.env"
        env = {
            **os.environ,
            "OPENMATES_CLI_SIGNUP_INVITE_CODE": invite,
            "NO_COLOR": "1",
            "OPENMATES_STATE_DIR": str(private / "state"),
        }
        command = [
            os.environ.get("OPENMATES_CLI", "openmates"), "--api-url", API_URL, "e2e", "provision-auth-accounts",
            "--slot", str(SIGNUP_SLOT), "--artifact", str(artifact), "--email", email,
            "--username", "dt" + secrets.token_hex(6), "--force",
        ]
        password = _cache_password()
        with (private / "provision.log").open("w") as log:
            child = subprocess.Popen(
                command, cwd=ROOT, env=env, stdin=subprocess.PIPE, stdout=log, stderr=log, text=True
            )
            try:
                deadline = time.monotonic() + 120
                while time.monotonic() < deadline:
                    if child.poll() is not None:
                        raise ThrowawayAccountError(f"signup_exited_early_{child.returncode}")
                    code = _verification_code(email, password)
                    if len(code) == 6 and code.isdigit():
                        child.stdin.write(code + "\n")
                        child.stdin.flush()
                        break
                    time.sleep(2)
                else:
                    raise ThrowawayAccountError("signup_email_code_not_generated")
                if child.wait(timeout=120):
                    raise ThrowawayAccountError("signup_security_setup_failed")
            finally:
                if child.poll() is None:
                    child.kill()
                    child.wait()
        credentials = _read_env_artifact(artifact, SIGNUP_SLOT)
        save_credentials(email, credentials)
    finally:
        shutil.rmtree(private, ignore_errors=True)
    grant_credits(credentials)
    return credentials


def login_state(credentials: dict[str, str], state_dir: Path) -> None:
    """Log the repo CLI helper in as ``credentials`` into an isolated state dir.

    ``--slot ""`` makes the helper use exactly these credentials instead of
    cycling through numbered slots from the repo .env. Rate-limited (HTTP 429)
    attempts and a reused TOTP window (``code_wrong``) are retried after a
    pause; any other failure raises at once.
    """
    reason = ""
    for attempt in range(LOGIN_ATTEMPTS):
        result = subprocess.run(
            ["node", str(ROOT / "scripts/openmates_cli_test_account.mjs"), "login", "--slot", "", "--api-url", API_URL],
            cwd=ROOT, env={**os.environ, **credentials, "OPENMATES_STATE_DIR": str(state_dir)},
            capture_output=True, text=True, timeout=180, check=False,
        )
        if not result.returncode:
            return
        tail = (result.stderr or result.stdout).strip().splitlines()[-3:]
        reason = re.sub(r"[\w.%+-]+@[\w.-]+", "<email>", " | ".join(tail))[:300]
        if attempt == LOGIN_ATTEMPTS - 1:
            break
        if "HTTP 429" in reason:
            time.sleep(LOGIN_RATE_LIMIT_PAUSE_SECONDS)
        elif "code_wrong" in reason:
            # A TOTP code is single-use per 30 s window; signup already used this one.
            time.sleep(31 - time.time() % 30)
        else:
            break
    raise ThrowawayAccountError(f"throwaway_login_failed: {reason}")


def grant_credits(credentials: dict[str, str]) -> None:
    """Top the new account up to GIFTED_CREDITS with the operator script inside the API container.

    Dev does not require invite codes, so signup ignores the invite's gifted
    credits; the operator top-up reuses the app's own encrypted-balance path.
    """
    email = credentials["OPENMATES_TEST_ACCOUNT_EMAIL"]
    _docker(
        "exec", "-i", "api", "python", "/app/backend/scripts/top_up_test_account_credits.py",
        "--accounts-json", "-", "--minimum", str(GIFTED_CREDITS), "--target", str(GIFTED_CREDITS),
        stdin=json.dumps([{"email": email}]), timeout=120,
    )


# --- export / delete ----------------------------------------------------------


def _cli(args: list[str], state: Path, timeout: int) -> str:
    """Run the installed OpenMates CLI as the logged-in account in ``state``."""
    result = subprocess.run(
        [os.environ.get("OPENMATES_CLI", "openmates"), *args],
        cwd=ROOT, env={**os.environ, "OPENMATES_STATE_DIR": str(state), "OPENMATES_API_URL": API_URL},
        capture_output=True, text=True, timeout=timeout, check=False,
    )
    if result.returncode:
        last = (result.stderr or result.stdout).strip().splitlines()[-1:] or [""]
        detail = re.sub(r"[\w.%+-]+@[\w.-]+", "<email>", last[0])[:200]
        raise ThrowawayAccountError(f"chat_export_failed ({args[0]} {args[1]}): {detail}")
    return result.stdout


def export_chats(credentials: dict[str, str], destination: Path) -> int:
    """Download every chat of the account as readable Markdown + YAML; returns the chat count.

    Uses per-chat ``chats download`` rather than ``account export`` so the
    backup is directly readable and does not depend on the archive format.
    """
    state = Path(tempfile.mkdtemp(prefix="devtest-export-"))
    os.chmod(state, 0o700)
    try:
        login_state(credentials, state)
        destination.mkdir(parents=True, exist_ok=True)
        chat_ids: list[str] = []
        for page in range(1, EXPORT_MAX_PAGES + 1):
            listing = json.loads(_cli(["chats", "list", "--limit", "100", "--page", str(page), "--json"], state, 120))
            ids = [chat["id"] for chat in listing.get("chats", []) if chat.get("id")]
            chat_ids.extend(ids)
            if len(ids) < 100:
                break
        for chat_id in chat_ids:
            _cli(["chats", "download", chat_id, "--output", str(destination)], state, 300)
        return len(chat_ids)
    finally:
        shutil.rmtree(state, ignore_errors=True)


def delete_account(email: str) -> str:
    """Queue the full account deletion (chats, embeds, files, billing, user record).

    Returns "ok", or "absent" when no user exists (signup failed before the account was created).
    """
    try:
        _docker(
            "exec", "-i", "api", "python", "/app/backend/scripts/delete_user_account.py",
            "--email", email, "--yes", "--reason", "Disposable dev test account", timeout=300,
        )
    except ThrowawayAccountError as exc:
        if "No user found" in str(exc):
            return "absent"
        raise
    return "ok"


def _email_hash(email: str) -> str:
    return hashlib.sha256(email.encode()).hexdigest()[:16]


# --- public API ---------------------------------------------------------------


def acquire_real_test_account(
    prefix: str, session_id: str, test_name: str, *, stack_timeout: int, allow_throwaway: bool = True
) -> RealTestAccount:
    """Personal account when free, else a throwaway account (or wait when not allowed)."""
    account_lease = try_personal_account_lease(prefix, session_id)
    if account_lease is None and not allow_throwaway:
        return RealTestAccount(
            "personal", personal_environment(), wait_for_personal_leases(prefix, session_id, stack_timeout),
            test_name=test_name,
        )
    if account_lease is not None:
        try:
            environment = personal_environment()
            leases = [account_lease, stack_lease(prefix, session_id, stack_timeout)]
        except BaseException:
            release_leases([account_lease])
            raise
        return RealTestAccount("personal", environment, leases, test_name=test_name)
    credentials = provision_throwaway(test_name)
    email = credentials["OPENMATES_TEST_ACCOUNT_EMAIL"]
    created_at = datetime.now(UTC).isoformat()
    try:
        leases = [stack_lease(prefix, session_id, stack_timeout)]
    except BaseException:
        finish_throwaway(email, test_name, created_at)
        raise
    return RealTestAccount(
        "throwaway", {**os.environ, **credentials}, leases, test_name=test_name, email=email, created_at=created_at
    )


def _credentials_file(email: str) -> Path:
    return REGISTRY.parent / "credentials" / f"{_email_hash(email)}.json"


def save_credentials(email: str, credentials: dict[str, str]) -> None:
    """Keep login values (0600) until deletion so a sweep can still back up a crashed run's chats."""
    path = _credentials_file(email)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as handle:
        json.dump(credentials, handle)


def load_credentials(email: str) -> dict[str, str] | None:
    path = _credentials_file(email)
    return json.loads(path.read_text()) if path.exists() else None


def finish_throwaway(email: str, test_name: str, created_at: str, credentials: dict[str, str] | None = None) -> dict:
    """Export chats (when credentials are known) and delete the account; delete runs even if export fails."""
    receipt: dict = {"kind": "throwaway", "email_hash": _email_hash(email)}
    if credentials is not None:
        day = datetime.now(UTC).strftime("%Y-%m-%d")
        backup = BACKUPS / day / f"{test_name}-{secrets.token_hex(4)}"
        try:
            chats = export_chats(credentials, backup)
            backup.mkdir(parents=True, exist_ok=True)
            (backup / "manifest.json").write_text(json.dumps({
                "test_name": test_name, "created_at": created_at, "kind": "throwaway",
                "email_hash": _email_hash(email), "chats": chats,
            }, indent=2))
            receipt["export"] = {"status": "ok", "path": str(backup), "chats": chats}
            registry_update(email, status="exported")
        except (ThrowawayAccountError, OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
            receipt["export"] = {"status": "failed", "error": f"{type(exc).__name__}: {exc}"}
    else:
        receipt["export"] = {"status": "skipped_no_credentials"}
    try:
        outcome = delete_account(email)
        registry_update(email, status="deleted", deleted_at=datetime.now(UTC).isoformat())
        _credentials_file(email).unlink(missing_ok=True)
        receipt["delete"] = {"status": outcome}
    except (ThrowawayAccountError, OSError, subprocess.TimeoutExpired) as exc:
        receipt["delete"] = {"status": "failed", "error": f"{type(exc).__name__}: {exc}"}
    return receipt


def finish_real_test_account(account: RealTestAccount) -> dict:
    """Release leases; for throwaway accounts export the chats then delete the account."""
    failed = release_leases(account.leases)
    receipt: dict = {"kind": account.kind}
    if failed:
        receipt["lease_release_failed"] = failed
    if account.kind == "throwaway":
        credentials = {k: v for k, v in account.environment.items() if k.startswith("OPENMATES_TEST_ACCOUNT_")}
        receipt.update(finish_throwaway(account.email, account.test_name, account.created_at, credentials))
    return receipt


# --- sweep --------------------------------------------------------------------


def sweep(dry_run: bool = False, now: datetime | None = None) -> dict:
    """Back up and delete stale throwaway accounts (crashed runs), then delete backups older than 7 days."""
    now = now or datetime.now(UTC)
    report: dict = {"accounts": [], "backups": [], "dry_run": dry_run}
    for entry in registry_entries():
        created = datetime.fromisoformat(entry["created_at"])
        if entry.get("status") == "deleted" or now - created < STALE_ACCOUNT_AFTER:
            continue
        if dry_run:
            report["accounts"].append({"email_hash": _email_hash(entry["email"]), "action": "would_delete"})
            continue
        result = finish_throwaway(entry["email"], entry.get("test_name", "swept"), entry["created_at"],
                                  load_credentials(entry["email"]))
        report["accounts"].append(result)
    if BACKUPS.exists():
        for day in sorted(BACKUPS.iterdir()):
            try:
                age = now - datetime.strptime(day.name, "%Y-%m-%d").replace(tzinfo=UTC)
            except ValueError:
                continue
            if age <= BACKUP_RETENTION:
                continue
            report["backups"].append(str(day))
            if not dry_run:
                shutil.rmtree(day)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sweep_parser = sub.add_parser("sweep")
    sweep_parser.add_argument("--dry-run", action="store_true")
    provision_parser = sub.add_parser("provision")
    provision_parser.add_argument("--test-name", required=True)
    finish_parser = sub.add_parser("finish")
    finish_parser.add_argument("--email", required=True)
    finish_parser.add_argument("--test-name", required=True)
    args = parser.parse_args(argv)
    if args.command == "sweep":
        print(json.dumps(sweep(args.dry_run), indent=2))
    elif args.command == "provision":
        credentials = provision_throwaway(args.test_name)
        # Passwords stay out of stdout; the email is enough to run finish (export needs a manual login).
        print(json.dumps({"email": credentials["OPENMATES_TEST_ACCOUNT_EMAIL"], "status": "provisioned"}))
    else:
        print(json.dumps(finish_throwaway(args.email, args.test_name, datetime.now(UTC).isoformat()), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
