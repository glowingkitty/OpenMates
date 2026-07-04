#!/usr/bin/env python3
"""
OpenMates VS Code extension V1 no-mutation audit.

Purpose: keep the first internal VS Code extension release read-only for local
Project access while the write/command security model matures.
Architecture: deterministic scan of extension manifest commands and bridge
message allowlists; this complements product tests and spec validation.
Security: fails if V1 exposes patch application, file writes, terminal commands,
package installs, test execution, or git mutation entry points.
"""

from __future__ import annotations

import json
import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
EXTENSION_ROOT = REPO_ROOT / "frontend" / "apps" / "vscode_extension"
PACKAGE_JSON = EXTENSION_ROOT / "package.json"
BRIDGE_TS = EXTENSION_ROOT / "src" / "bridge.ts"
CLI_TS = REPO_ROOT / "frontend" / "packages" / "openmates-cli" / "src" / "cli.ts"
REMOTE_ACCESS_TS = REPO_ROOT / "frontend" / "packages" / "openmates-cli" / "src" / "remoteAccess.ts"

FORBIDDEN_COMMAND_TERMS = (
    "apply",
    "patch",
    "write",
    "runcommand",
    "run-command",
    "terminal",
    "install",
    "runtests",
    "run-tests",
    "gitcommit",
    "gitpush",
)

FORBIDDEN_MESSAGE_TYPES = {
    "applyPatch",
    "writeFile",
    "runCommand",
    "installPackage",
    "runTests",
    "gitCommit",
    "gitPush",
}


def main() -> int:
    errors: list[str] = []
    package = json.loads(PACKAGE_JSON.read_text(encoding="utf-8"))
    command_ids = [
        command.get("command", "")
        for command in package.get("contributes", {}).get("commands", [])
    ]
    for command_id in command_ids:
        normalized = command_id.lower().replace(".", "").replace(":", "")
        if any(term in normalized for term in FORBIDDEN_COMMAND_TERMS):
            errors.append(f"Forbidden VS Code V1 command registered: {command_id}")

    bridge_source = BRIDGE_TS.read_text(encoding="utf-8")
    allowed_match = re.search(
        r"ALLOWED_WEBVIEW_MESSAGE_TYPES\s*=\s*\[(.*?)\]\s*as const",
        bridge_source,
        re.DOTALL,
    )
    if not allowed_match:
        errors.append("Could not find ALLOWED_WEBVIEW_MESSAGE_TYPES in bridge.ts")
    else:
        allowed_messages = set(re.findall(r'"([A-Za-z0-9_]+)"', allowed_match.group(1)))
        forbidden_allowed = sorted(allowed_messages & FORBIDDEN_MESSAGE_TYPES)
        if forbidden_allowed:
            errors.append(
                "Forbidden VS Code V1 bridge messages allowed: "
                + ", ".join(forbidden_allowed)
            )
    _remote_access_command_guard(errors)

    if errors:
        for error in errors:
            print(f"FAIL: {error}")
        return 1
    print("PASS: VS Code extension V1 exposes no mutation commands or bridge messages")
    return 0


def _remote_access_command_guard(errors: list[str]) -> None:
    cli_source = CLI_TS.read_text(encoding="utf-8")
    remote_source = REMOTE_ACCESS_TS.read_text(encoding="utf-8")
    remote_access_handler = _extract_between(
        cli_source,
        "async function handleRemoteAccess",
        "function parsePositiveIntegerFlag",
    )
    forbidden_subcommands = (
        "apply",
        "patch",
        "write",
        "run",
        "command",
        "terminal",
        "git",
    )
    for subcommand in forbidden_subcommands:
        help_pattern = re.compile(rf"openmates\s+remote-access\s+{re.escape(subcommand)}\b", re.IGNORECASE)
        branch_pattern = re.compile(rf"subcommand\s*===\s*[\"']{re.escape(subcommand)}[\"']")
        if help_pattern.search(cli_source) or branch_pattern.search(remote_access_handler):
            errors.append(f"Forbidden remote-access V1 subcommand found: {subcommand}")

    forbidden_exports = (
        "applyRemote",
        "writeRemote",
        "runRemoteCommand",
        "executeRemoteCommand",
    )
    for export_name in forbidden_exports:
        if export_name in remote_source:
            errors.append(f"Forbidden remote-access V1 helper found: {export_name}")


def _extract_between(source: str, start_marker: str, end_marker: str) -> str:
    start = source.find(start_marker)
    end = source.find(end_marker, start)
    if start == -1 or end == -1:
        return source
    return source[start:end]


if __name__ == "__main__":
    raise SystemExit(main())
