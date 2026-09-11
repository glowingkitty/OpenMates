#!/usr/bin/env python3
"""Bounded, opt-in live-dev signup email health check (engineering tooling).

Uses the global installed CLI on the dev host; never completes registration.
Keeps OAuth tokens, recipient aliases, message bodies and codes in memory.
Reports queue acknowledgement, Brevo acceptance and inbox arrival separately.
See docs/architecture/signup-email-live-smoke.md for scheduling and boundaries.
"""

import argparse
import json
import os
import re
import secrets
import selectors
import shutil
import socket
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from email.utils import getaddresses
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

API_URL = "https://api.dev.openmates.org"
DEV_HOSTNAME = "dev-server"
CLI_REQUEST_SECONDS = 30
CLI_PROMPT = b"Email verification code: "
GMAIL_URL = "https://gmail.googleapis.com/gmail/v1/users/me"
BREVO_URL = "https://api.brevo.com/v3/smtp/statistics/events"
POLL_SECONDS = 5
HTTP_TIMEOUT = 10
DEADLINE_SECONDS = 120
# email.this_is_your_email_code, not the heading inside confirm-email.mjml.
SUBJECT_PATTERN = re.compile(r"Your code: [0-9]{6}", re.IGNORECASE)
GMAIL_SETTINGS = ("GMAIL_CLIENT_ID", "GMAIL_CLIENT_SECRET", "GMAIL_REFRESH_TOKEN", "GMAIL_TEST_ADDRESS")


class ProbeError(Exception):
    """Only static, safe stage/status identifiers may leave an HTTP boundary."""


def require_dev_host():
    if os.environ.get("GITHUB_ACTIONS") or socket.gethostname() != DEV_HOSTNAME:
        raise ProbeError("dev_host_only_github_forbidden")


def cli_environment(state_dir):
    # No engineering auth, signup-code shortcut, profile or inbox credentials
    # may flow into the isolated signup subprocess. No confirmation is supplied.
    environment = {key: value for key, value in os.environ.items()
                   if key in ("PATH", "HOME", "LANG", "LC_ALL", "TZ")}
    environment["OPENMATES_STATE_DIR"] = str(state_dir)
    environment["OPENMATES_CLI_SIGNUP_PASSWORD"] = secrets.token_urlsafe(32)
    return environment


def request_with_cli(alias, run_id):
    installed = Path.home() / ".npm-global/bin/openmates"
    cli = str(installed) if installed.is_file() else shutil.which("openmates")
    if not cli:
        raise ProbeError("global_cli_unavailable")
    # Exclude repository/source builds even if a shell PATH was customized.
    resolved = Path(cli).resolve()
    if "node_modules/openmates/" not in str(resolved):
        raise ProbeError("installed_global_cli_required")
    with tempfile.TemporaryDirectory(prefix="signup-email-state-") as directory:
        command = [cli, "--api-url", API_URL, "signup", "--email", alias,
                   "--username", "email-smoke-" + run_id.replace("-", "")]
        invite = os.environ.get("E2E_SIGNUP_INVITE_CODE") or os.environ.get("SIGNUP_TEST_INVITE_CODE")
        if invite:
            command.extend(["--invite-code", invite])
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, env=cli_environment(Path(directory)),
                                   cwd=directory)
        output = b""
        deadline = time.monotonic() + CLI_REQUEST_SECONDS
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                while time.monotonic() < deadline:
                    if selector.select(timeout=min(1, max(0, deadline - time.monotonic()))):
                        chunk = os.read(process.stdout.fileno(), 4096)
                        if not chunk:
                            raise ProbeError("cli_exited_before_email_prompt")
                        output = (output + chunk)[-65536:]
                        if CLI_PROMPT in output:
                            return
                    if process.poll() is not None:
                        raise ProbeError("cli_exited_before_email_prompt")
                raise ProbeError("cli_email_request_timeout")
        finally:
            # Stop before verification/account creation. Never print CLI output.
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            process.stdin.close()
            process.stdout.close()


def request_json(url, *, data=None, headers=None, form=False):
    headers = dict(headers or {})
    body = None
    if data is not None:
        body = (urlencode(data) if form else json.dumps(data)).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded" if form else "application/json"
    try:
        with urlopen(Request(url, data=body, headers=headers), timeout=HTTP_TIMEOUT) as response:
            return json.load(response)
    except HTTPError as exc:
        raise ProbeError(f"http_{exc.code}") from None
    except (URLError, TimeoutError, ValueError, OSError):
        raise ProbeError("transport_or_json_error") from None


def make_alias(address, run_id):
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", run_id):
        raise ProbeError("invalid_run_id")
    if not re.fullmatch(r"[^\s@]+@[^\s@]+", address):
        raise ProbeError("invalid_inbox_address")
    local, domain = address.lower().split("@")
    return f"{local.split('+')[0]}+live-signup-{run_id}@{domain}"


def message_matches(message, alias, started):
    headers = {h["name"].lower(): h["value"] for h in message.get("payload", {}).get("headers", [])}
    recipients = {address.lower() for _, address in getaddresses([headers.get("to", "")])}
    return (alias in recipients and int(message.get("internalDate", 0)) >= int((started - 10) * 1000)
            and SUBJECT_PATTERN.fullmatch(headers.get("subject", "").strip()) is not None)


def acceptance_matches(event, alias, started):
    try:
        timestamp = datetime.fromisoformat(event.get("date", "").replace("Z", "+00:00"))
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        fresh = timestamp.timestamp() >= started - 10
    except (TypeError, ValueError):
        return False
    return (fresh and event.get("email", "").lower() == alias
            and event.get("event") == "requests"
            and event.get("messageId") not in (None, "", "unknown"))


