#!/usr/bin/env python3
"""Verify Account Import V1 through real OpenMates clients.

Purpose: exercise CLI-first and SDK account import gates against dev/prod API
targets.
Architecture: docs/specs/account-import-v1/spec.yml.
Security: uses synthetic fixtures only and never prints tokens, cookies, or
private import content.
Privacy: writes temporary import fixtures only under /tmp/opencode unless an
explicit --work-dir is provided.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
import urllib.error
import urllib.request

from sdk_cli_parity_live_smoke import _approve_pending_key_devices, _is_device_approval_error


ROOT = Path(__file__).resolve().parents[1]
CLI_DIR = ROOT / "frontend/packages/openmates-cli"
CLI_DIST = CLI_DIR / "dist/cli.js"
DEFAULT_DEV_API_URL = "https://api.dev.openmates.org"
DEFAULT_PROD_API_URL = "https://api.openmates.org"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Account Import V1 client verification scenarios.")
    parser.add_argument("--env", choices=["dev", "prod"], default="dev")
    parser.add_argument(
        "--scenario",
        choices=["direct-rest-contract", "generic-import", "npm-sdk-generic-import", "pip-sdk-generic-import", "claude-import", "chatgpt-import", "opencode-import", "npm-sdk-chatgpt-import", "npm-sdk-opencode-import", "pip-sdk-chatgpt-import", "pip-sdk-opencode-import", "openmates-v1-import", "limits-and-costs", "all"],
        default="claude-import",
    )
    parser.add_argument("--api-url", help="Override API URL.")
    parser.add_argument("--work-dir", help="Directory for generated synthetic fixtures.")
    args = parser.parse_args()

    api_url = (args.api_url or os.getenv("OPENMATES_API_URL") or (DEFAULT_DEV_API_URL if args.env == "dev" else DEFAULT_PROD_API_URL)).rstrip("/")
    should_cleanup_work_dir = args.work_dir is None
    work_dir = Path(args.work_dir) if args.work_dir else Path(tempfile.mkdtemp(prefix="account-import-cli-", dir="/tmp/opencode"))
    work_dir.mkdir(parents=True, exist_ok=True)

    run(["npm", "run", "build"], cwd=CLI_DIR)

    scenarios = [args.scenario] if args.scenario != "all" else ["direct-rest-contract", "generic-import", "npm-sdk-generic-import", "pip-sdk-generic-import"]
    results: dict[str, str] = {}
    api_key_id = ""
    try:
        sdk_key = ""
        for scenario in scenarios:
            if scenario == "direct-rest-contract":
                run_direct_rest_contract(api_url)
            elif scenario == "generic-import":
                run_generic_import(api_url, work_dir)
            elif scenario == "npm-sdk-generic-import":
                if not sdk_key:
                    api_key_id, sdk_key = create_api_key(api_url)
                run_npm_sdk_generic_import(api_url, sdk_key, api_key_id, work_dir)
            elif scenario == "pip-sdk-generic-import":
                if not sdk_key:
                    api_key_id, sdk_key = create_api_key(api_url)
                run_pip_sdk_generic_import(api_url, sdk_key, api_key_id, work_dir)
            elif scenario == "claude-import":
                run_claude_import(api_url, work_dir)
            elif scenario == "chatgpt-import":
                run_chatgpt_import(api_url, work_dir)
            elif scenario == "opencode-import":
                run_opencode_import(api_url, work_dir)
            elif scenario == "npm-sdk-chatgpt-import":
                if not sdk_key:
                    api_key_id, sdk_key = create_api_key(api_url)
                run_npm_sdk_chatgpt_import(api_url, sdk_key, api_key_id, work_dir)
            elif scenario == "npm-sdk-opencode-import":
                if not sdk_key:
                    api_key_id, sdk_key = create_api_key(api_url)
                run_npm_sdk_opencode_import(api_url, sdk_key, api_key_id, work_dir)
            elif scenario == "pip-sdk-chatgpt-import":
                if not sdk_key:
                    api_key_id, sdk_key = create_api_key(api_url)
                run_pip_sdk_chatgpt_import(api_url, sdk_key, api_key_id, work_dir)
            elif scenario == "pip-sdk-opencode-import":
                if not sdk_key:
                    api_key_id, sdk_key = create_api_key(api_url)
                run_pip_sdk_opencode_import(api_url, sdk_key, api_key_id, work_dir)
            elif scenario == "openmates-v1-import":
                run_openmates_import_preview(api_url, work_dir)
            elif scenario == "limits-and-costs":
                run_limits_preview(api_url, work_dir)
            results[scenario] = "passed"
    finally:
        if api_key_id:
            revoke_api_key(api_url, api_key_id)
        if should_cleanup_work_dir:
            shutil.rmtree(work_dir, ignore_errors=True)

    print(json.dumps({"status": "passed", "api_url": api_url, "work_dir": str(work_dir), "work_dir_deleted": should_cleanup_work_dir, "scenarios": results}, indent=2))
    return 0


def session_cookie_header() -> str:
    session_path = Path(os.getenv("OPENMATES_SESSION_PATH") or Path.home() / ".openmates/session.json")
    session = json.loads(session_path.read_text(encoding="utf-8"))
    cookies = session.get("cookies") if isinstance(session.get("cookies"), dict) else {}
    refresh_token = str(cookies.get("auth_refresh_token") or "")
    if not refresh_token:
        raise RuntimeError("Account import verifier requires an authenticated CLI session")
    return f"auth_refresh_token={refresh_token}"


def rest_json(api_url: str, method: str, path: str, payload: dict | None = None, *, authenticated: bool = True) -> tuple[int, dict]:
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    if authenticated:
        headers["Cookie"] = session_cookie_header()
    request = urllib.request.Request(
        f"{api_url}{path}",
        data=json.dumps(payload).encode("utf-8") if payload is not None else None,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8")
        return error.code, json.loads(body) if body else {}


def run_direct_rest_contract(api_url: str) -> None:
    fingerprint = hashlib.sha256(f"account-import-rest-{time.time_ns()}".encode("utf-8")).hexdigest()
    preview_payload = {
        "source": "other",
        "parser_format": "generic",
        "chat_count": 1,
        "source_fingerprints": [fingerprint],
        "estimated_tokens_by_chat": [8],
        "estimated_bytes": 64,
    }
    unauthorized_status, _ = rest_json(api_url, "POST", "/v1/account-imports/preview", preview_payload, authenticated=False)
    if unauthorized_status not in {401, 403}:
        raise RuntimeError(f"Account import unauthenticated preview returned HTTP {unauthorized_status}, expected 401/403")
    status, preview = rest_json(api_url, "POST", "/v1/account-imports/preview", preview_payload)
    if status != 200 or not isinstance(preview.get("import_id"), str):
        raise RuntimeError(f"Account import REST preview failed: HTTP {status} {redacted(preview)}")
    import_id = preview["import_id"]
    status, _ = rest_json(api_url, "POST", f"/v1/account-imports/{import_id}/confirm", {"selected_fingerprints": [fingerprint]})
    if status != 200:
        raise RuntimeError(f"Account import REST confirmation failed with HTTP {status}")
    chat = {
        "provider": "other",
        "parser_format": "generic",
        "selected_source": "other",
        "source_chat_id": "synthetic-rest-chat",
        "source_fingerprint": fingerprint,
        "title": "Synthetic REST chat",
        "messages": [{"role": "user", "content": "Synthetic REST import message.", "provider_metadata": {}, "imported_assistant_identity": None}],
        "embeds": [],
        "uploads": [],
        "provider_labels": ["other", "generic"],
        "source_metadata": {},
    }
    status, scan = rest_json(api_url, "POST", f"/v1/account-imports/{import_id}/scan", {"batch_id": "rest-scan-0", "sequence": 0, "final_batch": True, "chats": [chat]})
    if status != 200 or scan.get("status") != "acknowledged" or not isinstance(scan.get("chats"), list):
        raise RuntimeError(f"Account import REST scan failed: HTTP {status} {redacted(scan)}")
    sanitized_messages = scan["chats"][0].get("messages", [])
    status, compression = rest_json(api_url, "POST", f"/v1/account-imports/{import_id}/compress", {
        "batch_id": "rest-compress-0",
        "sequence": 0,
        "final_batch": True,
        "scan_sequence": 0,
        "source_fingerprint": fingerprint,
        "sanitized_messages": sanitized_messages,
    })
    if status != 200 or compression.get("status") != "acknowledged":
        raise RuntimeError(f"Account import REST compression failed: HTTP {status} {redacted(compression)}")
    status, metadata = rest_json(api_url, "GET", f"/v1/account-imports/{import_id}/status")
    if status != 200 or metadata.get("last_scan_sequence") != 0 or metadata.get("last_compression_sequence") != 0:
        raise RuntimeError(f"Account import REST metadata status failed: HTTP {status} {redacted(metadata)}")


def create_generic_fixture(work_dir: Path, filename: str) -> Path:
    fixture = work_dir / filename
    fixture.write_text(json.dumps({
        "id": f"generic-{time.time_ns()}",
        "title": "Synthetic generic import chat",
        "messages": [
            {"role": "user", "content": "Synthetic generic import user message."},
            {"role": "assistant", "content": "Synthetic generic import assistant message."},
        ],
    }), encoding="utf-8")
    return fixture


def run_generic_import(api_url: str, work_dir: Path) -> None:
    fixture = create_generic_fixture(work_dir, "generic-import-cli-synthetic.json")
    result = run_cli_json(["account", "import", "generic", str(fixture), "--source", "other", "--yes", "--json"], api_url)
    if result.get("source") != "other" or result.get("parser_format") != "generic":
        raise RuntimeError(f"Generic CLI import source/parser mismatch: {redacted(result)}")
    if (result.get("complete") or {}).get("status") != "complete" or (result.get("persistence") or {}).get("status") != "complete":
        raise RuntimeError(f"Generic CLI import did not complete encrypted persistence: {redacted(result)}")


def run_claude_import(api_url: str, work_dir: Path) -> None:
    fixture = work_dir / "claude-import-synthetic.json"
    fixture.write_text(json.dumps([
        {
            "uuid": "claude-cli-import-chat-1",
            "name": "Synthetic CLI import chat",
            "created_at": "2026-07-18T00:00:00Z",
            "updated_at": "2026-07-18T00:01:00Z",
            "chat_messages": [
                {"uuid": "msg-user-1", "sender": "human", "text": "Synthetic CLI import user message."},
                {"uuid": "msg-assistant-1", "sender": "assistant", "text": "Synthetic CLI import assistant message."},
            ],
        }
    ]), encoding="utf-8")
    result = run_cli_json(["account", "import", "claude", str(fixture), "--yes", "--json"], api_url)
    complete = result.get("complete") if isinstance(result.get("complete"), dict) else {}
    persistence = result.get("persistence") if isinstance(result.get("persistence"), dict) else {}
    if complete.get("status") != "complete" or int(complete.get("imported_count") or 0) < 1:
        raise RuntimeError(f"Claude import did not complete: {redacted(result)}")
    if persistence.get("status") != "complete":
        raise RuntimeError(f"Claude import encrypted persistence did not complete: {redacted(result)}")


def run_chatgpt_import(api_url: str, work_dir: Path) -> None:
    fixture = create_chatgpt_fixture(work_dir, "chatgpt-import-synthetic.zip")

    result = run_cli_json(["account", "import", "chatgpt", str(fixture), "--select", "all", "--yes", "--json"], api_url)
    parsed = result.get("parsed") if isinstance(result.get("parsed"), dict) else {}
    complete = result.get("complete") if isinstance(result.get("complete"), dict) else {}
    persistence = result.get("persistence") if isinstance(result.get("persistence"), dict) else {}
    if int(parsed.get("selected_count") or 0) != 3:
        raise RuntimeError(f"ChatGPT import did not limit selection to three chats: {redacted(result)}")
    if complete.get("status") != "complete" or int(complete.get("imported_count") or 0) != 3:
        raise RuntimeError(f"ChatGPT import did not complete three chats: {redacted(result)}")
    if persistence.get("status") != "complete":
        raise RuntimeError(f"ChatGPT import encrypted persistence did not complete: {redacted(result)}")


def create_opencode_fixture(work_dir: Path, filename: str) -> Path:
    fixture = work_dir / filename
    suffix = str(int(time.time()))
    fixture.write_text(json.dumps({
        "info": {
            "id": f"ses_opencode_import_{suffix}",
            "title": "Synthetic OpenCode import chat",
            "time": {"created": 1_785_000_000_000, "updated": 1_785_000_010_000},
        },
        "messages": [
            {
                "info": {"id": f"msg_user_{suffix}", "role": "user", "time": {"created": 1_785_000_001_000}},
                "parts": [
                    {"id": f"part_user_{suffix}", "type": "text", "text": "Synthetic OpenCode import user message."},
                    {"id": f"part_file_{suffix}", "type": "file", "filename": "private.txt", "mime": "text/plain", "url": "data:text/plain;base64,cHJpdmF0ZQ=="},
                ],
            },
            {
                "info": {"id": f"msg_assistant_{suffix}", "role": "assistant", "time": {"created": 1_785_000_002_000}},
                "parts": [
                    {"id": f"part_reasoning_{suffix}", "type": "reasoning", "text": "Synthetic reasoning must not import."},
                    {"id": f"part_assistant_{suffix}", "type": "text", "text": "Synthetic OpenCode import assistant message."},
                ],
            },
        ],
    }), encoding="utf-8")
    return fixture


def run_opencode_import(api_url: str, work_dir: Path) -> None:
    fixture = create_opencode_fixture(work_dir, "opencode-import-synthetic.json")
    result = run_cli_json(["account", "import", "opencode", str(fixture), "--yes", "--json"], api_url)
    complete = result.get("complete") if isinstance(result.get("complete"), dict) else {}
    persistence = result.get("persistence") if isinstance(result.get("persistence"), dict) else {}
    if complete.get("status") != "complete" or int(complete.get("imported_count") or 0) != 1:
        raise RuntimeError(f"OpenCode import did not complete one chat: {redacted(result)}")
    if persistence.get("status") != "complete":
        raise RuntimeError(f"OpenCode import encrypted persistence did not complete: {redacted(result)}")


def create_chatgpt_fixture(work_dir: Path, filename: str) -> Path:
    fixture = work_dir / filename
    conversations = [chatgpt_conversation(index) for index in range(1, 4)]
    with zipfile.ZipFile(fixture, "w") as archive:
        archive.writestr("ChatGPT Export/conversations.json", json.dumps(conversations))
        archive.writestr("ChatGPT Export/conversation_asset_file_names.json", json.dumps({}))
    return fixture


def create_api_key(api_url: str) -> tuple[str, str]:
    result = run_cli_json(["settings", "developers", "api-keys", "create", "account-import-sdk-verifier", "--yes", "--json"], api_url)
    key = result.get("key") if isinstance(result.get("key"), dict) else {}
    key_id = str(result.get("id") or result.get("key_id") or key.get("id") or "")
    api_key = str(result.get("api_key") or result.get("key") or "")
    if not key_id:
        raise RuntimeError(f"API key create response did not include key id: {redacted(result)}")
    if not api_key.startswith("sk-api-"):
        raise RuntimeError("API key create response did not include a usable API key")
    return key_id, api_key


def revoke_api_key(api_url: str, api_key_id: str) -> None:
    subprocess.run(
        ["node", str(CLI_DIST), "settings", "developers", "api-keys", "revoke", api_key_id, "--yes", "--json", "--api-url", api_url],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        timeout=120,
    )


def run_npm_sdk_generic_import(api_url: str, api_key: str, api_key_id: str, work_dir: Path) -> None:
    fixture = create_generic_fixture(work_dir, "generic-import-npm-sdk-synthetic.json")
    sdk_entry = (CLI_DIR / "dist/index.js").as_uri()
    code = f"""
