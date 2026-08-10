#!/usr/bin/env python3
"""Verify Account Export V1 through the real OpenMates CLI.

Purpose: exercise CLI-first account export gates against dev/prod API targets.
Architecture: docs/specs/account-export-v1/spec.yml.
Security: uses the existing local CLI session or OPENMATES_API_KEY; never prints
tokens, cookies, or exported personal data.
Privacy: writes archives only under /tmp/opencode unless --output-dir is given.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile
from urllib.error import HTTPError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
CLI_DIR = ROOT / "frontend/packages/openmates-cli"
CLI_DIST = CLI_DIR / "dist/cli.js"
ARCHIVE_VERIFIER = ROOT / "scripts/verify_account_export_archive.py"
DEFAULT_DEV_API_URL = "https://api.dev.openmates.org"
DEFAULT_PROD_API_URL = "https://api.openmates.org"
DEFAULT_COMMAND_TIMEOUT_SECONDS = 180
ARCHIVE_VERIFIER_TIMEOUT_SECONDS = 600
DEFAULT_REQUIRED_DOMAINS = [
    "chats",
    "embeds",
    "referenced_uploads",
    "projects",
    "tasks",
    "plans",
    "workflows_runs",
    "billing_invoices",
    "usage",
    "profile_account_settings",
    "memories_app_settings",
    "compliance_consent_history",
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Account Export V1 CLI verification scenarios.")
    parser.add_argument("--env", choices=["dev", "prod"], default="dev")
    parser.add_argument(
        "--scenario",
        choices=["complete-default-export", "filtered-export", "partial-export", "all"],
        default="all",
    )
    parser.add_argument("--api-url", help="Override API URL.")
    parser.add_argument("--output-dir", help="Directory for generated archives.")
    args = parser.parse_args()

    api_url = (args.api_url or os.getenv("OPENMATES_API_URL") or (DEFAULT_DEV_API_URL if args.env == "dev" else DEFAULT_PROD_API_URL)).rstrip("/")
    output_root = Path(args.output_dir) if args.output_dir else Path(tempfile.mkdtemp(prefix="account-export-cli-", dir="/tmp/opencode"))
    output_root.mkdir(parents=True, exist_ok=True)

    if not CLI_DIST.exists():
        run(["npm", "run", "build"], cwd=CLI_DIR)

    scenarios = [args.scenario] if args.scenario != "all" else ["complete-default-export", "filtered-export", "partial-export"]
    results: dict[str, str] = {}
    for scenario in scenarios:
        if scenario == "complete-default-export":
            run_complete_default_export(api_url, output_root)
        elif scenario == "filtered-export":
            run_filtered_export(api_url, output_root)
        elif scenario == "partial-export":
            run_partial_export(api_url)
        results[scenario] = "passed"

    print(json.dumps({"status": "passed", "api_url": api_url, "output_dir": str(output_root), "scenarios": results}, indent=2))
    return 0


def run_complete_default_export(api_url: str, output_root: Path) -> None:
    archive_path = output_root / "complete-default-export.zip"
    result = run_cli_json(["account", "export", "--output", str(archive_path), "--json"], api_url)
    assert_export_status(result, {"complete", "partial_accepted"})
    manifest = result.get("manifest") if isinstance(result.get("manifest"), dict) else {}
    selected_domains = manifest.get("selected_domains") if isinstance(manifest, dict) else []
    for domain in ["chats", "usage", "profile_account_settings", "memories_app_settings"]:
        if domain not in selected_domains:
            raise RuntimeError(f"default export missing selected domain {domain}")
    run_archive_verifier(archive_path)
    validate_export_archive_completeness(archive_path, required_domains=DEFAULT_REQUIRED_DOMAINS)


def run_filtered_export(api_url: str, output_root: Path) -> None:
    archive_path = output_root / "filtered-export.zip"
    filters = {"chats": {"from": "2026-01-01"}, "usage": {"from": "2026-01-01"}}
    result = run_cli_json([
        "account",
        "export",
        "--domains",
        "chats,usage",
        "--filters",
        json.dumps(filters),
        "--output",
        str(archive_path),
        "--json",
    ], api_url)
    assert_export_status(result, {"complete", "partial_accepted"})
    manifest = result.get("manifest") if isinstance(result.get("manifest"), dict) else {}
    if manifest.get("selected_domains") != ["chats", "usage"]:
        raise RuntimeError(f"filtered export selected_domains mismatch: {manifest.get('selected_domains')!r}")
    if manifest.get("filters") != filters:
        raise RuntimeError(f"filtered export filters mismatch: {manifest.get('filters')!r}")
    run_archive_verifier(archive_path)
    validate_export_archive_completeness(archive_path, required_domains=["chats", "usage"])


def run_partial_export(api_url: str) -> None:
    auth = load_auth_headers(api_url)
    started = api_request(api_url, "POST", "/v1/account-exports", auth, {"domains": ["chats"], "filters": {}, "format": "zip", "include_advanced_metadata": False})
    export_id = str(started.get("export", {}).get("export_id") or "")
    if not export_id:
        raise RuntimeError("partial scenario did not receive an export_id")
    api_request(api_url, "POST", f"/v1/account-exports/{export_id}/failures", auth, {"domain": "chats", "item_id": "cli-verifier-partial", "reason": "verifier_injected_partial_failure"})

    status = run_cli_json(["account", "export", "status", export_id, "--json"], api_url)
    if status.get("export", {}).get("status") != "partial":
        raise RuntimeError(f"expected partial status before acceptance, got {status!r}")
    manifest = run_cli_json(["account", "export", "manifest", export_id, "--json"], api_url)
    report = manifest.get("manifest", {}).get("report", {})
    if report.get("partial_requires_acceptance") is not True:
        raise RuntimeError(f"partial manifest did not require acceptance: {manifest!r}")
    accepted = run_cli_json(["account", "export", "accept-partial", export_id, "--json"], api_url)
    if accepted.get("export", {}).get("status") != "partial_accepted":
        raise RuntimeError(f"expected partial_accepted after CLI accept-partial, got {accepted!r}")


def run_cli_json(args: list[str], api_url: str) -> dict:
    completed = run(["node", str(CLI_DIST), *args, "--api-url", api_url], cwd=ROOT, capture=True)
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"CLI did not return JSON for {' '.join(args)}") from exc


def run_archive_verifier(path: Path) -> None:
    source_flag = "--zip" if path.suffix == ".zip" else "--dir"
    run(
        ["python3", str(ARCHIVE_VERIFIER), source_flag, str(path), "--layout-v1", "--forbid-secrets"],
        cwd=ROOT,
        timeout=ARCHIVE_VERIFIER_TIMEOUT_SECONDS,
    )


def validate_export_archive_completeness(path: Path, *, required_domains: list[str]) -> None:
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
        domains = manifest.get("domains") if isinstance(manifest.get("domains"), dict) else {}
        for domain in required_domains:
            if domain not in domains:
                raise RuntimeError(f"manifest missing required domain {domain}")
            source = str(domains[domain].get("source") or "")
            if source == "not_yet_materialized":
                raise RuntimeError(f"domain {domain} is still a placeholder source")
            domain_path = f"domains/{domain}.json"
            if domain_path not in names:
                raise RuntimeError(f"archive missing {domain_path}")
            payload = json.loads(archive.read(domain_path).decode("utf-8"))
            actual_count = _payload_count(payload)
            expected_count = int(domains[domain].get("count") or 0)
            if actual_count != expected_count:
                raise RuntimeError(f"domain {domain} count mismatch: manifest={expected_count}, archive={actual_count}")

        if "chats" in required_domains:
            chats = json.loads(archive.read("domains/chats.json").decode("utf-8"))
            for chat in _payload_items(chats):
                if "messages" not in chat:
                    raise RuntimeError(f"chat {chat.get('id') or chat.get('chat_id')} missing messages collection")
                if "embeds" not in chat:
                    raise RuntimeError(f"chat {chat.get('id') or chat.get('chat_id')} missing embeds collection")

        if "domains/referenced_uploads.json" in names:
            uploads = json.loads(archive.read("domains/referenced_uploads.json").decode("utf-8"))
            for upload in _payload_items(uploads):
                if "s3_objects" not in upload:
                    raise RuntimeError(f"referenced upload {upload.get('id') or upload.get('embed_id')} missing s3_objects")

        if "usage" in required_domains:
            usage = json.loads(archive.read("domains/usage.json").decode("utf-8"))
            if "archives" not in usage:
                raise RuntimeError("usage domain missing S3 archive references collection")
        if "tasks" in required_domains:
            tasks = json.loads(archive.read("domains/tasks.json").decode("utf-8"))
            if "archives" not in tasks:
                raise RuntimeError("tasks domain missing S3 archive references collection")


def _payload_count(payload: dict) -> int:
    return len(_payload_items(payload)) + (len(payload.get("runs")) if isinstance(payload.get("runs"), list) else 0)


def _payload_items(payload: dict) -> list[dict]:
    items = payload.get("items")
    return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []


def assert_export_status(result: dict, allowed: set[str]) -> None:
    status = str(result.get("export", {}).get("status") or "")
    if status not in allowed:
        raise RuntimeError(f"unexpected export status {status!r}; expected one of {sorted(allowed)}")


def load_auth_headers(api_url: str) -> dict[str, str]:
    if os.getenv("OPENMATES_API_KEY"):
        return {"Authorization": f"Bearer {os.environ['OPENMATES_API_KEY']}"}
    session_path = Path(os.getenv("OPENMATES_SESSION_PATH") or Path.home() / ".openmates/session.json")
    if not session_path.exists():
        raise RuntimeError("No OPENMATES_API_KEY or local CLI session found for partial export verification")
    session = json.loads(session_path.read_text(encoding="utf-8"))
    token = (session.get("cookies") or {}).get("auth_refresh_token")
    if not token:
        raise RuntimeError("Local CLI session does not contain auth_refresh_token for partial export verification")
    return {
        "Cookie": f"auth_refresh_token={token}",
        "Origin": api_url.replace("api.", "app.", 1),
        "X-OpenMates-SDK": "cli",
        "X-OpenMates-Device-Identity": "cli:account-export-verifier",
    }


def api_request(api_url: str, method: str, path: str, headers: dict[str, str], payload: dict | None = None) -> dict:
    body = json.dumps(payload or {}).encode("utf-8") if payload is not None else None
    request = Request(
        f"{api_url}{path}",
        data=body,
        method=method,
        headers={"Accept": "application/json", "Content-Type": "application/json", **headers},
    )
    try:
        with urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8")
        raise RuntimeError(f"HTTP {exc.code} from {path}: {detail}") from exc


def run(command: list[str], *, cwd: Path, capture: bool = False, timeout: int = DEFAULT_COMMAND_TIMEOUT_SECONDS) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(command, cwd=cwd, text=True, capture_output=capture, check=False, timeout=timeout)
    if completed.returncode != 0:
        stderr = completed.stderr.strip() if completed.stderr else ""
        stdout = completed.stdout.strip() if completed.stdout else ""
        raise RuntimeError(f"Command failed ({completed.returncode}): {' '.join(command)}\n{stdout}\n{stderr}")
    return completed


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"FAIL: {error}", file=sys.stderr)
        raise SystemExit(1)