def run_probe(run_id, receipt, report, observe_since=None):
    require_dev_host()
    report["mode"] = "read_only_observation" if observe_since is not None else "send_once"
    if observe_since is not None and not time.time() - 86400 <= observe_since <= time.time():
        raise ProbeError("observation_start_outside_last_day")
    missing = [name for name in GMAIL_SETTINGS if not os.environ.get(name)]
    if missing:
        report["configuration"] = "missing:" + ",".join(missing)
        return
    alias = make_alias(os.environ["GMAIL_TEST_ADDRESS"], run_id)
    report["stage"] = "gmail_oauth"
    token_response = request_json("https://oauth2.googleapis.com/token", form=True, data={
        "client_id": os.environ["GMAIL_CLIENT_ID"], "client_secret": os.environ["GMAIL_CLIENT_SECRET"],
        "refresh_token": os.environ["GMAIL_REFRESH_TOKEN"], "grant_type": "refresh_token",
    })
    token = token_response.get("access_token")
    if not token:
        raise ProbeError("gmail_token_missing")
    gmail_headers = {"Authorization": f"Bearer {token}"}
    report["stage"] = "gmail_read_preflight"
    # Check actual read access before sending, without logging inbox metadata.
    request_json(GMAIL_URL + "/messages?maxResults=1", headers=gmail_headers)
    report["configuration"] = "gmail_read_verified"
    started = observe_since if observe_since is not None else time.time()
    report["started_at"] = datetime.fromtimestamp(started, timezone.utc).isoformat()
    if observe_since is None:
        receipt.parent.mkdir(parents=True, exist_ok=True)
        try:
            with receipt.open("x") as handle:
                handle.write("send_reserved\n")
        except FileExistsError:
            raise ProbeError("duplicate_send_prevented") from None
        report["stage"] = "signup_request"
        request_with_cli(alias, run_id)
        report["queue_acknowledged"] = True
    report["stage"] = "observe_provider_and_inbox"
    brevo_key = os.environ.get("BREVO_API_KEY")
    report["provider_acceptance"] = "pending" if brevo_key else "unavailable_missing_event_credentials"
    report["inbox_arrival"] = "pending"
    deadline = time.monotonic() + DEADLINE_SECONDS
    while time.monotonic() < deadline:
        if brevo_key and report["provider_acceptance"] == "pending":
            try:
                events = request_json(BREVO_URL + "?" + urlencode({"email": alias, "event": "requests", "days": 1, "limit": 50}), headers={"api-key": brevo_key})
                if any(acceptance_matches(event, alias, started) for event in events.get("events", [])):
                    report["provider_acceptance"] = "observed"
            except ProbeError as exc:
                report["provider_acceptance"] = "error:" + str(exc)
        if report["inbox_arrival"] == "pending":
            try:
                listing = request_json(GMAIL_URL + "/messages?" + urlencode({"q": f"to:{alias} after:{int(started) - 10}", "includeSpamTrash": "true", "maxResults": 10}), headers=gmail_headers)
                for item in listing.get("messages", []):
                    message = request_json(GMAIL_URL + "/messages/" + item["id"] + "?format=metadata&metadataHeaders=To&metadataHeaders=Subject", headers=gmail_headers)
                    if message_matches(message, alias, started):
                        report["inbox_arrival"] = "observed"
                        received = int(message["internalDate"]) / 1000
                        report["inbox_received_at"] = datetime.fromtimestamp(received, timezone.utc).isoformat()
                        report["inbox_received_within_deadline"] = received <= started + DEADLINE_SECONDS
                        break
            except ProbeError as exc:
                report["inbox_arrival"] = "error:" + str(exc)
        if report["inbox_arrival"] != "pending" and report["provider_acceptance"] != "pending":
            break
        time.sleep(POLL_SECONDS)
    for stage in ("provider_acceptance", "inbox_arrival"):
        if report[stage] == "pending":
            report[stage] = "timeout"
    # Actual expected inbox delivery proves the end-to-end path. Independent
    # provider events are diagnostics, not an extra credential requirement.
    report["passed"] = report["inbox_arrival"] == "observed" and report.get("inbox_received_within_deadline", False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--observe-since", type=float, help="Read-only recheck of this alias since an existing attempt's Unix timestamp; never sends")
    parser.add_argument("--dev-host", action="store_true", required=True, help="Explicit dev-server-only live health layer")
    args = parser.parse_args()
    report = {"passed": False, "queue_acknowledged": False, "provider_acceptance": "not_attempted", "inbox_arrival": "not_attempted", "execution_surface": "dev_host_global_cli", "cleanup": "no_account_created; isolated_cli_state_removed; scoped_cache_keys_expire; inbox_readonly"}
    try:
        require_dev_host()
        # Reuse the established local configuration reader; never move secrets
        # from GitHub or persist them into the global CLI login.
        from run_tests import _read_env_file, _get_env
        configured = _read_env_file()
        for name in (*GMAIL_SETTINGS, "BREVO_API_KEY", "E2E_SIGNUP_INVITE_CODE", "SIGNUP_TEST_INVITE_CODE"):
            if not os.environ.get(name):
                value = _get_env(name, configured)
                if value:
                    os.environ[name] = value
        run_probe(args.run_id, args.receipt, report, args.observe_since)
    except ProbeError as exc:
        report["error"] = str(exc)
    except Exception:
        # Never emit exception payloads: upstream values can contain private mail.
        report["error"] = "unexpected_probe_error"
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
