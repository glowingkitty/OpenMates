#!/usr/bin/env python3
"""Verify AI model routing REST and WebSocket contracts on the real dev API.

This gate uses configured OpenMates test accounts, authenticated settings REST,
and first-party WebSocket sessions against https://api.dev.openmates.org. It
prints only sanitized check names and counts: credentials, cookies, tokens,
ciphertext values, account IDs, and private chat contents never leave memory.
"""

from __future__ import annotations

# contract-test-file: infrastructure

import argparse
import base64
import http.cookiejar
import json
import os
import socket
import sys
import time
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

from apple_cross_client_sync_test import ContractFailure, WireWebSocket, require_https  # noqa: E402
from verify_test_account_login import (  # noqa: E402
    AccountLoginError,
    TOTP_WINDOW_OFFSETS,
    _json_detail,
    _wait_out_totp_boundary,
    derive_email_encryption_key,
    generate_totp,
    hash_email,
    hash_lookup_key,
    load_test_account,
    post_json,
)


DEFAULT_API = "https://api.dev.openmates.org"
DEFAULT_ORIGIN = "https://app.dev.openmates.org"
REST_SETTINGS_PATH = "/v1/settings/ai-model-defaults"
AUTH_LOOKUP_PATH = "/v1/auth/lookup"
AUTH_LOGIN_PATH = "/v1/auth/login"
CHAT_ID_PREFIX = "om-routing-verify"
FORBIDDEN_PLAINTEXT_RECORD_KEYS = {
    "selected_ai_model",
    "selected_model",
    "model_id",
    "model",
    "selection",
    "mode",
}


def _control_plane_root(repo_root: Path) -> Path:
    if repo_root.parent.name == ".openmates-agent-worktrees":
        return repo_root.parent.parent
    return repo_root


def _load_local_dotenv(env: dict[str, str], *, repo_root: Path | None = None) -> None:
    root = repo_root or SCRIPTS_DIR.parent
    for env_path in (root / ".env", _control_plane_root(root) / ".env"):
        if not env_path.is_file():
            continue
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            value = value.strip()
            if (value.startswith("\"") and value.endswith("\"")) or (
                value.startswith("'") and value.endswith("'")
            ):
                value = value[1:-1]
            env.setdefault(key.strip(), value)


@dataclass(frozen=True)
class AuthSession:
    opener: urllib.request.OpenerDirector
    session_id: str
    ws_token: str
    cookie: str


def _format_d_ciphertext(byte_value: int) -> str:
    return base64.b64encode(bytes([byte_value]) * 28).decode("ascii")


def _login(
    api_url: str,
    *,
    origin: str,
    slot: int,
    timeout: float,
    allow_base_fallback: bool = True,
    account_label: str = "primary",
) -> AuthSession:
    require_https(api_url)
    credentials = load_test_account(slot, allow_base_fallback=allow_base_fallback)
    if credentials is None:
        raise ContractFailure(f"configured {account_label} test-account credentials are incomplete")

    cookie_jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookie_jar))
    session_id = str(uuid.uuid4())
    normalized_email = credentials.email.strip().lower()
    hashed_email = hash_email(normalized_email)
    status, lookup = post_json(
        opener,
        api_url,
        AUTH_LOOKUP_PATH,
        {"hashed_email": hashed_email, "stay_logged_in": True},
        origin=origin,
        timeout=timeout,
    )
    if status != 200:
        raise ContractFailure(f"first-party lookup failed with status {status}")
    user_email_salt = lookup.get("user_email_salt")
    if not isinstance(user_email_salt, str) or not user_email_salt:
        raise ContractFailure("first-party lookup did not return a usable salt")

    login_body = {
        "hashed_email": hashed_email,
        "lookup_hash": hash_lookup_key(credentials.password, user_email_salt),
        "session_id": session_id,
        "email_encryption_key": derive_email_encryption_key(normalized_email, user_email_salt),
        "stay_logged_in": True,
    }
    status, login = post_json(opener, api_url, AUTH_LOGIN_PATH, login_body, origin=origin, timeout=timeout)
    if status != 200 or login.get("success") is not True:
        raise ContractFailure("first-party password login failed")

    if login.get("tfa_required") is True:
        otp_success = False
        for offset in TOTP_WINDOW_OFFSETS:
            _wait_out_totp_boundary()
            otp_body = {
                **login_body,
                "tfa_code": generate_totp(credentials.otp_key, window_offset=offset),
                "code_type": "otp",
            }
            status, login = post_json(opener, api_url, AUTH_LOGIN_PATH, otp_body, origin=origin, timeout=timeout)
            if status == 200 and login.get("success") is True and login.get("tfa_required") is not True:
                otp_success = True
                break
        if not otp_success:
            raise ContractFailure("first-party OTP login failed")

    token = login.get("ws_token")
    if not isinstance(token, str) or not token:
        raise ContractFailure("authenticated session did not provide a WebSocket token")
    cookie = "; ".join(f"{item.name}={item.value}" for item in cookie_jar)
    if not cookie:
        raise ContractFailure("authenticated session did not provide an HTTP-only cookie")
    return AuthSession(opener=opener, session_id=session_id, ws_token=token, cookie=cookie)


