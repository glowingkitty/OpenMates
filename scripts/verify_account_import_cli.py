#!/usr/bin/env python3
"""Verify Account Import V1 through the real OpenMates CLI.

Purpose: exercise CLI-first account import gates against dev/prod API targets.
Architecture: docs/specs/account-import-v1/spec.yml.
Security: uses synthetic fixtures only and never prints tokens, cookies, or
private import content.
Privacy: writes temporary import fixtures only under /tmp/opencode unless an
explicit --work-dir is provided.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile


ROOT = Path(__file__).resolve().parents[1]
CLI_DIR = ROOT / "frontend/packages/openmates-cli"
CLI_DIST = CLI_DIR / "dist/cli.js"
DEFAULT_DEV_API_URL = "https://api.dev.openmates.org"
DEFAULT_PROD_API_URL = "https://api.openmates.org"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Account Import V1 CLI verification scenarios.")
    parser.add_argument("--env", choices=["dev", "prod"], default="dev")
    parser.add_argument(
        "--scenario",
        choices=["claude-import", "chatgpt-import", "openmates-v1-import", "limits-and-costs", "all"],
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

    scenarios = [args.scenario] if args.scenario != "all" else ["claude-import", "chatgpt-import", "openmates-v1-import", "limits-and-costs"]
    results: dict[str, str] = {}
    try:
        for scenario in scenarios:
            if scenario == "claude-import":
                run_claude_import(api_url, work_dir)
            elif scenario == "chatgpt-import":
                run_chatgpt_import(api_url, work_dir)
            elif scenario == "openmates-v1-import":
                run_openmates_import_preview(api_url, work_dir)
            elif scenario == "limits-and-costs":
                run_limits_preview(api_url, work_dir)
            results[scenario] = "passed"
    finally:
        if should_cleanup_work_dir:
            shutil.rmtree(work_dir, ignore_errors=True)

    print(json.dumps({"status": "passed", "api_url": api_url, "work_dir": str(work_dir), "work_dir_deleted": should_cleanup_work_dir, "scenarios": results}, indent=2))
    return 0


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
    fixture = work_dir / "chatgpt-import-synthetic.zip"
    conversations = [chatgpt_conversation(index) for index in range(1, 4)]
    with zipfile.ZipFile(fixture, "w") as archive:
        archive.writestr("ChatGPT Export/conversations.json", json.dumps(conversations))
        archive.writestr("ChatGPT Export/conversation_asset_file_names.json", json.dumps({}))

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
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"CLI did not return JSON for {' '.join(args)}") from exc


def redacted(value: object) -> str:
    text = json.dumps(value, sort_keys=True)
    return text[:1200]


def run(command: list[str], *, cwd: Path, capture: bool = False) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(command, cwd=cwd, text=True, capture_output=capture, check=False, timeout=180)
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
