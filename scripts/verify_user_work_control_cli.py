#!/usr/bin/env python3
"""Verify user work-control through the built CLI against the real dev API.

Creates a UUID-scoped Project, Plan, and Task using an isolated test-account
session. It exercises dependency, typed-proof, revision, scoped-list, and
recovery commands, never invokes any approval command, and removes its fixtures.
Output intentionally contains only operation names and cleanup status.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Any

from verify_project_remote_access_api import CLI_DIR, login_session, run


def cli(home: Path, api_url: str, args: list[str]) -> dict[str, Any]:
    session_path = home / ".openmates" / "session.json"
    before = json.loads(session_path.read_text())
    before_key = before.get("masterKeyExportedB64") or before.get("masterKeyEncrypted")
    result = subprocess.run(["node", "dist/cli.js", *args, "--api-url", api_url, "--json"], cwd=CLI_DIR, env={**os.environ, "HOME": str(home)}, text=True, capture_output=True, check=False, timeout=90)
    if result.returncode:
        raise RuntimeError(f"CLI command failed: {' '.join(args[:3])}: {result.stderr.strip()}")
    after = json.loads(session_path.read_text())
    after_key = after.get("masterKeyExportedB64") or after.get("masterKeyEncrypted")
    if before_key != after_key:
        raise RuntimeError(f"CLI command changed isolated session key material: {' '.join(args[:3])}")
    payload = json.loads(result.stdout)
    if not isinstance(payload, dict):
        raise RuntimeError("CLI did not return a JSON object")
    return payload


def _find_identifier(value: Any, key: str) -> str | None:
    if isinstance(value, dict):
        if isinstance(value.get(key), str):
            return str(value[key])
        for child in value.values():
            result = _find_identifier(child, key)
            if result:
                return result
    elif isinstance(value, list):
        for child in value:
            result = _find_identifier(child, key)
            if result:
                return result
    return None


def identifier(payload: dict[str, Any], key: str) -> str:
    result = _find_identifier(payload, key)
    if result:
        return result
    raise RuntimeError(f"CLI response did not include {key}")


def cleanup(home: Path, api_url: str, task_id: str, plan_id: str, project_id: str) -> None:
    failures: list[str] = []
    for name, identifier_value, command in (
        ("task", task_id, ["tasks", "delete", task_id, "--confirm"]),
        ("plan", plan_id, ["plans", "delete", plan_id, "--confirm"]),
        ("project", project_id, ["projects", "delete", project_id, "--confirm", project_id]),
    ):
        if not identifier_value:
            continue
        try:
            cli(home, api_url, command)
        except RuntimeError as exc:
            failures.append(f"{name} ({exc})")
    if failures:
        raise RuntimeError(f"fixture cleanup failed: {','.join(failures)}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default="https://api.dev.openmates.org")
    parser.add_argument("--slot", default=os.getenv("OPENMATES_TEST_ACCOUNT_SOURCE_SLOT"))
    parser.add_argument("--skip-build", action="store_true")
    args = parser.parse_args()
    if not args.skip_build:
        run(["npm", "run", "build"], cwd=CLI_DIR)
    with tempfile.TemporaryDirectory(prefix="openmates-work-control-cli-") as home_value, tempfile.TemporaryDirectory(prefix="openmates-work-control-recovery-") as recovery_root:
        home = Path(home_value)
        login_session(args.api_url, args.slot, home, "work-control-cli-verifier")
        suffix = uuid.uuid4().hex[:12]
        project_id = plan_id = task_id = ""
        operations: list[str] = []
        try:
            project_id = identifier(cli(home, args.api_url, ["projects", "create", f"work-control-{suffix}", "--description", "ephemeral verifier"]), "project_id")
            plan_id = identifier(cli(home, args.api_url, ["plans", "create", "--title", f"work-control-{suffix}", "--goal", "Verify encrypted work control", "--project", project_id]), "plan_id")
            task_id = identifier(cli(home, args.api_url, ["tasks", "create", "--title", f"work-control-{suffix}", "--project", project_id, "--plan", plan_id]), "task_id")
            cli(home, args.api_url, ["plans", "dependencies", "add", plan_id, "--target", f"task:{task_id}"])
            cli(home, args.api_url, ["plans", "dependencies", "list", plan_id])
            cli(home, args.api_url, ["plans", "dependencies", "remove", plan_id, "--target", f"task:{task_id}"])
            assumption = cli(home, args.api_url, ["plans", "assumptions", "create", plan_id, "--id", "proof", "--text", "typed proof", "--sub-chat", "opencode:verification", "--proof-file", "docs/specs/opencode-openmates-work-control/spec.yml:1:2", "--proof-url", "https://example.invalid/proof", "--proof-embed", "embed-proof"])
            assumption_id = identifier(assumption, "assumption_id")
            cli(home, args.api_url, ["plans", "assumptions", "update", plan_id, "--assumption", assumption_id, "--status", "checking", "--sub-chat", "opencode:verification", "--proof-file", "docs/specs/opencode-openmates-work-control/spec.yml:1:2", "--proof-url", "https://example.invalid/proof", "--proof-embed", "embed-proof"])
            cli(home, args.api_url, ["plans", "revisions", "submit-for-review", plan_id])
            cli(home, args.api_url, ["plans", "revisions", "status", plan_id])
            cli(home, args.api_url, ["plans", "revisions", "list", plan_id])
            cli(home, args.api_url, ["plans", "list", "--project", project_id])
            cli(home, args.api_url, ["tasks", "list", "--project", project_id])
            synced = cli(home, args.api_url, ["recovery", "full-sync", "--project", project_id, "--root", recovery_root])
            projection = str(synced.get("path") or Path(recovery_root) / f"{project_id}.yml")
            cli(home, args.api_url, ["recovery", "validate", "--file", projection])
            dry_run = cli(home, args.api_url, ["recovery", "restore", "--file", projection, "--project", project_id, "--dry-run"])
            if dry_run.get("conflicts"):
                raise RuntimeError("recovery dry-run unexpectedly reported conflicts")
            restored_plan_id, restored_task_id = plan_id, task_id
            cli(home, args.api_url, ["tasks", "delete", task_id, "--confirm"])
            task_id = ""
            cli(home, args.api_url, ["plans", "delete", plan_id, "--confirm"])
            plan_id = ""
            restored = cli(home, args.api_url, ["recovery", "restore", "--file", projection, "--project", project_id, "--confirm-restore"])
            if restored.get("restored") is not True:
                raise RuntimeError("recovery restore did not report semantic verification")
            plan_id, task_id = restored_plan_id, restored_task_id
            operations = ["create", "dependency_add_list_remove", "typed_proof_with_opencode_sub_chat", "revision_submit_status_list", "project_scoped_lists", "recovery_full_sync_validate_dry_run_confirm_restore_cleanup"]
        finally:
            cleanup(home, args.api_url, task_id, plan_id, project_id)
    print(json.dumps({"status": "passed", "operations": operations, "approval": "not_invoked"}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