def _post_settings(
    opener: urllib.request.OpenerDirector,
    api_url: str,
    origin: str,
    body: dict[str, Any],
    *,
    timeout: float,
) -> tuple[int, dict[str, Any]]:
    return post_json(opener, api_url, REST_SETTINGS_PATH, body, origin=origin, timeout=timeout)


def _expect_success_response(status: int, payload: dict[str, Any], label: str) -> None:
    if status != 200 or payload.get("success") is not True:
        raise ContractFailure(f"{label} failed with status {status}: {_json_detail(payload)}")


def _expect_status(status: int, expected: set[int], label: str) -> None:
    if status not in expected:
        raise ContractFailure(f"{label} returned status {status}; expected one of {sorted(expected)}")


def _validate_preference_record(record: Any, *, expected_chat_id: str, expected_version: int) -> None:
    if not isinstance(record, dict):
        raise ContractFailure("chat model preference response did not contain an object record")
    if record.get("chat_id") != expected_chat_id:
        raise ContractFailure("chat model preference response escaped the requested chat boundary")
    if int(record.get("preference_v") or 0) != expected_version:
        raise ContractFailure("chat model preference version did not match the expected CAS value")
    encrypted_value = record.get("encrypted_selected_ai_model")
    if not isinstance(encrypted_value, str) or not encrypted_value:
        raise ContractFailure("chat model preference response omitted encrypted_selected_ai_model")
    if FORBIDDEN_PLAINTEXT_RECORD_KEYS.intersection(record):
        raise ContractFailure("chat model preference response exposed plaintext selection fields")


