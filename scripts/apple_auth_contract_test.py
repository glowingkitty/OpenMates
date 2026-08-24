#!/usr/bin/env python3
"""Live Apple first-party authentication contract probe.

Credentials are loaded only from the existing OPENMATES_TEST_ACCOUNT convention.
The probe retains hashes, session cookies, OTPs, and tokens in memory and emits
only assertion names and sanitized failure classes.
"""

from __future__ import annotations

# contract-test-file: infrastructure

import argparse
import http.cookiejar
import json
import os
import sys
import urllib.request
import urllib.parse
import uuid
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from verify_test_account_login import (  # noqa: E402
    AccountLoginError,
    derive_email_encryption_key,
    generate_totp,
    hash_email,
    hash_lookup_key,
    load_test_account,
)


DEFAULT_API = "https://api.dev.openmates.org"
DEFAULT_ORIGIN = "https://app.dev.openmates.org"
NATIVE_HEADERS = {
    "User-Agent": "OpenMates-Apple/contract",
    "X-OpenMates-Client": "ios",
    "X-OpenMates-Bundle-ID": "org.openmates.app",
}
LOOKUP_PUBLIC_KEYS = {"login_method", "available_login_methods", "user_email_salt", "tfa_enabled", "stay_logged_in"}
SECRET_RESPONSE_KEYS = {"refresh_token", "access_token", "encrypted_master_key", "key_iv", "salt", "password", "otp_key", "prf"}


class ContractFailure(RuntimeError):
    """A sanitized, visible auth contract failure."""


def require_https(api_url: str) -> None:
    parsed = urllib.parse.urlparse(api_url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ContractFailure("credential-bearing contract probes require an https API URL")


def _request(opener: urllib.request.OpenerDirector, api: str, path: str, body: dict[str, Any], *, headers: dict[str, str], timeout: float) -> tuple[int, dict[str, Any]]:
    require_https(api)
    request = urllib.request.Request(api.rstrip("/") + path, data=json.dumps(body).encode("utf-8"), headers={"Accept": "application/json", "Content-Type": "application/json", **headers}, method="POST")
    try:
        with opener.open(request, timeout=timeout) as response:
            raw, status = response.read().decode("utf-8", errors="replace"), response.status
    except urllib.error.HTTPError as exc:
        raw, status = exc.read().decode("utf-8", errors="replace"), exc.code
    try:
        payload = json.loads(raw or "{}")
    except json.JSONDecodeError:
        payload = {}
    return int(status), payload if isinstance(payload, dict) else {}


def _assert_no_secrets(payload: dict[str, Any], label: str) -> None:
    if SECRET_RESPONSE_KEYS.intersection(payload):
        raise ContractFailure(f"{label} exposed a forbidden secret boundary field")


def run(api: str, *, slot: int, timeout: float) -> dict[str, Any]:
    require_https(api)
    credentials = load_test_account(slot, allow_base_fallback=True)
    if credentials is None:
        raise ContractFailure("configured test-account credentials are incomplete")
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    existing_hash = hash_email(credentials.email)
    missing_hash = hash_email(f"apple-contract-missing-{uuid.uuid4()}@invalid.example")
    native_lookup = {"hashed_email": existing_hash, "stay_logged_in": False}
    status, existing = _request(opener, api, "/v1/auth/lookup", native_lookup, headers=NATIVE_HEADERS, timeout=timeout)
    if status != 200 or set(existing) != LOOKUP_PUBLIC_KEYS:
        raise ContractFailure("native lookup did not return the exact generic public shape")
    _assert_no_secrets(existing, "lookup")
    missing_status, missing = _request(opener, api, "/v1/auth/lookup", {"hashed_email": missing_hash, "stay_logged_in": False}, headers=NATIVE_HEADERS, timeout=timeout)
    repeat_status, repeated_missing = _request(opener, api, "/v1/auth/lookup", {"hashed_email": missing_hash, "stay_logged_in": False}, headers=NATIVE_HEADERS, timeout=timeout)
    if missing_status != 200 or repeat_status != 200 or set(missing) != LOOKUP_PUBLIC_KEYS or missing != repeated_missing:
        raise ContractFailure("missing-account lookup did not preserve stable generic decoy semantics")
    for bad_headers in ({}, {"Origin": "https://untrusted.invalid"}):
        denied, _ = _request(opener, api, "/v1/auth/lookup", native_lookup, headers=bad_headers, timeout=timeout)
        if denied != 403:
            raise ContractFailure("missing or unauthorized first-party identity was accepted")
    salt = existing.get("user_email_salt")
    if not isinstance(salt, str) or not salt:
        raise ContractFailure("existing lookup did not return a usable opaque salt")
    login = {"hashed_email": existing_hash, "lookup_hash": hash_lookup_key(credentials.password, salt), "email_encryption_key": derive_email_encryption_key(credentials.email, salt), "session_id": str(uuid.uuid4()), "stay_logged_in": False}
    status, response = _request(opener, api, "/v1/auth/login", login, headers=NATIVE_HEADERS, timeout=timeout)
    if status != 200 or response.get("success") is not True:
        raise ContractFailure("native password login was rejected")
    if response.get("tfa_required") is True:
        login.update({"tfa_code": generate_totp(credentials.otp_key), "code_type": "otp"})
        status, response = _request(opener, api, "/v1/auth/login", login, headers=NATIVE_HEADERS, timeout=timeout)
    if status != 200 or response.get("success") is not True or not isinstance(response.get("ws_token"), str):
        raise ContractFailure("password plus OTP did not converge on a WebSocket session")
    _assert_no_secrets(response, "login")
    session_status, session = _request(opener, api, "/v1/auth/session", {"session_id": login["session_id"]}, headers=NATIVE_HEADERS, timeout=timeout)
    if session_status != 200 or session.get("success") is not True or not isinstance(session.get("ws_token"), str):
        raise ContractFailure("native session lifecycle did not return an active short-lived WebSocket token")
    _assert_no_secrets(session, "session")
    passkey_status, passkey = _request(opener, api, "/v1/auth/passkey/assertion/initiate", {"hashed_email": existing_hash}, headers=NATIVE_HEADERS, timeout=timeout)
    if passkey_status != 200 or passkey.get("success") is not True or not isinstance(passkey.get("rp"), dict) or passkey.get("userVerification") not in {"required", "preferred"}:
        raise ContractFailure("native passkey challenge did not preserve relying-party or user-verification shape")
    extensions = passkey.get("extensions")
    if not isinstance(extensions, dict) or "prf" not in extensions:
        raise ContractFailure("native passkey challenge did not request the PRF extension")
    _assert_no_secrets(passkey, "passkey challenge")
    return {"status": "passed", "checks": ["stable_generic_lookup", "native_identity_accepted", "unauthorized_identity_rejected", "password_otp_session_convergence", "wrapped_key_and_raw_token_boundary", "passkey_rp_prf_boundary"]}


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", default=os.environ.get("OPENMATES_API_URL", DEFAULT_API))
    parser.add_argument("--slot", type=int, default=int(os.environ.get("OPENMATES_APPLE_CONTRACT_ACCOUNT_SLOT", "14")))
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        result, code = run(args.api, slot=args.slot, timeout=args.timeout), 0
    except (AccountLoginError, ContractFailure, OSError) as exc:
        result, code = {"status": "failed", "failure_class": "auth_contract_or_transport", "error": str(exc)}, 1
    print(json.dumps(result, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
