#!/usr/bin/env python3
"""Audit OpenMates REST API exposure boundaries.

Purpose: keep Caddy reachability, OpenAPI exposure, and encryption-boundary
decisions deterministic after REST hardening changes.
Scope: static checks only; full runtime contract tests live under backend/tests
and dev-server API smoke scripts.
Usage: python3 scripts/audit_rest_api_surface.py --check-caddy-parity
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DEV_CADDY = REPO_ROOT / "deployment/dev_server/Caddyfile"
PROD_CADDY = REPO_ROOT / "deployment/prod_server/Caddyfile"
MAIN_API = REPO_ROOT / "backend/core/api/main.py"

DEV_ONLY_PUBLIC_PATHS = {
    "/v1/ideabucket",
    "/v1/ideabucket/*",
    "/v1/team-invites/*",
    "/v1/teams",
    "/v1/teams/*",
    "/v1/test-recordings",
    "/v1/test-recordings/*",
}

OPENAPI_FALSE_ROUTERS = {
    "settings.router": "sensitive account settings and security actions",
    "projects.router": "encrypted workspace project payloads",
    "user_tasks.router": "encrypted task content; safe metadata is separate",
    "user_plans.router": "encrypted plan content; safe metadata is separate",
    "ideabucket.router": "encrypted bucket content",
    "workspace_history.router": "encrypted workspace references",
    "teams.router": "membership and billing context",
}

OPENAPI_TRUE_ROUTERS = {
    "developer_metadata_api.router": "safe task/plan status metadata",
    "workflows.router": "scoped non-encrypted workflow template API",
    "account_imports.router": "approved account portability API",
    "account_exports.router": "approved account portability API",
    "sdk.router": "developer SDK bootstrap API",
    "openai_compat.router": "OpenAI-compatible developer API",
}


def _matcher_paths(caddyfile: Path, matcher: str) -> set[str]:
    pattern = re.compile(rf"^\s*@{re.escape(matcher)}\s+path\s+(.+?)(?:\s+#.*)?$")
    paths: set[str] = set()
    for line in caddyfile.read_text(encoding="utf-8").splitlines():
        match = pattern.match(line)
        if not match:
            continue
        for token in match.group(1).split():
            if token.startswith("/"):
                paths.add(token)
    return paths


def check_caddy_parity() -> list[str]:
    dev_public = _matcher_paths(DEV_CADDY, "public_api_paths")
    prod_public = _matcher_paths(PROD_CADDY, "public_api_paths")

    unexpected_dev_only = sorted(dev_public - prod_public - DEV_ONLY_PUBLIC_PATHS)
    unexpected_prod_only = sorted(prod_public - dev_public)
    errors: list[str] = []
    if unexpected_dev_only:
        errors.append(f"unexpected dev-only public API paths: {unexpected_dev_only}")
    if unexpected_prod_only:
        errors.append(f"unexpected prod-only public API paths: {unexpected_prod_only}")
    return errors


def check_public_rest_parity() -> list[str]:
    source = MAIN_API.read_text(encoding="utf-8")
    errors: list[str] = []

    for router, reason in sorted(OPENAPI_FALSE_ROUTERS.items()):
        expected = f"app.include_router({router}, include_in_schema=False)"
        if expected not in source:
            errors.append(f"{router} must stay hidden from developer OpenAPI: {reason}")

    for router, reason in sorted(OPENAPI_TRUE_ROUTERS.items()):
        expected = f"app.include_router({router}, include_in_schema=True)"
        if expected not in source:
            errors.append(f"{router} must stay in developer OpenAPI: {reason}")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Run all REST API surface checks")
    parser.add_argument("--check-caddy-parity", action="store_true")
    parser.add_argument("--check-public-rest-parity", action="store_true")
    args = parser.parse_args()

    checks = []
    if args.check or args.check_caddy_parity:
        checks.append(check_caddy_parity)
    if args.check or args.check_public_rest_parity:
        checks.append(check_public_rest_parity)
    if not checks:
        checks = [check_caddy_parity, check_public_rest_parity]

    errors = [error for check in checks for error in check()]
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1

    print("REST API surface audit passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
