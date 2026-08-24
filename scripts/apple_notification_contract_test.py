#!/usr/bin/env python3
"""Live Apple APNs registration lifecycle contract probe.

The first-party HTTPS probe authenticates a reserved test account with native
Apple headers, registers then rotates opaque synthetic device tokens, and always
unregisters the final token. Credentials, cookies, tokens, device IDs, and API
response bodies stay in process memory and are never printed.
"""

from __future__ import annotations

# contract-test-file: infrastructure

import argparse
import http.cookiejar
import json
import os
import secrets
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Callable


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
DEFAULT_BUNDLE_ID = "org.openmates.app"
REGISTER_PATH = "/v1/notifications/register-device"
UNREGISTER_PATH = "/v1/notifications/unregister-device"
RequestJSON = Callable[[urllib.request.OpenerDirector, str, str, dict[str, Any], dict[str, str], str, float], tuple[int, dict[str, Any]]]


class ContractFailure(RuntimeError):
    """A sanitized, visible notification contract failure."""


def require_https(api_url: str) -> None:
    parsed = urllib.parse.urlparse(api_url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ContractFailure("credential-bearing contract probes require an https API URL")


def native_headers() -> dict[str, str]:
    return {
        "User-Agent": "OpenMates-Apple/contract",
        "X-OpenMates-Client": "ios",
        "X-OpenMates-Bundle-ID": os.environ.get("OPENMATES_IOS_BUNDLE_ID", DEFAULT_BUNDLE_ID),
    }


def request_json(
    opener: urllib.request.OpenerDirector,
    api_url: str,
    path: str,
    body: dict[str, Any],
    headers: dict[str, str],
    method: str,
    timeout: float,
) -> tuple[int, dict[str, Any]]:
    """Make one HTTPS request while retaining response data only for assertions."""
    require_https(api_url)
    request = urllib.request.Request(
        api_url.rstrip("/") + path,
        data=json.dumps(body, separators=(",", ":")).encode("utf-8"),
        headers={"Accept": "application/json", "Content-Type": "application/json", **headers},
        method=method,
    )
    try:
        with opener.open(request, timeout=timeout) as response:
            raw, status = response.read().decode("utf-8", errors="replace"), int(response.status)
    except urllib.error.HTTPError as exc:
        raw, status = exc.read().decode("utf-8", errors="replace"), int(exc.code)
    try:
        payload = json.loads(raw or "{}")
    except json.JSONDecodeError:
        payload = {}
    return status, payload if isinstance(payload, dict) else {}


def login_native(
    api_url: str,
    *,
    slot: int,
    timeout: float,
    request: RequestJSON = request_json,
) -> urllib.request.OpenerDirector:
    require_https(api_url)
    credentials = load_test_account(slot, allow_base_fallback=True)
    if credentials is None:
        raise ContractFailure("configured test-account credentials are incomplete")
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    headers = native_headers()
    hashed_email = hash_email(credentials.email)
    status, lookup = request(opener, api_url, "/v1/auth/lookup", {"hashed_email": hashed_email}, headers, "POST", timeout)
    salt = lookup.get("user_email_salt") if status == 200 else None
    if not isinstance(salt, str) or not salt:
        raise ContractFailure("native account lookup did not return a usable salt")
    login = {
        "hashed_email": hashed_email,
        "lookup_hash": hash_lookup_key(credentials.password, salt),
        "email_encryption_key": derive_email_encryption_key(credentials.email, salt),
        "session_id": str(uuid.uuid4()),
        "stay_logged_in": False,
    }
    status, response = request(opener, api_url, "/v1/auth/login", login, headers, "POST", timeout)
    if status != 200 or response.get("success") is not True:
        raise ContractFailure("native password login was rejected")
    if response.get("tfa_required") is True:
        login.update({"tfa_code": generate_totp(credentials.otp_key), "code_type": "otp"})
        status, response = request(opener, api_url, "/v1/auth/login", login, headers, "POST", timeout)
    if status != 200 or response.get("success") is not True:
        raise ContractFailure("native password plus OTP login was rejected")
    return opener


def _require_acknowledged(status: int, payload: dict[str, Any], label: str) -> None:
    if status != 200 or payload.get("success") is not True:
        keys = ",".join(sorted(str(key) for key in payload)) or "none"
        raise ContractFailure(
            f"{label} did not receive a persistence acknowledgement "
            f"(status={status}, response_keys={keys})"
        )


def run(
    api_url: str,
    *,
    slot: int,
    timeout: float,
    request: RequestJSON = request_json,
    login: Callable[..., urllib.request.OpenerDirector] = login_native,
    token_factory: Callable[[int], str] = lambda length: secrets.token_urlsafe(length),
    device_id_factory: Callable[[], str] = lambda: str(uuid.uuid4()),
) -> dict[str, Any]:
    require_https(api_url)
    opener = login(api_url, slot=slot, timeout=timeout, request=request)
    headers = native_headers()
    token_one, token_two, device_id = token_factory(48), token_factory(48), device_id_factory()
    body_one = {"token": token_one, "device_id": device_id, "platform": "apns", "environment": "sandbox"}
    body_two = {**body_one, "token": token_two}
    cleanup_error: ContractFailure | None = None
    primary_error: BaseException | None = None
    try:
        missing_identity_status, _ = request(opener, api_url, REGISTER_PATH, body_one, {}, "POST", timeout)
        if missing_identity_status != 403:
            raise ContractFailure("authenticated registration without native identity was not rejected")
        register_status, register_payload = request(opener, api_url, REGISTER_PATH, body_one, headers, "POST", timeout)
        _require_acknowledged(register_status, register_payload, "initial native registration")
        rotate_status, rotate_payload = request(opener, api_url, REGISTER_PATH, body_two, headers, "POST", timeout)
        _require_acknowledged(rotate_status, rotate_payload, "native token rotation")
    except BaseException as exc:
        primary_error = exc
    finally:
        cleanup_status, cleanup_payload = request(
            opener,
            api_url,
            UNREGISTER_PATH,
            {"token": token_two, "device_id": device_id},
            headers,
            "DELETE",
            timeout,
        )
        try:
            _require_acknowledged(cleanup_status, cleanup_payload, "native token cleanup")
        except ContractFailure as exc:
            cleanup_error = exc
    if primary_error is not None and cleanup_error is not None:
        primary_detail = str(primary_error) if isinstance(primary_error, ContractFailure) else type(primary_error).__name__
        raise ContractFailure(
            f"notification lifecycle failed: {primary_detail}; "
            f"final token cleanup also failed: {cleanup_error}"
        ) from primary_error
    if cleanup_error is not None:
        raise cleanup_error
    if primary_error is not None:
        raise primary_error
    return {
        "status": "passed",
        "checks": [
            "native_identity_required",
            "registration_acknowledged",
            "same_device_token_rotation_acknowledged",
            "rotated_token_unregistered",
        ],
    }


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
        result, code = {"status": "failed", "failure_class": "notification_contract_or_transport", "error": str(exc)}, 1
    print(json.dumps(result, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