import {{ OpenMates }} from {json.dumps(sdk_entry)};
import {{ readFileSync }} from 'node:fs';

const client = new OpenMates({{ apiKey: process.env.OPENMATES_API_KEY, apiUrl: process.env.OPENMATES_API_URL, deviceId: 'account-import-generic-sdk-npm' }});
const parsed = await client.account.parseGenericImport(readFileSync(process.env.OPENMATES_IMPORT_FIXTURE), 'generic-sdk-live.json', 'other');
if (parsed.source !== 'other' || parsed.parserFormat !== 'generic' || parsed.chats.length !== 1) throw new Error('npm SDK parsed unexpected generic result');
const result = await client.account.importChats(parsed, {{ select: 'all' }});
if (result?.complete?.status !== 'complete' || result?.persistence?.status !== 'complete') throw new Error('npm SDK generic import did not complete');
console.log(JSON.stringify({{ source: result.source, parser_format: parsed.parserFormat, imported_count: result.complete.imported_count }}));
"""
    env = {**os.environ, "OPENMATES_API_KEY": api_key, "OPENMATES_API_URL": api_url, "OPENMATES_IMPORT_FIXTURE": str(fixture)}
    try:
        run(["node", "--input-type=module", "-e", code], cwd=ROOT, capture=True, env=env)
    except RuntimeError as error:
        if not _is_device_approval_error(error):
            raise
        if not _approve_pending_key_devices(api_url, api_key_id, {"npm"}):
            raise RuntimeError("No pending npm SDK device was available to approve") from error
        run(["node", "--input-type=module", "-e", code], cwd=ROOT, capture=True, env=env)


def run_npm_sdk_chatgpt_import(api_url: str, api_key: str, api_key_id: str, work_dir: Path) -> None:
    fixture = create_chatgpt_fixture(work_dir, "chatgpt-import-npm-sdk-synthetic.zip")
    sdk_entry = (CLI_DIR / "dist/index.js").as_uri()
    code = f"""
