#!/usr/bin/env python3
"""
Live first-party authentication-method capability contract check.

The script logs in through the existing CLI test-account helper, reads only the
resulting local test session cookies, and never prints credentials or cookies.
It verifies authenticated, unauthenticated, and removed legacy-route behavior.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
from urllib import request as urllib_request
from urllib.error import HTTPError


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_API_URL = "https://api.dev.openmates.org"


class AuthMethodsSmokeError(RuntimeError):
    pass


def _request_status(api_url: str, path: str, cookie: str | None = None) -> tuple[int, dict]:
    headers = {"Accept": "application/json"}
    if cookie:
        headers["Cookie"] = cookie
    request = urllib_request.Request(f"{api_url.rstrip('/')}{path}", headers=headers)
    try:
        with urllib_request.urlopen(request, timeout=30) as response:
            return response.status, json.loads(response.read().decode("utf-8") or "{}")
    except HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(body or "{}")
        except json.JSONDecodeError:
            parsed = {}
        return error.code, parsed


def _login_and_read_cookie(api_url: str) -> str:
    result = subprocess.run(
        ["node", "scripts/openmates_cli_test_account.mjs", "login", "--api-url", api_url],
        cwd=REPO_ROOT,
        text=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        check=False,
        timeout=180,
    )
    if result.returncode != 0:
        raise AuthMethodsSmokeError("CLI test-account login failed")

    session_path = Path.home() / ".openmates" / "session.json"
    session = json.loads(session_path.read_text(encoding="utf-8"))
    cookies = session.get("cookies") or {}
    cookie = "; ".join(f"{key}={value}" for key, value in cookies.items() if isinstance(value, str))
    if not cookie:
        raise AuthMethodsSmokeError("CLI test-account session has no cookies")
    return cookie


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the core auth-method capability route")
    parser.add_argument("--api-url", default=DEFAULT_API_URL)
    args = parser.parse_args()

    unauthenticated_status, _ = _request_status(args.api_url, "/v1/auth/methods")
    if unauthenticated_status != 401:
        raise AuthMethodsSmokeError(f"Unauthenticated request returned HTTP {unauthenticated_status}, expected 401")

    cookie = _login_and_read_cookie(args.api_url)
    authenticated_status, capabilities = _request_status(args.api_url, "/v1/auth/methods", cookie)
    if authenticated_status != 200:
        raise AuthMethodsSmokeError(f"Authenticated request returned HTTP {authenticated_status}, expected 200")
    expected_fields = {"has_passkey", "has_2fa", "has_password", "has_recovery_key"}
    if set(capabilities) != expected_fields or not all(isinstance(capabilities[field], bool) for field in expected_fields):
        raise AuthMethodsSmokeError("Capability response did not contain exactly four boolean fields")

    legacy_status, _ = _request_status(args.api_url, "/v1/payments/user-auth-methods", cookie)
    if legacy_status != 404:
        raise AuthMethodsSmokeError(f"Legacy payment route returned HTTP {legacy_status}, expected 404")

    print(json.dumps({"ok": True, "authenticated_status": 200, "unauthenticated_status": 401, "legacy_status": 404}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
