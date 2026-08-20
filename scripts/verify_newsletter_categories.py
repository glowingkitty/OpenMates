#!/usr/bin/env python3
"""Verify newsletter category REST semantics against a dev API.

This script uses an explicit test-account session cookie to prove the
first-party newsletter category route returns canonical categories and applies
partial PATCH updates. It refuses to auto-create a subscription by default and
restores the original category values after the mutation check.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASE_URL = "https://api.dev.openmates.org"
CANONICAL_KEYS = {"openmates_events", "software_updates"}


def _load_dotenv(env: dict[str, str]) -> None:
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
            value = value[1:-1]
        env.setdefault(key.strip(), value)


def _load_session_headers(session_path: Path) -> dict[str, str]:
    payload = json.loads(session_path.read_text(encoding="utf-8"))
    cookies = payload.get("cookies") if isinstance(payload, dict) else None
    refresh_token = cookies.get("auth_refresh_token") if isinstance(cookies, dict) else None
    if not isinstance(refresh_token, str) or not refresh_token:
        raise RuntimeError(f"test session is missing auth_refresh_token: {session_path}")
    return {
        "Cookie": f"auth_refresh_token={refresh_token}",
        "User-Agent": "OpenMates-CLI/0.1 (newsletter-category-verifier)",
        "X-OpenMates-SDK": "cli",
        "X-OpenMates-Device-Identity": "cli:newsletter-category-verifier",
    }


def _request(
    base_url: str,
    session_headers: dict[str, str],
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(
        f"{base_url.rstrip('/')}{path}",
        data=body,
        method=method,
        headers={
            **session_headers,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"{method} {path} failed with HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"{method} {path} failed: {exc.reason}") from exc


def _assert_categories(payload: dict[str, Any]) -> dict[str, bool]:
    if payload.get("success") is not True:
        raise AssertionError(f"newsletter categories response was not successful: {payload}")
    categories = payload.get("categories")
    if not isinstance(categories, dict):
        raise AssertionError(f"newsletter categories missing dict payload: {payload}")
    if set(categories) != CANONICAL_KEYS:
        raise AssertionError(f"expected only canonical categories {sorted(CANONICAL_KEYS)}, got {sorted(categories)}")
    for key, value in categories.items():
        if not isinstance(value, bool):
            raise AssertionError(f"category {key} must be bool, got {value!r}")
    return categories


def verify(base_url: str, session_path: Path, *, allow_create: bool) -> None:
    session_headers = _load_session_headers(session_path)
    initial_payload = _request(base_url, session_headers, "GET", "/v1/newsletter/categories")
    original = _assert_categories(initial_payload)
    if initial_payload.get("subscribed") is not True and not allow_create:
        raise RuntimeError("test account is not subscribed; rerun with --allow-create only for a disposable test account")

    changed = {"software_updates": not original["software_updates"]}
    try:
        patched_payload = _request(base_url, session_headers, "PATCH", "/v1/newsletter/categories", {"categories": changed})
        patched = _assert_categories(patched_payload)
        if patched["software_updates"] is not changed["software_updates"]:
            raise AssertionError("PATCH did not update software_updates")
        if patched["openmates_events"] is not original["openmates_events"]:
            raise AssertionError("PATCH changed an untouched canonical category")
    finally:
        _request(base_url, session_headers, "PATCH", "/v1/newsletter/categories", {"categories": original})


def main() -> int:
    env = dict(os.environ)
    _load_dotenv(env)
    parser = argparse.ArgumentParser(description="Verify newsletter category REST semantics against a dev API")
    parser.add_argument("--base-url", default=env.get("OPENMATES_API_URL", DEFAULT_BASE_URL))
    parser.add_argument("--session-path", default=env.get("OPENMATES_TEST_SESSION_PATH") or env.get("OPENMATES_NEWSLETTER_TEST_SESSION_PATH"))
    parser.add_argument("--allow-create", action="store_true", help="Allow PATCH to auto-create a subscription for a disposable test account")
    args = parser.parse_args()

    if not args.session_path:
        print("Missing OPENMATES_TEST_SESSION_PATH or OPENMATES_NEWSLETTER_TEST_SESSION_PATH; /v1/newsletter/categories requires a first-party session cookie, not an API key", file=sys.stderr)
        return 2

    try:
        verify(args.base_url, Path(args.session_path), allow_create=args.allow_create)
    except Exception as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, indent=2), file=sys.stderr)
        return 1
    print(json.dumps({"status": "passed", "base_url": args.base_url}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