import {{ OpenMates }} from {json.dumps(sdk_entry)};
import {{ readFileSync }} from 'node:fs';

const client = new OpenMates({{ apiKey: process.env.OPENMATES_API_KEY, apiUrl: process.env.OPENMATES_API_URL, deviceId: 'account-import-sdk-npm' }});
const parsed = await client.account.parseChatGPTImport(readFileSync(process.env.OPENMATES_IMPORT_FIXTURE), 'chatgpt-sdk-live.zip');
if (parsed.source !== 'chatgpt') throw new Error(`npm SDK parsed unexpected source ${{parsed.source}}`);
if (parsed.chats.length !== 3) throw new Error(`npm SDK parsed ${{parsed.chats.length}} chats instead of 3`);
const result = await client.account.importChats(parsed, {{ select: 'all' }});
if (result?.complete?.status !== 'complete' || result?.complete?.imported_count !== 3) throw new Error(`npm SDK import did not complete exactly 3 chats: ${{JSON.stringify({{ status: result?.complete?.status, imported: result?.complete?.imported_count }})}}`);
if (result?.persistence?.status !== 'complete') throw new Error(`npm SDK encrypted persistence status was ${{result?.persistence?.status}}`);
console.log(JSON.stringify({{ source: result.source, parsed_chats: parsed.chats.length, imported_count: result.complete.imported_count, persistence_status: result.persistence.status }}));
"""
    env = {**os.environ, "OPENMATES_API_KEY": api_key, "OPENMATES_API_URL": api_url, "OPENMATES_IMPORT_FIXTURE": str(fixture)}
    try:
        run(["node", "--input-type=module", "-e", code], cwd=ROOT, capture=True, env=env)
    except RuntimeError as error:
        if not _is_device_approval_error(error):
            raise
        approved = _approve_pending_key_devices(api_url, api_key_id, {"npm"})
        if not approved:
            raise RuntimeError("No pending npm SDK device was available to approve") from error
        run(["node", "--input-type=module", "-e", code], cwd=ROOT, capture=True, env=env)


def run_npm_sdk_opencode_import(api_url: str, api_key: str, api_key_id: str, work_dir: Path) -> None:
    fixture = create_opencode_fixture(work_dir, "opencode-import-npm-sdk-synthetic.json")
    sdk_entry = (CLI_DIR / "dist/index.js").as_uri()
    code = f"""