def _receive_event(ws: WireWebSocket, expected_type: str, *, timeout: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    seen_types: list[str] = []
    while time.monotonic() < deadline:
        try:
            event = ws.receive_json(max(0.1, deadline - time.monotonic()))
        except socket.timeout as exc:
            seen_summary = ",".join(seen_types[-8:]) if seen_types else "none"
            raise ContractFailure(f"timed out waiting for {expected_type}; seen event types: {seen_summary}") from exc
        event_type = event.get("type")
        if isinstance(event_type, str):
            seen_types.append(event_type)
        if event_type == "error" and expected_type != "error":
            payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
            code = payload.get("code") if isinstance(payload.get("code"), str) else "unknown_error"
            raise ContractFailure(f"server returned error while waiting for {expected_type}: {code}")
        if event_type == expected_type:
            return event
    seen_summary = ",".join(seen_types[-8:]) if seen_types else "none"
    raise ContractFailure(f"timed out waiting for {expected_type}; seen event types: {seen_summary}")


def _connect_ws(
    api_url: str,
    auth: AuthSession,
    *,
    session_id: str | None = None,
    handshake_timeout: float = 20,
) -> WireWebSocket:
    ws = WireWebSocket(
        api_url,
        query={"sessionId": session_id or auth.session_id, "token": auth.ws_token},
        cookie=auth.cookie,
        handshake_timeout=handshake_timeout,
    )
    if ws.connect() != 101:
        ws.close()
        raise ContractFailure("authenticated first-party WebSocket connection was rejected")
    return ws


def _expect_rejected_ws(api_url: str, token: str, *, timeout: float) -> None:
    ws = WireWebSocket(
        api_url,
        query={"sessionId": str(uuid.uuid4()), "token": token},
        handshake_timeout=min(timeout, 5.0),
    )
    try:
        status = ws.connect()
        if status == 101:
            raise ContractFailure("unauthorized or developer-style WebSocket access was accepted")
    except socket.timeout:
        return
    finally:
        ws.close()


def _close_ws(ws: WireWebSocket | None) -> None:
    if ws is not None:
        ws.close()


def run_rest_checks(api_url: str, *, origin: str, auth: AuthSession, timeout: float) -> list[str]:
    checks: list[str] = []
    unauthenticated = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    status, _payload = _post_settings(
        unauthenticated,
        api_url,
        origin,
        {"default_ai_model_most_demanding": "google/gemini-3.7-flash-high"},
        timeout=timeout,
    )
    _expect_status(status, {401, 403}, "unauthenticated settings REST mutation")
    checks.append("unauthenticated_rest_rejected")

    status, _payload = _post_settings(
        auth.opener,
        api_url,
        origin,
        {"default_ai_model_most_demanding": "not-a-model-id"},
        timeout=timeout,
    )
    _expect_status(status, {400}, "invalid model default REST mutation")
    checks.append("invalid_rest_model_rejected")

    status, payload = _post_settings(
        auth.opener,
        api_url,
        origin,
        {
            "default_ai_model_simple": "google/gemini-3.5-flash-lite",
            "default_ai_model_complex": "google/gemini-3.7-flash",
            "default_ai_model_most_demanding": "google/gemini-3.7-flash-high",
        },
        timeout=timeout,
    )
    _expect_success_response(status, payload, "three-tier settings REST mutation")
    checks.append("three_tier_rest_defaults_accepted")

    status, payload = _post_settings(
        auth.opener,
        api_url,
        origin,
        {"default_ai_model_most_demanding": None},
        timeout=timeout,
    )
    _expect_success_response(status, payload, "most-demanding Auto reset REST mutation")
    checks.append("most_demanding_rest_auto_reset_accepted")

    status, payload = _post_settings(
        auth.opener,
        api_url,
        origin,
        {
            "default_ai_model_simple": None,
            "default_ai_model_complex": None,
            "default_ai_model_most_demanding": None,
        },
        timeout=timeout,
    )
    _expect_success_response(status, payload, "three-tier settings REST cleanup")
    checks.append("rest_defaults_cleanup_reset_to_auto")

    return checks


def run_websocket_checks(
    api_url: str,
    *,
    origin: str,
    auth: AuthSession,
    slot: int,
    isolation_slot: int,
    timeout: float,
) -> list[str]:
    checks: list[str] = []
    chat_id = f"{CHAT_ID_PREFIX}-{uuid.uuid4().hex}"
    first_ciphertext = _format_d_ciphertext(1)
    second_ciphertext = _format_d_ciphertext(2)
    isolated_ciphertext = _format_d_ciphertext(3)
    phase = "reject developer-style WebSocket token"

    try:
        _expect_rejected_ws(api_url, "developer-api-key-is-not-a-websocket-token", timeout=timeout)
        phase = "reject missing WebSocket token"
        _expect_rejected_ws(api_url, "", timeout=timeout)
        checks.extend(["unauthorized_ws_rejected", "developer_ws_rejected"])

        phase = "connect primary authenticated WebSocket"
        primary = _connect_ws(api_url, auth, session_id=str(uuid.uuid4()), handshake_timeout=timeout)
        phase = "connect secondary authenticated WebSocket"
        secondary = _connect_ws(api_url, auth, session_id=str(uuid.uuid4()), handshake_timeout=timeout)
    except socket.timeout as exc:
        raise ContractFailure(f"{phase} timed out") from exc

    try:
        phase = "read missing chat model preference"
        primary.send_json({"type": "get_chat_model_preference", "payload": {"chat_id": chat_id}})
        initial = _receive_event(primary, "chat_model_preference", timeout=timeout)
        initial_payload = initial.get("payload") if isinstance(initial.get("payload"), dict) else {}
        if initial_payload.get("chat_id") != chat_id or initial_payload.get("preference") is not None:
            raise ContractFailure("initial chat model preference was not absent-is-Auto")
        checks.append("missing_chat_preference_is_auto")

        phase = "create encrypted chat model preference"
        primary.send_json(
            {
                "type": "update_chat_model_preference",
                "payload": {
                    "chat_id": chat_id,
                    "encrypted_selected_ai_model": first_ciphertext,
                    "expected_preference_v": 0,
                },
            }
        )
        updated = _receive_event(primary, "chat_model_preference_updated", timeout=timeout)
        updated_payload = updated.get("payload") if isinstance(updated.get("payload"), dict) else {}
        _validate_preference_record(updated_payload.get("preference"), expected_chat_id=chat_id, expected_version=1)
        synced = _receive_event(secondary, "chat_model_preference_synced", timeout=timeout)
        synced_payload = synced.get("payload") if isinstance(synced.get("payload"), dict) else {}
        _validate_preference_record(synced_payload.get("preference"), expected_chat_id=chat_id, expected_version=1)
        checks.extend(["encrypted_ws_preference_created", "same_user_ws_broadcast_delivered"])

        _close_ws(primary)
        _close_ws(secondary)
        secondary = None
        phase = "reconnect primary authenticated WebSocket after create"
        primary = _connect_ws(api_url, auth, session_id=str(uuid.uuid4()), handshake_timeout=timeout)

        phase = "reject stale chat model preference version"
        primary.send_json(
            {
                "type": "update_chat_model_preference",
                "payload": {
                    "chat_id": chat_id,
                    "encrypted_selected_ai_model": second_ciphertext,
                    "expected_preference_v": 0,
                },
            }
        )
        conflict = _receive_event(primary, "chat_model_preference_conflict", timeout=timeout)
        conflict_payload = conflict.get("payload") if isinstance(conflict.get("payload"), dict) else {}
        _validate_preference_record(conflict_payload.get("preference"), expected_chat_id=chat_id, expected_version=1)
        checks.append("stale_ws_preference_version_conflicts")

        _close_ws(primary)
        phase = "reconnect primary authenticated WebSocket before CAS update"
        primary = _connect_ws(api_url, auth, session_id=str(uuid.uuid4()), handshake_timeout=timeout)
        phase = "reconnect secondary authenticated WebSocket before CAS broadcast"
        secondary = _connect_ws(api_url, auth, session_id=str(uuid.uuid4()), handshake_timeout=timeout)

        phase = "accept chat model preference CAS update"
        primary.send_json(
            {
                "type": "update_chat_model_preference",
                "payload": {
                    "chat_id": chat_id,
                    "encrypted_selected_ai_model": second_ciphertext,
                    "expected_preference_v": 1,
                },
            }
        )
        updated_again = _receive_event(primary, "chat_model_preference_updated", timeout=timeout)
        updated_again_payload = updated_again.get("payload") if isinstance(updated_again.get("payload"), dict) else {}
        _validate_preference_record(updated_again_payload.get("preference"), expected_chat_id=chat_id, expected_version=2)
        _receive_event(secondary, "chat_model_preference_synced", timeout=timeout)
        checks.append("ws_preference_cas_update_accepted")

        _close_ws(primary)
        _close_ws(secondary)
        secondary = None
        phase = "reconnect primary authenticated WebSocket before validation checks"
        primary = _connect_ws(api_url, auth, session_id=str(uuid.uuid4()), handshake_timeout=timeout)

        phase = "reject plaintext chat model preference"
        primary.send_json(
            {
                "type": "update_chat_model_preference",
                "payload": {"chat_id": chat_id, "model": "google/gemini-3.7-flash"},
            }
        )
        plaintext_error = _receive_event(primary, "error", timeout=timeout)
        plaintext_payload = plaintext_error.get("payload") if isinstance(plaintext_error.get("payload"), dict) else {}
        if plaintext_payload.get("code") != "plaintext_chat_model_preference_forbidden":
            raise ContractFailure("plaintext chat model preference mutation returned the wrong error code")
        checks.append("plaintext_ws_preference_rejected")

        phase = "reject invalid ciphertext chat model preference"
        primary.send_json(
            {
                "type": "update_chat_model_preference",
                "payload": {"chat_id": chat_id, "encrypted_selected_ai_model": "google/gemini-3.7-flash"},
            }
        )
        invalid_error = _receive_event(primary, "error", timeout=timeout)
        invalid_payload = invalid_error.get("payload") if isinstance(invalid_error.get("payload"), dict) else {}
        if invalid_payload.get("code") != "invalid_chat_model_preference":
            raise ContractFailure("invalid ciphertext chat model preference returned the wrong error code")
        checks.append("invalid_ciphertext_ws_preference_rejected")
    except socket.timeout as exc:
        raise ContractFailure(f"{phase} timed out") from exc
    except ContractFailure as exc:
        raise ContractFailure(f"{phase}: {exc}") from exc
    finally:
        _close_ws(primary)
        _close_ws(secondary)

    if isolation_slot == slot:
        raise ContractFailure("isolation-slot must identify a different configured test account")

    phase = "login isolation account"
    try:
        isolation_auth = _login(
            api_url,
            origin=origin,
            slot=isolation_slot,
            timeout=timeout,
            allow_base_fallback=False,
            account_label="isolation",
        )
        phase = "connect isolation authenticated WebSocket"
        isolated_ws = _connect_ws(api_url, isolation_auth, handshake_timeout=timeout)
        phase = "connect primary readback WebSocket"
        primary_readback_ws = _connect_ws(api_url, auth, session_id=str(uuid.uuid4()), handshake_timeout=timeout)
    except socket.timeout as exc:
        raise ContractFailure(f"{phase} timed out") from exc

    try:
        phase = "read second-account isolated chat model preference"
        isolated_ws.send_json({"type": "get_chat_model_preference", "payload": {"chat_id": chat_id}})
        isolated_get = _receive_event(isolated_ws, "chat_model_preference", timeout=timeout)
        isolated_get_payload = isolated_get.get("payload") if isinstance(isolated_get.get("payload"), dict) else {}
        if isolated_get_payload.get("chat_id") != chat_id or isolated_get_payload.get("preference") is not None:
            raise ContractFailure("second test account could read the primary user's chat preference")

        phase = "write second-account isolated chat model preference"
        isolated_ws.send_json(
            {
                "type": "update_chat_model_preference",
                "payload": {
                    "chat_id": chat_id,
                    "encrypted_selected_ai_model": isolated_ciphertext,
                    "expected_preference_v": 0,
                },
            }
        )
        isolated_update = _receive_event(isolated_ws, "chat_model_preference_updated", timeout=timeout)
        isolated_update_payload = isolated_update.get("payload") if isinstance(isolated_update.get("payload"), dict) else {}
        _validate_preference_record(isolated_update_payload.get("preference"), expected_chat_id=chat_id, expected_version=1)

        phase = "read primary chat model preference after second-account write"
        primary_readback_ws.send_json({"type": "get_chat_model_preference", "payload": {"chat_id": chat_id}})
        primary_readback = _receive_event(primary_readback_ws, "chat_model_preference", timeout=timeout)
        primary_readback_payload = primary_readback.get("payload") if isinstance(primary_readback.get("payload"), dict) else {}
        _validate_preference_record(primary_readback_payload.get("preference"), expected_chat_id=chat_id, expected_version=2)
        checks.extend(["second_user_ws_preference_isolated", "second_user_write_does_not_mutate_primary"])
    except socket.timeout as exc:
        raise ContractFailure(f"{phase} timed out") from exc
    except ContractFailure as exc:
        raise ContractFailure(f"{phase}: {exc}") from exc
    finally:
        isolated_ws.close()
        primary_readback_ws.close()

    return checks


def run(args: argparse.Namespace) -> dict[str, Any]:
    api_url = args.target.rstrip("/")
    origin = args.origin.rstrip("/")
    require_https(api_url)
    if not args.real_auth:
        raise ContractFailure("--real-auth is required; mocked API calls do not satisfy this verifier")
    if not (args.check_rest or args.check_websocket or args.check_cli or args.check_npm or args.check_pip):
        raise ContractFailure("at least one --check-* flag is required")
    unsupported = []
    for enabled, name in ((args.check_cli, "cli"), (args.check_npm, "npm"), (args.check_pip, "pip")):
        if enabled:
            unsupported.append(name)
    if unsupported:
        raise ContractFailure(f"checks not implemented in TASK-3 verifier yet: {', '.join(unsupported)}")

    auth = _login(api_url, origin=origin, slot=args.slot, timeout=args.timeout)
    checks: list[str] = []
    if args.check_rest:
        checks.extend(run_rest_checks(api_url, origin=origin, auth=auth, timeout=args.timeout))
    if args.check_websocket:
        checks.extend(
            run_websocket_checks(
                api_url,
                origin=origin,
                auth=auth,
                slot=args.slot,
                isolation_slot=args.isolation_slot,
                timeout=args.timeout,
            )
        )
    return {
        "status": "passed",
        "target": api_url,
        "access_model": "first-party client surface only",
        "auth": "real configured test-account session",
        "checks": checks,
        "checks_passed": len(checks),
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", "--api", dest="target", default=os.environ.get("OPENMATES_API_URL", DEFAULT_API))
    parser.add_argument("--origin", default=os.environ.get("PLAYWRIGHT_TEST_BASE_URL", DEFAULT_ORIGIN))
    primary_slot = int(os.environ.get("OPENMATES_AI_MODEL_ROUTING_ACCOUNT_SLOT", os.environ.get("OPENMATES_TEST_ACCOUNT_SOURCE_SLOT", "1")))
    parser.add_argument("--slot", type=int, default=primary_slot)
    parser.add_argument("--isolation-slot", type=int, default=None)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--real-auth", action="store_true")
    parser.add_argument("--check-rest", action="store_true")
    parser.add_argument("--check-websocket", action="store_true")
    parser.add_argument("--check-cli", action="store_true")
    parser.add_argument("--check-npm", action="store_true")
    parser.add_argument("--check-pip", action="store_true")
    parser.add_argument("--json", action="store_true", help="Accepted for compatibility; output is always JSON.")
    args = parser.parse_args(argv)
    if args.isolation_slot is None:
        args.isolation_slot = int(os.environ.get("OPENMATES_AI_MODEL_ROUTING_ISOLATION_SLOT", "2" if args.slot != 2 else "1"))
    return args


def main(argv: list[str]) -> int:
    _load_local_dotenv(os.environ)
    args = parse_args(argv)
    try:
        result = run(args)
        code = 0
    except (AccountLoginError, ContractFailure, OSError, socket.timeout) as exc:
        result, code = {"status": "failed", "failure_class": "contract_or_transport", "error": str(exc)}, 1
    print(json.dumps(result, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
