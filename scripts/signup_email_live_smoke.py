#!/usr/bin/env python3
"""Bounded, opt-in live-dev signup email health check (engineering tooling).

Calls the existing first-party signup route; never completes registration.
Keeps OAuth tokens, recipient aliases, message bodies and codes in memory.
Reports queue acknowledgement, Brevo acceptance and inbox arrival separately.
See docs/architecture/signup-email-live-smoke.md for scheduling and boundaries.
"""

import argparse
import base64
import hashlib
import json
import os
import re
import time
from datetime import datetime, timezone
from email.utils import getaddresses
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

API_URL = "https://api.dev.openmates.org"
APP_URL = "https://app.dev.openmates.org"
GMAIL_URL = "https://gmail.googleapis.com/gmail/v1/users/me"
BREVO_URL = "https://api.brevo.com/v3/smtp/statistics/events"
POLL_SECONDS = 5
HTTP_TIMEOUT = 10
DEADLINE_SECONDS = 120
SUBJECT = "Confirm your email address"
GMAIL_SETTINGS = ("GMAIL_CLIENT_ID", "GMAIL_CLIENT_SECRET", "GMAIL_REFRESH_TOKEN", "GMAIL_TEST_ADDRESS")


class ProbeError(Exception):
    """Only static, safe stage/status identifiers may leave an HTTP boundary."""


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
            and SUBJECT.lower() in headers.get("subject", "").lower())


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


def run_probe(run_id, receipt, report):
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
    receipt.parent.mkdir(parents=True, exist_ok=True)
    try:
        with receipt.open("x") as handle:
            handle.write("send_reserved\n")
    except FileExistsError:
        raise ProbeError("duplicate_send_prevented") from None
    started = time.time()
    report["started_at"] = datetime.fromtimestamp(started, timezone.utc).isoformat()
    report["stage"] = "signup_request"
    response = request_json(API_URL + "/v1/auth/request_confirm_email_code", headers={"Origin": APP_URL}, data={
        "email": alias, "hashed_email": base64.b64encode(hashlib.sha256(alias.encode()).digest()).decode(),
        "invite_code": os.environ.get("E2E_SIGNUP_INVITE_CODE", ""), "language": "en", "darkmode": False,
    })
    if response.get("success") is not True:
        raise ProbeError("signup_request_rejected")
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
                        break
            except ProbeError as exc:
                report["inbox_arrival"] = "error:" + str(exc)
        if report["inbox_arrival"] != "pending" and report["provider_acceptance"] != "pending":
            break
        time.sleep(POLL_SECONDS)
    for stage in ("provider_acceptance", "inbox_arrival"):
        if report[stage] == "pending":
            report[stage] = "timeout"
    report["passed"] = report["provider_acceptance"] == report["inbox_arrival"] == "observed"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    report = {"passed": False, "queue_acknowledged": False, "provider_acceptance": "not_attempted", "inbox_arrival": "not_attempted", "source_commit": os.environ.get("GITHUB_SHA", "local"), "cleanup": "no_account_created; scoped_cache_keys_expire; inbox_readonly"}
    try:
        run_probe(args.run_id, args.receipt, report)
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