import {{ OpenMates }} from {json.dumps(sdk_entry)};
import {{ readFileSync }} from 'node:fs';

const client = new OpenMates({{ apiKey: process.env.OPENMATES_API_KEY, apiUrl: process.env.OPENMATES_API_URL, deviceId: 'account-import-opencode-sdk-npm' }});
const parsed = await client.account.parseOpenCodeImport(readFileSync(process.env.OPENMATES_IMPORT_FIXTURE), 'opencode-sdk-live.json');
if (parsed.source !== 'opencode' || parsed.chats.length !== 1) throw new Error(`npm SDK parsed unexpected OpenCode result`);
if (parsed.chats[0].uploads.length !== 0) throw new Error(`npm SDK retained OpenCode file payloads`);
const result = await client.account.importChats(parsed, {{ select: 'all' }});
if (result?.complete?.status !== 'complete' || result?.complete?.imported_count !== 1) throw new Error(`npm SDK OpenCode import did not complete exactly one chat`);
console.log(JSON.stringify({{ source: result.source, parsed_chats: parsed.chats.length, imported_count: result.complete.imported_count }}));
"""
    env = {**os.environ, "OPENMATES_API_KEY": api_key, "OPENMATES_API_URL": api_url, "OPENMATES_IMPORT_FIXTURE": str(fixture)}
    try:
        run(["node", "--input-type=module", "-e", code], cwd=ROOT, capture=True, env=env)
    except RuntimeError as error:
        if not _is_device_approval_error(error):
            raise
        approved = _approve_pending_key_devices(api_url, api_key_id, {"npm"})
        if not approved:
            raise RuntimeError("No pending npm SDK device was available to approve") from error
        run(["node", "--input-type=module", "-e", code], cwd=ROOT, capture=True, env=env)


def run_pip_sdk_chatgpt_import(api_url: str, api_key: str, api_key_id: str, work_dir: Path) -> None:
    fixture = create_chatgpt_fixture(work_dir, "chatgpt-import-pip-sdk-synthetic.zip")
    code = """
