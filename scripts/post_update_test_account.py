"""Temporary test accounts for post-update checks (chat check and voice call check).

Purpose: after an update, the check signs in with a brand-new account that is
labelled as test account (users.is_test_account) so no signup, user, usage or
growth number counts it, and deletes it with all its data afterwards.

Dev uses the E2E signup CLI and the local API container. Production uses the
AI test users' single-use gift cards and browser account lifecycle. The gift
card marks the account as a test account when it is redeemed during signup.

Credentials are written only to a 0600 file; the command prints the e-mail, the file
path and the user id hash, never the password or OTP key.

  python3 scripts/post_update_test_account.py --target dev|prod create [--out FILE]
  python3 scripts/post_update_test_account.py --target dev|prod delete --email EMAIL
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

ROOT = Path(__file__).resolve().parents[1]
SERVER_SCRIPT = ROOT / "backend" / "scripts" / "post_update_test_account.py"
DEV_API_URL = "https://api.dev.openmates.org"
SIGNUP_SLOT = 14
CODE_WAIT_SECONDS = 120
PROD_ACCOUNT_LABEL = "post-update"


class AccountError(RuntimeError):
    """Creating or deleting the temporary account failed."""


def _server(target: str, command: str, email: str = "", timeout: int = 300) -> dict:
    """Run one provisioning command in the dev API container."""
    if target != "dev":
        raise AccountError("server-side test account provisioning is dev-only")
    argv = ["docker", "exec", "-i", "api", "python", "-", command] + (["--email", email] if email else [])
    run = subprocess.run(argv, input=SERVER_SCRIPT.read_text(), capture_output=True, text=True,
                         timeout=timeout, check=False)
    lines = [line for line in run.stdout.splitlines() if line.startswith("{")]
    if not lines:
        raise AccountError(f"{command} failed: no result (exit {run.returncode})")
    result = json.loads(lines[-1])
    if run.returncode or "error" in result:
        raise AccountError(f"{command} failed: {result.get('error', 'exit ' + str(run.returncode))}")
    return result


def _email_domain(target: str) -> str:
    if target != "dev":
        raise AccountError("use the AI test-user mailbox for production")
    out = subprocess.run(["docker", "exec", "api", "printenv", "SIGNUP_TEST_EMAIL_DOMAINS"],
                         capture_output=True, text=True, check=False).stdout
    domain = out.split(",")[0].strip().lstrip("@")
    if not domain:
        raise AccountError("dev has no SIGNUP_TEST_EMAIL_DOMAINS")
    return domain


def _read_artifact(path: Path) -> dict[str, str]:
    values = dict(line.split("=", 1) for line in path.read_text().splitlines()
                  if line and not line.startswith("#") and "=" in line)
    prefix = f"OPENMATES_TEST_ACCOUNT_{SIGNUP_SLOT}_"
    out = {k[len(prefix):].lower(): v.strip().strip("\"'") for k, v in values.items() if k.startswith(prefix)}
    if not all(out.get(k) for k in ("email", "password", "otp_key")):
        raise AccountError("signup returned incomplete credentials")
    return out


def _signup(target: str, email: str, invite: str, private: Path) -> dict[str, str]:
    artifact = private / "account.env"
    env = {**os.environ, "OPENMATES_CLI_SIGNUP_INVITE_CODE": invite, "NO_COLOR": "1",
           "OPENMATES_STATE_DIR": str(private / "state")}
    command = [os.environ.get("OPENMATES_CLI", "openmates"), "--api-url", DEV_API_URL, "e2e",
               "provision-auth-accounts", "--slot", str(SIGNUP_SLOT), "--artifact", str(artifact),
               "--email", email, "--username", "pu" + secrets.token_hex(5), "--force"]
    with (private / "signup.log").open("w") as log:
        child = subprocess.Popen(command, cwd=ROOT, env=env, stdin=subprocess.PIPE, stdout=log, stderr=log, text=True)
        try:
            deadline = time.monotonic() + CODE_WAIT_SECONDS
            while time.monotonic() < deadline:
                if child.poll() is not None:
                    raise AccountError(f"signup exited early ({child.returncode})")
                code = _server(target, "code", email, timeout=60).get("code") or ""
                if len(code) == 6 and code.isdigit():
                    child.stdin.write(code + "\n")
                    child.stdin.flush()
                    break
                time.sleep(3)
            else:
                raise AccountError("signup e-mail code never appeared")
            if child.wait(timeout=180):
                raise AccountError("signup security setup failed")
        finally:
            if child.poll() is None:
                child.kill()
                child.wait()
    return _read_artifact(artifact)


def _write_credentials(out: Path | None, credentials: dict) -> Path:
    if out is None:
        fd, filename = tempfile.mkstemp(prefix="post-update-account-", suffix=".json")
        out = Path(filename)
    else:
        fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as handle:
        os.fchmod(handle.fileno(), 0o600)
        json.dump(credentials, handle)
    return out


def _production_browser_job(signup: dict, mode: str) -> dict:
    """Run one scripted account operation in the existing AI test-user browser."""
    import ai_test_users_exec as worker
    import e2b_dev_capacity

    run_id = f"post-update-{secrets.token_hex(8)}"
    job = worker.make_job(None, "prod", run_id, signup, worker.Settings(), PROD_ACCOUNT_LABEL, mode=mode)
    slot = e2b_dev_capacity.acquire(f"post-update-{mode}", timeout=900)
    if slot is None:
        raise AccountError("no browser slot for the production test account")
    try:
        run = worker.docker("exec", "-i", worker.CONTAINER, "python", worker.CONTAINER_WORKER,
                            stdin=json.dumps(job), timeout=1200)
        lines = run.stdout.splitlines()
        if run.returncode or not lines:
            raise AccountError(f"production {mode} browser job failed")
        result = json.loads(lines[-1])
        usage = result.get("e2b") or {}
        if usage.get("seconds"):
            e2b_dev_capacity.record_spend(usage["seconds"], usage["cpu"], usage["memory_mb"])
        return result
    finally:
        slot.release()
        worker.docker("exec", worker.CONTAINER, "rm", "-rf", f"{worker.CONTAINER_OUTPUT}/{run_id}")


def _create_production(out: Path | None) -> dict:
    import ai_test_users_accounts as accounts

    code, remaining = accounts.pop_prod_code()
    if not code:
        raise AccountError("no production test-account gift card is available")
    domain, inbox = accounts.signup_mailbox("prod")
    identity = accounts.new_identity(domain=domain)
    email = identity["email"]
    signup = {**identity, "inbox": inbox}
    accounts.save_secret(email, signup)
    accounts.register_account(email, "prod", f"post-update-{secrets.token_hex(8)}", PROD_ACCOUNT_LABEL)
    try:
        result = _production_browser_job({**signup, "gift_card_code": code}, "signup_only")
        if result.get("status") != "signup_only_done":
            raise AccountError("production test signup or gift card redemption failed")
        accounts.update_status(email, "signed_up")
        path = _write_credentials(out, {"email": email, "password": identity["password"]})
    except (AccountError, OSError, ValueError, subprocess.SubprocessError):
        delete("prod", email)
        raise
    return {"email": email, "credentials_file": str(path), "remaining_gift_cards": remaining}


def _delete_production(email: str) -> dict:
    import ai_test_users_accounts as accounts

    entry = accounts.latest_by_email().get(email)
    if not entry or entry["target"] != "prod" or entry["persona"] != PROD_ACCOUNT_LABEL:
        raise AccountError("email does not identify a production post-update test account")
    if entry["status"] == "deleted":
        return {"deleted": True}
    signup = accounts.load_secret(email)
    if signup is None:
        raise AccountError("production test-account credentials are missing")
    try:
        result = _production_browser_job(signup, "delete_only")
        if result.get("deletion", {}).get("status") not in ("deleted", "absent"):
            raise AccountError("production test-account deletion did not complete")
    except (AccountError, OSError, ValueError, subprocess.SubprocessError):
        accounts.update_status(email, "delete_failed")
        raise
    accounts.update_status(email, "deleted")
    accounts.remove_secret(email)
    return {"deleted": True}


def create(target: str, out: Path | None) -> dict:
    """Sign up, label and fund a temporary account; credentials go to a 0600 file."""
    if target == "prod":
        return _create_production(out)
    email = f"omtestuser-{secrets.token_hex(8)}@{_email_domain(target)}"
    invite = _server(target, "prepare")["invite_code"]
    private = Path(tempfile.mkdtemp(prefix="post-update-account-"))
    os.chmod(private, 0o700)
    try:
        try:
            credentials = _signup(target, email, invite, private)
            marked = _server(target, "mark", email)
        except (AccountError, subprocess.SubprocessError):
            _cleanup_after_failure(target, email)
            raise
        path = _write_credentials(out, {"email": email, "password": credentials["password"],
                                        "otp_key": credentials["otp_key"], "user_id_hash": marked["user_id_hash"]})
        return {"email": email, "credentials_file": str(path), "user_id_hash": marked["user_id_hash"]}
    finally:
        shutil.rmtree(private, ignore_errors=True)


def _cleanup_after_failure(target: str, email: str) -> None:
    try:
        _server(target, "delete", email)
    except (AccountError, subprocess.SubprocessError) as exc:
        print(f"WARNING: cleanup of a failed signup did not finish: {exc}", file=sys.stderr)


def delete(target: str, email: str) -> dict:
    """Delete the account; a failure is a warning, never a crash."""
    try:
        if target == "prod":
            return _delete_production(email)
        return _server(target, "delete", email)
    except (AccountError, OSError, subprocess.SubprocessError, ValueError) as exc:
        warning = f"account cleanup failed: {exc}"
        print(f"WARNING: {warning}", file=sys.stderr)
        return {"deleted": False, "warning": warning}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--target", choices=["dev", "prod"], required=True)
    sub = parser.add_subparsers(dest="command", required=True)
    make = sub.add_parser("create")
    make.add_argument("--out", type=Path)
    remove = sub.add_parser("delete")
    remove.add_argument("--email", required=True)
    args = parser.parse_args(argv)
    if args.command == "delete":
        result = delete(args.target, args.email)
        print(json.dumps(result))
        return 0 if result.get("deleted") else 1
    try:
        print(json.dumps(create(args.target, args.out)))
    except (AccountError, OSError, subprocess.SubprocessError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
