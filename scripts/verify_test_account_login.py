#!/usr/bin/env python3
"""Fast configured E2E account login preflight.

This script validates persistent test-account credentials through the real
OpenMates auth REST API without starting a browser or storing a CLI session.
It mirrors the web password/TOTP login payload, keeps credentials only in
process memory, and prints no passwords, OTP secrets, cookies, or tokens.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import http.cookiejar
import json
import os
import re
import struct
import sys
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from typing import Any


MAX_ACCOUNTS = 27
ACCOUNT_ID_RE = re.compile(r"^[A-Z0-9]{7}$")
DEFAULT_API_URL = "https://api.dev.openmates.org"
DEFAULT_WEB_ORIGIN = "https://app.dev.openmates.org"
TOTP_PERIOD_SECONDS = 30
TOTP_DIGITS = 6
TOTP_WINDOW_OFFSETS = (0, -1, 1, 0, -1)


@dataclass(frozen=True)
class TestAccountCredentials:
    slot: int
    email: str
    password: str
    otp_key: str


class AccountLoginError(RuntimeError):
    """Raised for sanitized account-health failures."""


def _base64_sha256(data: bytes) -> str:
    return base64.b64encode(hashlib.sha256(data).digest()).decode("ascii")


def _decode_base64(value: str, *, label: str) -> bytes:
    try:
        return base64.b64decode(value, validate=True)
    except Exception as exc:
        raise AccountLoginError(f"{label} is not valid base64") from exc


def hash_email(email: str) -> str:
    return _base64_sha256(email.strip().lower().encode("utf-8"))


def hash_lookup_key(password: str, user_email_salt_b64: str) -> str:
    salt = _decode_base64(user_email_salt_b64, label="user_email_salt")
    return _base64_sha256(password.encode("utf-8") + salt)


def derive_email_encryption_key(email: str, user_email_salt_b64: str) -> str:
    salt = _decode_base64(user_email_salt_b64, label="user_email_salt")
    return _base64_sha256(email.strip().lower().encode("utf-8") + salt)


def generate_totp(secret: str, *, for_time: int | None = None, window_offset: int = 0, digits: int = TOTP_DIGITS) -> str:
    normalized = "".join(secret.strip().upper().split())
    padded = normalized + "=" * ((8 - len(normalized) % 8) % 8)
    try:
        key = base64.b32decode(padded, casefold=True)
    except Exception as exc:
        raise AccountLoginError("otp key is not valid base32") from exc
    timestamp = int(time.time() if for_time is None else for_time)
    counter = timestamp // TOTP_PERIOD_SECONDS + window_offset
    if counter < 0:
        raise AccountLoginError("otp counter is negative")
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code_int = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(code_int % (10 ** digits)).zfill(digits)


def _json_detail(payload: dict[str, Any]) -> str:
    for key in ("message", "error", "detail"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:300]
    return "unexpected response"


def post_json(
    opener: urllib.request.OpenerDirector,
    api_url: str,
    path: str,
    body: dict[str, Any],
    *,
    origin: str,
    timeout: float,
) -> tuple[int, dict[str, Any]]:
    request = urllib.request.Request(
        api_url.rstrip("/") + path,
        data=json.dumps(body, separators=(",", ":")).encode("utf-8"),
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Origin": origin.rstrip("/"),
            "User-Agent": "OpenMates account-health preflight",
        },
        method="POST",
    )
    try:
        with opener.open(request, timeout=timeout) as response:
            raw_body = response.read().decode("utf-8", errors="replace")
            status = int(response.status)
    except urllib.error.HTTPError as exc:
        raw_body = exc.read().decode("utf-8", errors="replace")
        status = int(exc.code)
    except urllib.error.URLError as exc:
        raise AccountLoginError(f"request failed: {exc.reason}") from exc

    try:
        payload = json.loads(raw_body or "{}")
    except json.JSONDecodeError as exc:
        raise AccountLoginError(f"{path} returned non-JSON status {status}") from exc
    if not isinstance(payload, dict):
        raise AccountLoginError(f"{path} returned non-object JSON status {status}")
    return status, payload


def _expanded_account_bundle() -> dict[str, Any]:
    raw = os.environ.get("OPENMATES_TEST_ACCOUNTS_EXPANDED_JSON") or os.environ.get("EXPANDED_ACCOUNTS_JSON") or "{}"
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def load_test_account(slot: int, *, allow_base_fallback: bool) -> TestAccountCredentials | None:
    expanded = _expanded_account_bundle()
    expanded_account = expanded.get(str(slot)) if isinstance(expanded.get(str(slot)), dict) else {}
    email = os.environ.get(f"OPENMATES_TEST_ACCOUNT_{slot}_EMAIL") or str(expanded_account.get("email") or "")
    password = os.environ.get(f"OPENMATES_TEST_ACCOUNT_{slot}_PASSWORD") or str(expanded_account.get("password") or "")
    otp_key = os.environ.get(f"OPENMATES_TEST_ACCOUNT_{slot}_OTP_KEY") or str(expanded_account.get("otpKey") or "")
    if allow_base_fallback:
        email = email or os.environ.get("OPENMATES_TEST_ACCOUNT_EMAIL", "")
        password = password or os.environ.get("OPENMATES_TEST_ACCOUNT_PASSWORD", "")
        otp_key = otp_key or os.environ.get("OPENMATES_TEST_ACCOUNT_OTP_KEY", "")
    if not email or not password or not otp_key:
        return None
    return TestAccountCredentials(slot=slot, email=email, password=password, otp_key=otp_key)


def _wait_out_totp_boundary() -> None:
    seconds_into_window = int(time.time()) % TOTP_PERIOD_SECONDS
    if seconds_into_window >= 25:
        time.sleep((TOTP_PERIOD_SECONDS - seconds_into_window) + 2)


def verify_account(credentials: TestAccountCredentials, *, api_url: str, web_origin: str, timeout: float) -> dict[str, Any]:
    started = time.time()
    normalized_email = credentials.email.strip().lower()
    cookie_jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookie_jar))
    session_id = str(uuid.uuid4())

    try:
        hashed_email = hash_email(normalized_email)
        status, lookup = post_json(
            opener,
            api_url,
            "/v1/auth/lookup",
            {"hashed_email": hashed_email, "stay_logged_in": True},
            origin=web_origin,
            timeout=timeout,
        )
        if status != 200:
            raise AccountLoginError(f"lookup failed with status {status}: {_json_detail(lookup)}")
        user_email_salt = lookup.get("user_email_salt")
        if not isinstance(user_email_salt, str) or not user_email_salt:
            raise AccountLoginError("lookup did not return user_email_salt")

        login_body = {
            "hashed_email": hashed_email,
            "lookup_hash": hash_lookup_key(credentials.password, user_email_salt),
            "session_id": session_id,
            "email_encryption_key": derive_email_encryption_key(normalized_email, user_email_salt),
            "stay_logged_in": True,
        }
        status, login = post_json(opener, api_url, "/v1/auth/login", login_body, origin=web_origin, timeout=timeout)
        if status == 429:
            raise AccountLoginError("login rate limited")
        if status != 200:
            raise AccountLoginError(f"login failed with status {status}: {_json_detail(login)}")
        if login.get("success") is not True:
            raise AccountLoginError(f"login failed: {_json_detail(login)}")

        if login.get("tfa_required") is True:
            otp_success = False
            last_error = "OTP login did not succeed"
            for offset in TOTP_WINDOW_OFFSETS:
                _wait_out_totp_boundary()
                otp_body = {**login_body, "tfa_code": generate_totp(credentials.otp_key, window_offset=offset), "code_type": "otp"}
                status, login = post_json(opener, api_url, "/v1/auth/login", otp_body, origin=web_origin, timeout=timeout)
                if status == 429:
                    raise AccountLoginError("OTP login rate limited")
                if status != 200:
                    last_error = f"OTP login failed with status {status}: {_json_detail(login)}"
                    continue
                if login.get("success") is True and login.get("tfa_required") is not True:
                    otp_success = True
                    break
                last_error = f"OTP login failed: {_json_detail(login)}"
            if not otp_success:
                raise AccountLoginError(last_error)

        status, session = post_json(
            opener,
            api_url,
            "/v1/auth/session",
            {"session_id": session_id},
            origin=web_origin,
            timeout=timeout,
        )
        if status != 200 or session.get("success") is not True:
            raise AccountLoginError(f"session validation failed with status {status}: {_json_detail(session)}")
        user = session.get("user") if isinstance(session.get("user"), dict) else {}
        account_id = user.get("account_id")
        if not isinstance(account_id, str) or not ACCOUNT_ID_RE.match(account_id):
            raise AccountLoginError("Persistent E2E account is missing users.account_id")

        result = {
            "slot": credentials.slot,
            "email": credentials.email,
            "status": "passed",
            "duration_seconds": round(time.time() - started, 3),
            "account_id": account_id,
        }
        if isinstance(user.get("credits"), int):
            result["credits"] = user["credits"]
        return result
    except AccountLoginError as exc:
        return {
            "slot": credentials.slot,
            "email": credentials.email,
            "status": "failed",
            "duration_seconds": round(time.time() - started, 3),
            "error": str(exc),
        }


def parse_slots(value: str, repeated_slots: list[int] | None) -> list[int]:
    raw_values: list[str] = []
    if value:
        raw_values.extend(part.strip() for part in value.split(","))
    raw_values.extend(str(slot) for slot in repeated_slots or [])
    if not raw_values:
        return list(range(1, MAX_ACCOUNTS + 1))
    slots: list[int] = []
    for raw in raw_values:
        if not raw:
            continue
        slot = int(raw)
        if slot < 1 or slot > MAX_ACCOUNTS:
            raise argparse.ArgumentTypeError(f"slot must be between 1 and {MAX_ACCOUNTS}: {slot}")
        if slot not in slots:
            slots.append(slot)
    return slots


def verify_slots(slots: list[int], *, api_url: str, web_origin: str, timeout: float) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    allow_base_fallback = len(slots) == 1
    for slot in slots:
        started = time.time()
        credentials = load_test_account(slot, allow_base_fallback=allow_base_fallback)
        if credentials is None:
            results.append({
                "slot": slot,
                "status": "skipped",
                "duration_seconds": round(time.time() - started, 3),
                "error": "configured credentials are incomplete for this slot",
            })
            continue
        results.append(verify_account(credentials, api_url=api_url, web_origin=web_origin, timeout=timeout))
    failed = [item for item in results if item.get("status") != "passed"]
    return {
        "status": "failed" if failed else "passed",
        "accounts_checked": len(results),
        "accounts_passed": len(results) - len(failed),
        "accounts_failed": len(failed),
        "results": results,
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slots", default="", help="Comma-separated account slots; defaults to all configured slots")
    parser.add_argument("--slot", action="append", type=int, default=[], help="Account slot to validate; may be repeated")
    parser.add_argument("--api-url", default=os.environ.get("PLAYWRIGHT_TEST_API_URL") or DEFAULT_API_URL)
    parser.add_argument("--web-origin", default=os.environ.get("PLAYWRIGHT_TEST_BASE_URL") or DEFAULT_WEB_ORIGIN)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON only")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    try:
        slots = parse_slots(args.slots, args.slot)
    except (ValueError, argparse.ArgumentTypeError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, sort_keys=True))
        return 2
    result = verify_slots(slots, api_url=args.api_url.rstrip("/"), web_origin=args.web_origin.rstrip("/"), timeout=args.timeout)
    print(json.dumps(result, indent=2 if args.json else None, sort_keys=True))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