from pathlib import Path
from openmates import OpenMates
import json
import os

client = OpenMates(api_key=os.environ["OPENMATES_API_KEY"], api_url=os.environ["OPENMATES_API_URL"], device_id="account-import-sdk-pip")
parsed = client.account.parse_chatgpt_import(Path(os.environ["OPENMATES_IMPORT_FIXTURE"]).read_bytes(), "chatgpt-sdk-live.zip")
if parsed.get("source") != "chatgpt":
    raise SystemExit(f"pip SDK parsed unexpected source {parsed.get('source')}")
if len(parsed.get("chats") or []) != 3:
    raise SystemExit(f"pip SDK parsed {len(parsed.get('chats') or [])} chats instead of 3")
result = client.account.import_chats(parsed, select="all")
complete = result.get("complete") or {}
persistence = result.get("persistence") or {}
if complete.get("status") != "complete" or complete.get("imported_count") != 3:
    raise SystemExit(f"pip SDK import did not complete exactly 3 chats: {json.dumps({'status': complete.get('status'), 'imported': complete.get('imported_count')})}")
if persistence.get("status") != "complete":
    raise SystemExit(f"pip SDK encrypted persistence status was {persistence.get('status')}")
print(json.dumps({"source": result.get("source"), "parsed_chats": len(parsed.get("chats") or []), "imported_count": complete.get("imported_count"), "persistence_status": persistence.get("status")}))
"""
    env = {
        **os.environ,
        "OPENMATES_API_KEY": api_key,
        "OPENMATES_API_URL": api_url,
        "OPENMATES_IMPORT_FIXTURE": str(fixture),
        "PYTHONPATH": str(ROOT / "packages/openmates-python"),
    }
    try:
        run(["python3", "-c", code], cwd=ROOT, capture=True, env=env)
    except RuntimeError as error:
        if not _is_device_approval_error(error):
            raise
        approved = _approve_pending_key_devices(api_url, api_key_id, {"pip"})
        if not approved:
            raise RuntimeError("No pending pip SDK device was available to approve") from error
        run(["python3", "-c", code], cwd=ROOT, capture=True, env=env)


def run_pip_sdk_generic_import(api_url: str, api_key: str, api_key_id: str, work_dir: Path) -> None:
    fixture = create_generic_fixture(work_dir, "generic-import-pip-sdk-synthetic.json")
    code = """
