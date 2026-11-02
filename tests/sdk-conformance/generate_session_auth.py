#!/usr/bin/env python3
"""Generate synthetic auth transcript fixtures from canonical crypto vectors.

Development tooling only. No account, SDK or product requests are performed.
"""

from __future__ import annotations
from copy import deepcopy
import base64
import hashlib
import hmac
import json
from pathlib import Path
import struct

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "packages/openmates-rust/tests/crypto_fixtures/account.json"
OUTPUT = Path(__file__).with_name("fixtures") / "session-auth.json"


def build() -> dict:
    known = json.loads(SOURCE.read_text())
    salt = base64.b64decode(known["password_v2_salt"])
    auth = base64.urlsafe_b64decode(known["auth_key_v2"] + "=")
    account = {
        "email": known["email"],
        "input_email": "  USER@Example.com  ",
        "password": known["password_v2"],
        "hashed_email": base64.b64encode(
            hashlib.sha256(known["email"].encode()).digest()
        ).decode(),
        "email_key": known["email_key"],
        "salt": known["password_v2_salt"],
        "key_iv": known["iv"],
        "encrypted_key": known["password_v2_wrapped_master"],
        "master_key": known["legacy_master"],
        "owner_id": "11111111-1111-4111-8111-111111111111",
    }
    # RFC6238 SHA1/HOTP truncation at T=59, period30, using the public RFC key;
    # six digits match ordinary OTP input (the RFC appendix prints eight).
    secret = b"12345678901234567890"
    digest = hmac.new(secret, struct.pack(">Q", 59 // 30), hashlib.sha1).digest()
    offset = digest[-1] & 15
    otp = str(
        (int.from_bytes(digest[offset : offset + 4], "big") & 0x7FFFFFFF) % 1_000_000
    ).zfill(6)
    assert otp == "287082"
    vectors = []
    for identifier, totp, bad_body, logout_status in [
        ("password-v2-serialized-cookie-rotation", False, False, 200),
        ("password-v2-totp-challenge-and-retry", True, False, 200),
        ("rotation-headers-survive-invalid-body", False, True, 200),
        ("logout-clears-session-on-remote-failure", False, False, 503),
        ("owner-assertion-refuses-switched-cookie-before-logout", False, False, 403),
    ]:
        steps, actions = [], []

        def step(
            name,
            path,
            body,
            response=None,
            *,
            cookie=None,
            token=None,
            raw=None,
            status=200,
        ):
            headers = (
                []
                if token is None
                else [
                    [
                        "Set-Cookie",
                        f"auth_refresh_token={token}; HttpOnly; SameSite=Lax; Path=/",
                    ]
                ]
            )
            item = {
                "id": name,
                "method": "POST",
                "path": path,
                "body": body,
                "cookie": cookie,
                "expected_principal": account["owner_id"]
                if path in {"/v1/auth/session", "/v1/auth/logout"}
                else None,
                "response": {"status": status, "headers": headers},
            }
            item["response"]["json" if raw is None else "raw"] = (
                response if raw is None else raw
            )
            steps.append(item)

        attempts = [(None, False), (otp, True)] if totp else [(None, True)]
        for attempt, (code, success) in enumerate(attempts, 1):
            nonce = bytes(range(31 + attempt, 63 + attempt))
            nonce_b64 = base64.urlsafe_b64encode(nonce).decode().rstrip("=")
            proof = (
                base64.urlsafe_b64encode(
                    hmac.new(
                        auth,
                        b"openmates/password-v2/proof\0login\0" + nonce,
                        hashlib.sha256,
                    ).digest()
                )
                .decode()
                .rstrip("=")
            )
            sid = {"$ref": f"session-{attempt}"}
            step(
                f"lookup-{attempt}",
                "/v1/auth/lookup",
                {"hashed_email": account["hashed_email"]},
                {"user_email_salt": account["salt"]},
            )
            step(
                f"challenge-{attempt}",
                "/v1/auth/password-v2/challenge",
                {
                    "hashed_email": account["hashed_email"],
                    "session_id": {"$capture_uuid": f"session-{attempt}"},
                    "purpose": "login",
                },
                {"challenge_id": f"synthetic-challenge-{attempt}", "nonce": nonce_b64},
            )
            common = {
                "hashed_email": account["hashed_email"],
                "session_id": sid,
                "login_method": "password",
                "stay_logged_in": False,
                "email_encryption_key": account["email_key"],
            }
            v2 = {
                **common,
                "credential_version": 2,
                "challenge_id": f"synthetic-challenge-{attempt}",
                "password_proof": proof,
            }
            if code is not None:
                v2.update(tfa_code=code, code_type="otp")
            if not success:
                step(
                    f"totp-required-{attempt}",
                    "/v1/auth/login",
                    v2,
                    {"success": False, "tfa_required": True},
                    token="synthetic-unverified",
                )
                legacy = {
                    **common,
                    "credential_version": 1,
                    "lookup_hash": base64.b64encode(
                        hashlib.sha256(account["password"].encode() + salt).digest()
                    ).decode(),
                }
                step(
                    f"totp-legacy-probe-{attempt}",
                    "/v1/auth/login",
                    legacy,
                    {"success": False, "tfa_required": True},
                    cookie="auth_refresh_token=synthetic-unverified",
                )
                actions.append(
                    {
                        "kind": "login",
                        "tfa": code,
                        "error": "two_factor_required",
                        "snapshot": None,
                    }
                )
            else:
                user = {
                    "id": account["owner_id"],
                    "credential_version": 2,
                    "user_email_salt": account["salt"],
                    "encrypted_key": account["encrypted_key"],
                    "salt": account["salt"],
                    "key_iv": account["key_iv"],
                }
                step(
                    f"login-success-{attempt}",
                    "/v1/auth/login",
                    v2,
                    {"success": True, "ws_token": "synthetic-ws-login", "user": user},
                    token="synthetic-login-token",
                )
                actions.append(
                    {
                        "kind": "login",
                        "tfa": code,
                        "snapshot": {
                            "token": "synthetic-login-token",
                            "ws_token": "synthetic-ws-login",
                        },
                    }
                )
        final_sid = {"$ref": f"session-{len(attempts)}"}
        if bad_body:
            step(
                "rotate-invalid-body",
                "/v1/auth/session",
                {"session_id": final_sid},
                cookie="auth_refresh_token=synthetic-login-token",
                token="synthetic-rotated-1",
                raw='{"success":',
            )
            actions.append(
                {
                    "kind": "validate",
                    "error": "protocol",
                    "snapshot": {
                        "token": "synthetic-rotated-1",
                        "ws_token": "synthetic-ws-login",
                    },
                }
            )
            start, count, cookie = 2, 1, "synthetic-rotated-1"
        else:
            start, count, cookie = 1, 3, "synthetic-login-token"
        for number in range(start, start + count):
            step(
                f"rotate-{number}",
                "/v1/auth/session",
                {"session_id": final_sid},
                {
                    "success": True,
                    "client_security_capabilities": [
                        "expected-principal-v1",
                        "ws-dual-principal-v1",
                    ],
                    "ws_token": f"synthetic-ws-{number}",
                    "user": {"id": account["owner_id"]},
                },
                cookie=f"auth_refresh_token={cookie}",
                token=f"synthetic-rotated-{number}",
            )
            cookie = f"synthetic-rotated-{number}"
        if logout_status == 403:
            # Model an ambient/received cookie changing after a fresh owner-A
            # proof. The client must retain intended A, never follow cookie B.
            steps[-1]["response"]["headers"] = [
                [
                    "Set-Cookie",
                    "auth_refresh_token=synthetic-owner-b; HttpOnly; SameSite=Lax; Path=/",
                ]
            ]
            cookie = "synthetic-owner-b"
        actions.append(
            {
                "kind": "validate_concurrently",
                "count": count,
                "snapshot": {
                    "token": cookie,
                    "ws_token": f"synthetic-ws-{start + count - 1}",
                },
            }
        )
        step(
            "logout",
            "/v1/auth/logout",
            {},
            {"success": True}
            if logout_status == 200
            else (
                {"detail": {"error": "session_principal_mismatch"}}
                if logout_status == 403
                else {"detail": "synthetic-private-server-diagnostic"}
            ),
            cookie=f"auth_refresh_token={cookie}",
            status=logout_status,
        )
        if logout_status == 403:
            steps[-1]["authenticated_principal"] = (
                "22222222-2222-4222-8222-222222222222"
            )
            steps[-1]["blocked_effect"] = "logout"
        action = {"kind": "logout", "snapshot": None}
        if logout_status != 200:
            action["error"] = "forbidden" if logout_status == 403 else "offline"
        actions.append(action)
        vectors.append(
            {
                "id": identifier,
                "account": account,
                "app_origin": "https://app.example.invalid",
                "totp": {
                    "secret_b32": base64.b32encode(secret).decode(),
                    "unix_seconds": 59,
                    "period": 30,
                    "digits": 6,
                    "code": otp,
                },
                "steps": steps,
                "actions": actions,
            }
        )
    denied = deepcopy(
        next(
            v
            for v in vectors
            if v["id"] == "owner-assertion-refuses-switched-cookie-before-logout"
        )
    )
    denied["id"] = "closed-owner-mismatch-revokes-current-credentials"
    denied["steps"][-1]["path"] = "/v1/auth/session"
    denied["steps"][-1]["body"] = deepcopy(denied["steps"][-2]["body"])
    denied["steps"][-1]["blocked_effect"] = "session-post-auth-publication"
    denied["actions"][-1] = {"kind": "validate", "snapshot": None, "error": "expired"}
    denied["actions"].append({"kind": "logout", "snapshot": None})
    vectors.append(denied)
    preference_vectors = []
    for original_id in [
        "password-v2-serialized-cookie-rotation",
        "password-v2-totp-challenge-and-retry",
    ]:
        original = next(v for v in vectors if v["id"] == original_id)
        for preference in [False, True]:
            variant = deepcopy(original)
            variant["id"] = original_id + "-stay-logged-in-" + str(preference).lower()
            for action in variant["actions"]:
                if action["kind"] == "login":
                    action["stay_logged_in"] = preference
            for step in variant["steps"]:
                if step["path"] == "/v1/auth/login":
                    step["body"]["stay_logged_in"] = preference
            preference_vectors.append(variant)
    vectors.extend(preference_vectors)
    # Independent PBKDF2-HMAC-SHA256(100000)/AES-GCM wrapper for the existing
    # public v2 password/salt, public IV and public legacy_master fixture. The
    # derivation is independently checked by test_session_auth.py. No account
    # enrollment, protocol or KDF parameter changes are involved.
    compatibility_wrapper = (
        "/er9SL0bhcVDwhAj5BF0DifNs6u2bf30yh701tfXO8Y98hTpWNkMQJJIKX5hlcjL"
    )
    legacy_vectors = []
    for source in preference_vectors:
        variant = deepcopy(source)
        variant["id"] += "-v1-success"
        index = next(
            i
            for i, s in enumerate(variant["steps"])
            if s["id"].startswith("login-success-")
        )
        failed = variant["steps"][index]
        success = deepcopy(failed)
        failed["id"] += "-v2-refused"
        failed["response"] = {"status": 200, "headers": [], "json": {"success": False}}
        success["id"] += "-v1-fallback"
        success["body"].pop("password_proof")
        success["body"].pop("challenge_id")
        success["body"]["credential_version"] = 1
        success["body"]["lookup_hash"] = base64.b64encode(
            hashlib.sha256(account["password"].encode() + salt).digest()
        ).decode()
        success["response"]["json"]["user"].update(
            credential_version=1, encrypted_key=compatibility_wrapper
        )
        variant["steps"].insert(index + 1, success)
        legacy_vectors.append(variant)
    vectors.extend(legacy_vectors)
    return {
        "schema_version": 1,
        "provenance": "Synthetic public fixtures only. Account Argon2/HKDF/AES constants copied from packages/openmates-rust/tests/crypto_fixtures/account.json; fresh proof nonces/HMAC independently computed by Python hashlib/hmac. OTP uses RFC6238 public SHA1 key/time, truncated to6 digits. HTTP transcripts are in-process unit mocks; no product account or inference requests.",
        "capabilities": {
            "session.password-totp-rotation.v1": {
                "vectors": vectors,
                "required_checks": [
                    "omitted/default false, explicit false and true server preference retained across v1 probes and TFA retry; no local persistence change",
                    "actual Rust/NAPI/PyO3 password-v2 proof and wrapped-master-key open",
                    "normalized email and fresh per-attempt session/challenge binding",
                    "TOTP required refusal followed by supplied OTP success",
                    "serialized concurrent refresh cookie chain",
                    "known principal assertion retained across changed cookie and protected logout refusal",
                    "closed owner mismatch revokes current credentials and publication in all3 real adapters",
                    "rotation headers retained after invalid response body",
                    "logout clears local session even on remote error",
                    "no plaintext password/master key in request or diagnostic output",
                ],
            }
        },
    }


if __name__ == "__main__":
    OUTPUT.write_text(json.dumps(build(), indent=2) + "\n")
