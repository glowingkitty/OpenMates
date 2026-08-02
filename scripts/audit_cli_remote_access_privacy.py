#!/usr/bin/env python3
"""Audit the remote-access first-party encryption boundary.

The CLI must not expose ciphertext or key flags, and backend coordination must
remain an authenticated opaque-envelope relay. This source check complements
runtime crypto and authorization tests with a low-cost drift guard.
Spec: docs/specs/cli-remote-access-live-bridge/spec.yml.
"""

from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "frontend/packages/openmates-cli/src/cli.ts"
SERVICE = ROOT / "backend/core/api/app/services/project_remote_access_service.py"
ROUTES = ROOT / "backend/core/api/app/routes/projects.py"
WEBSOCKET = ROOT / "backend/core/api/app/routes/websockets.py"


def require_markers(path: Path, markers: list[str], failures: list[str]) -> str:
    if not path.is_file():
        failures.append(f"missing {path.relative_to(ROOT)}")
        return ""
    source = path.read_text(encoding="utf-8")
    for marker in markers:
        if marker not in source:
            failures.append(f"{path.relative_to(ROOT)} missing privacy marker {marker!r}")
    return source


def main() -> int:
    failures: list[str] = []
    cli = require_markers(
        CLI,
        ["assertRemoteAccessPublicFlags", "Unsupported remote-access option", "--path <folder>"],
        failures,
    )
    require_markers(
        SERVICE,
        ["encrypted_envelope", "target_device_fingerprint_hash", "MAX_ENVELOPE_BYTES", "_hash(project_id)"],
        failures,
    )
    require_markers(
        ROUTES,
        ["get_current_user", "create_project_remote_access_request", "get_project_remote_access_request_result"],
        failures,
    )
    require_markers(
        WEBSOCKET,
        ["project_remote_access_register", "project_remote_access_complete"],
        failures,
    )
    public_help = cli[cli.find("function printHelp"):]
    for forbidden in ("--encrypted-display-name", "--encrypted-metadata", "--project-key", "--session-key"):
        if forbidden in public_help:
            failures.append(f"public CLI help exposes forbidden input {forbidden}")

    if failures:
        for failure in failures:
            print(f"FAIL: {failure}", file=sys.stderr)
        return 1
    print("PASS CLI remote-access privacy boundary")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