from pathlib import Path
from openmates import OpenMates
import json
import os

client = OpenMates(api_key=os.environ["OPENMATES_API_KEY"], api_url=os.environ["OPENMATES_API_URL"], device_id="account-import-generic-sdk-pip")
parsed = client.account.parse_generic_import(Path(os.environ["OPENMATES_IMPORT_FIXTURE"]).read_bytes(), source="other", source_name="generic-sdk-live.json")
if parsed.get("source") != "other" or parsed.get("parser_format") != "generic" or len(parsed.get("chats") or []) != 1:
    raise SystemExit("pip SDK parsed unexpected generic result")
result = client.account.import_chats(parsed, select="all")
if (result.get("complete") or {}).get("status") != "complete" or (result.get("persistence") or {}).get("status") != "complete":
    raise SystemExit("pip SDK generic import did not complete")
print(json.dumps({"source": result.get("source"), "parser_format": parsed.get("parser_format"), "imported_count": result["complete"].get("imported_count")}))
"""
    env = {
        **os.environ,
        "OPENMATES_API_KEY": api_key,
        "OPENMATES_API_URL": api_url,
        "OPENMATES_IMPORT_FIXTURE": str(fixture),
        "PYTHONPATH": str(ROOT / "packages/openmates-python"),
    }
    try:
        run(["python3", "-c", code], cwd=ROOT, capture=True, env=env)
    except RuntimeError as error:
        if not _is_device_approval_error(error):
            raise
        if not _approve_pending_key_devices(api_url, api_key_id, {"pip"}):
            raise RuntimeError("No pending pip SDK device was available to approve") from error
        run(["python3", "-c", code], cwd=ROOT, capture=True, env=env)


def run_pip_sdk_opencode_import(api_url: str, api_key: str, api_key_id: str, work_dir: Path) -> None:
    fixture = create_opencode_fixture(work_dir, "opencode-import-pip-sdk-synthetic.json")
    code = """
from pathlib import Path
from openmates import OpenMates
import os

client = OpenMates(api_key=os.environ["OPENMATES_API_KEY"], api_url=os.environ["OPENMATES_API_URL"], device_id="account-import-opencode-sdk-pip")
parsed = client.account.parse_opencode_import(Path(os.environ["OPENMATES_IMPORT_FIXTURE"]).read_bytes(), "opencode-sdk-live.json")
if parsed.get("source") != "opencode" or len(parsed.get("chats") or []) != 1:
    raise SystemExit("pip SDK parsed unexpected OpenCode result")
if parsed["chats"][0].get("uploads"):
    raise SystemExit("pip SDK retained OpenCode file payloads")
result = client.account.import_chats(parsed, select="all")
complete = result.get("complete") or {}
if complete.get("status") != "complete" or complete.get("imported_count") != 1:
    raise SystemExit("pip SDK OpenCode import did not complete exactly one chat")
print("OpenCode pip SDK import passed")
"""
    env = {
        **os.environ,
        "OPENMATES_API_KEY": api_key,
        "OPENMATES_API_URL": api_url,
        "OPENMATES_IMPORT_FIXTURE": str(fixture),
        "PYTHONPATH": str(ROOT / "packages/openmates-python"),
    }
    try:
        run(["python3", "-c", code], cwd=ROOT, capture=True, env=env)
    except RuntimeError as error:
        if not _is_device_approval_error(error):
            raise
        approved = _approve_pending_key_devices(api_url, api_key_id, {"pip"})
        if not approved:
            raise RuntimeError("No pending pip SDK device was available to approve") from error
        run(["python3", "-c", code], cwd=ROOT, capture=True, env=env)


def chatgpt_conversation(index: int) -> dict:
    suffix = f"{int(time.time())}-{index}"
    return {
        "id": f"chatgpt-cli-import-chat-{suffix}",
        "conversation_id": f"chatgpt-cli-import-conversation-{suffix}",
        "title": f"Synthetic ChatGPT CLI import chat {index}",
        "create_time": 1_785_000_000 + index,
        "update_time": 1_785_000_100 + index,
        "current_node": f"assistant-{index}",
        "mapping": {
            "root": {"id": "root", "message": None, "parent": None},
            f"user-{index}": {
                "id": f"user-{index}",
                "parent": "root",
                "message": {
                    "id": f"message-user-{suffix}",
                    "author": {"role": "user"},
                    "create_time": 1_785_000_001 + index,
                    "content": {"content_type": "text", "parts": ["Synthetic ChatGPT CLI import user message."]},
                },
            },
            f"assistant-{index}": {
                "id": f"assistant-{index}",
                "parent": f"user-{index}",
                "message": {
                    "id": f"message-assistant-{suffix}",
                    "author": {"role": "assistant"},
                    "create_time": 1_785_000_010 + index,
                    "content": {"content_type": "text", "parts": ["Synthetic ChatGPT CLI import assistant message."]},
                },
            },
        },
    }


def run_openmates_import_preview(api_url: str, work_dir: Path) -> None:
    fixture = work_dir / "openmates-import-synthetic.zip"
    with zipfile.ZipFile(fixture, "w") as archive:
        archive.writestr("README.md", "Synthetic OpenMates Export V1 fixture")
        archive.writestr("manifest.yml", "format: openmates-account-export\nversion: 1\ndomains:\n  chats:\n    count: 1\n  projects:\n    count: 1\n")
        archive.writestr("export-report.yml", "status: complete\n")
        archive.writestr("chats/chat-1.yml", "id: chat-1\ntitle: Synthetic chat\nmessages: []\n")
        archive.writestr("chats/chat-1.md", "# Synthetic chat\n")
    result = run_cli_json(["account", "import", "openmates", str(fixture), "--domain", "chats", "--dry-run", "--json"], api_url)
    parsed = result.get("parsed") if isinstance(result.get("parsed"), dict) else {}
    if int(parsed.get("chat_count") or 0) != 1:
        raise RuntimeError(f"OpenMates import preview did not parse one chat: {redacted(result)}")
    if "projects" not in parsed.get("skipped_domains", []):
        raise RuntimeError(f"OpenMates import preview did not report skipped projects: {redacted(result)}")


def run_limits_preview(api_url: str, work_dir: Path) -> None:
    fixture = work_dir / "claude-import-limits-synthetic.json"
    chats = [
        {
            "uuid": f"claude-cli-import-limits-{index}",
            "name": f"Synthetic limits chat {index}",
            "updated_at": f"2026-07-{index + 1:02d}T00:00:00Z",
            "chat_messages": [{"uuid": f"msg-{index}", "sender": "human", "text": "Synthetic limits message."}],
        }
        for index in range(5)
    ]
    fixture.write_text(json.dumps(chats), encoding="utf-8")
    result = run_cli_json(["account", "import", "claude", str(fixture), "--dry-run", "--json"], api_url)
    preview = result.get("preview") if isinstance(result.get("preview"), dict) else {}
    if "default_selection_count" not in preview or "max_batch_count" not in preview:
        raise RuntimeError(f"limits preview missing selection counts: {redacted(result)}")


def run_cli_json(args: list[str], api_url: str) -> dict:
    completed = run(["node", str(CLI_DIST), *args, "--api-url", api_url], cwd=ROOT, capture=True)
    try:
        output = completed.stdout.strip()
        starts = [index for index in (output.find("{"), output.find("[")) if index >= 0]
        if not starts:
            raise json.JSONDecodeError("missing JSON payload", output, 0)
        return json.loads(output[min(starts) :])
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"CLI did not return JSON for {' '.join(args)}") from exc


def redacted(value: object) -> str:
    text = json.dumps(value, sort_keys=True)
    return text[:1200]


def run(command: list[str], *, cwd: Path, capture: bool = False, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(command, cwd=cwd, env=env or os.environ.copy(), text=True, capture_output=capture, check=False, timeout=180)
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
