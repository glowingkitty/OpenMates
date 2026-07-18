#!/usr/bin/env python3
"""Shared real-CLI verification helpers for Teams V1.

These checks intentionally execute the compiled OpenMates CLI against a real API
session. They are not mocks; local unit tests cover mocked contracts, while these
scripts are the deploy/dev gates referenced by docs/specs/teams-v1/spec.yml.
Secrets are read by existing CLI test-account tooling and are never printed.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CLI_DIR = ROOT / "frontend" / "packages" / "openmates-cli"
RUN_ENV = os.environ.copy()


class VerificationError(RuntimeError):
    """Raised for a failed Teams CLI verification assertion."""


def run(command: list[str], *, cwd: Path = ROOT, timeout: int = 180) -> str:
    result = subprocess.run(command, cwd=cwd, env=RUN_ENV, text=True, capture_output=True, check=False, timeout=timeout)
    if result.returncode != 0:
        sys.stderr.write(result.stdout)
        sys.stderr.write(result.stderr)
        raise VerificationError(f"Command failed ({result.returncode}): {' '.join(command)}")
    return result.stdout


def run_cli(args: list[str], *, timeout: int = 180) -> str:
    return run(["node", "dist/cli.js", *args], cwd=CLI_DIR, timeout=timeout)


def run_cli_json(args: list[str], *, timeout: int = 180) -> Any:
    output = run_cli([*args, "--json"], timeout=timeout).strip()
    if not output:
        raise VerificationError(f"CLI command returned empty JSON output: {' '.join(args)}")
    starts = [index for index in (output.find("{"), output.find("[")) if index >= 0]
    return json.loads(output[min(starts) :] if starts else output)


def run_cli_failure(args: list[str], *, timeout: int = 180) -> str:
    result = subprocess.run(["node", "dist/cli.js", *args], cwd=CLI_DIR, env=RUN_ENV, text=True, capture_output=True, check=False, timeout=timeout)
    if result.returncode == 0:
        raise VerificationError(f"Command unexpectedly succeeded: {' '.join(args)}")
    return f"{result.stdout}\n{result.stderr}"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise VerificationError(message)


def setup_cli(api_url: str, skip_build: bool) -> None:
    if not skip_build:
        run(["npm", "run", "build"], cwd=CLI_DIR, timeout=240)
    run(["node", "scripts/openmates_cli_test_account.mjs", "login", "--api-url", api_url], timeout=180)


def login_cli(api_url: str, slot: str | None = None) -> None:
    command = ["node", "scripts/openmates_cli_test_account.mjs", "login", "--api-url", api_url]
    if slot:
        command.extend(["--slot", slot])
    run(command, timeout=180)


def load_env_values() -> dict[str, str]:
    values = dict(os.environ)
    env_path = ROOT / ".env"
    if not env_path.exists():
        return values
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
            value = value[1:-1]
        values.setdefault(key.strip(), value)
    return values


def available_test_account_slots() -> list[str]:
    values = load_env_values()
    slots = [str(index) for index in range(1, 21) if values.get(f"OPENMATES_TEST_ACCOUNT_{index}_EMAIL")]
    if values.get("OPENMATES_TEST_ACCOUNT_EMAIL"):
        slots.append("")
    return slots


def test_account_email(slot: str) -> str:
    values = load_env_values()
    suffix = f"_{slot}" if slot else ""
    email = values.get(f"OPENMATES_TEST_ACCOUNT{suffix}_EMAIL")
    require(bool(email), f"Missing OPENMATES_TEST_ACCOUNT{suffix}_EMAIL for multi-account verification")
    return str(email)


def team_id_from(value: dict[str, Any]) -> str:
    team = value.get("team") if isinstance(value.get("team"), dict) else value
    team_id = team.get("team_id") or team.get("id") if isinstance(team, dict) else None
    require(isinstance(team_id, str) and team_id, f"Missing team_id in response: {value}")
    return team_id


def chat_id_from(value: dict[str, Any]) -> str:
    chat_id = value.get("chatId") or value.get("chat_id")
    if not chat_id and isinstance(value.get("chat"), dict):
        chat_id = value["chat"].get("id") or value["chat"].get("chat_id")
    require(isinstance(chat_id, str) and chat_id, f"Missing chat ID in response: {value}")
    return chat_id


def listed_chat_ids(value: Any) -> set[str]:
    raw_chats = value.get("chats", value) if isinstance(value, dict) else value
    require(isinstance(raw_chats, list), f"Chat list response did not contain a list: {value}")
    chat_ids: set[str] = set()
    for raw_chat in raw_chats:
        if not isinstance(raw_chat, dict):
            continue
        chat = raw_chat.get("chat") if isinstance(raw_chat.get("chat"), dict) else raw_chat
        chat_id = chat.get("id") or chat.get("chat_id")
        if isinstance(chat_id, str):
            chat_ids.add(chat_id)
    return chat_ids


def memory_ids(value: Any) -> set[str]:
    raw_entries = value.get("memories", value) if isinstance(value, dict) else value
    require(isinstance(raw_entries, list), f"Memory list response did not contain a list: {value}")
    return {str(entry.get("id")) for entry in raw_entries if isinstance(entry, dict) and entry.get("id")}


def create_test_team(prefix: str = "CLI Teams V1") -> str:
    suffix = str(time.time_ns())
    created = run_cli_json(["teams", "create", "--name", f"{prefix} {suffix}", "--slug", f"teams-v1-{suffix}", "--switch"])
    return team_id_from(created)


def cleanup_team(team_id: str) -> None:
    subprocess.run(["node", "dist/cli.js", "teams", "delete", team_id, "--yes", "--json"], cwd=CLI_DIR, env=RUN_ENV, text=True, capture_output=True, check=False)


def cleanup_memory(entry_id: str, team_id: str | None = None) -> None:
    command = ["node", "dist/cli.js", "settings", "memories", "delete", "--id", entry_id, "--json"]
    if team_id:
        command.extend(["--team", team_id])
    subprocess.run(command, cwd=CLI_DIR, env=RUN_ENV, text=True, capture_output=True, check=False)


def scenario_lifecycle(api_url: str, skip_build: bool) -> dict[str, Any]:
    setup_cli(api_url, skip_build)
    team_id = create_test_team("CLI Teams lifecycle")
    try:
        teams = run_cli_json(["teams", "list"])
        require(any(team.get("team_id") == team_id or team.get("id") == team_id for team in teams.get("teams", [])), "Created team was not listed")
        switched = run_cli_json(["teams", "switch", team_id])
        require(switched.get("active_team_id") == team_id, "Team switch did not persist active team")
        personal = run_cli_json(["teams", "personal"])
        require(personal.get("active_team_id") is None, "Personal switch did not clear active team")
        shown = run_cli_json(["teams", "show", team_id])
        require(team_id_from(shown) == team_id, "Team show returned a different team")
    finally:
        cleanup_team(team_id)
    return {"status": "passed", "team_id_prefix": team_id[:8]}


def scenario_membership(api_url: str, skip_build: bool) -> dict[str, Any]:
    slots = available_test_account_slots()
    require(len(slots) >= 2, "Membership verification requires two OPENMATES_TEST_ACCOUNT slots")
    owner_slot, member_slot = slots[0], slots[1]
    if not skip_build:
        run(["npm", "run", "build"], cwd=CLI_DIR, timeout=240)
    login_cli(api_url, owner_slot)
    member_email = test_account_email(member_slot)
    team_id = create_test_team("CLI Teams membership")
    try:
        invite = run_cli_json(["teams", "invite", team_id, "--email", member_email, "--role", "viewer"], timeout=120)["invite"]
        invite_id = invite.get("invite_id")
        require(isinstance(invite_id, str), "Invite response did not include invite_id")
        invite_input = invite.get("invite_url") or invite_id
        require(isinstance(invite_input, str) and invite_input, "Invite response did not include an invite URL or ID")
        login_cli(api_url, member_slot)
        accepted = run_cli_json(["teams", "accept-invite", invite_input, "--email", member_email], timeout=120)
        require(accepted.get("status_label") == "Waiting for team access approval", "Invite accept did not return access-approval wait state")
        login_cli(api_url, owner_slot)
        requests = run_cli_json(["teams", "access-requests", team_id], timeout=120)
        access_requests = requests.get("access_requests", [])
        require(isinstance(access_requests, list) and access_requests, "Access request list did not include accepted invite")
        matching = [request for request in access_requests if isinstance(request, dict) and request.get("invite_id") == invite_id]
        require(matching, "Access request list did not include the accepted invite")
        access_request_id = matching[0].get("access_request_id")
        require(isinstance(access_request_id, str), "Access request lacks access_request_id")
        approved = run_cli_json(["teams", "approve-access", team_id, access_request_id], timeout=120)
        require("membership" in approved, "Access approval did not return membership")
        login_cli(api_url, member_slot)
        member_teams = run_cli_json(["teams", "list"], timeout=120).get("teams", [])
        require(any(isinstance(team, dict) and team.get("team_id") == team_id for team in member_teams), "Approved member did not see the team in teams list")
    finally:
        login_cli(api_url, owner_slot)
        cleanup_team(team_id)
    return {"status": "passed", "team_id_prefix": team_id[:8]}


def scenario_billing(api_url: str, skip_build: bool) -> dict[str, Any]:
    setup_cli(api_url, skip_build)
    team_id = create_test_team("CLI Teams billing")
    try:
        billing = run_cli_json(["teams", "billing", team_id]).get("billing", {})
        require("balance_credits" in billing or "encrypted_balance" in billing, "Billing summary lacked balance fields")
        funded = run_cli_json(["teams", "add-credits", team_id, "--credits", "1"])
        require("billing" in funded, "Team add-credits did not return billing payload")
    finally:
        cleanup_team(team_id)
    return {"status": "passed", "team_id_prefix": team_id[:8]}


def scenario_data_portability(api_url: str, skip_build: bool) -> dict[str, Any]:
    setup_cli(api_url, skip_build)
    source_team_id = create_test_team("CLI Teams export")
    destination_team_id = ""
    try:
        with tempfile.TemporaryDirectory() as tmp:
            export_path = Path(tmp) / "team-export.json"
            run_cli_json(["teams", "export", source_team_id, "--output", str(export_path)])
            artifact = json.loads(export_path.read_text(encoding="utf-8"))
            require(artifact.get("schema") == "openmates.team_export.v1", "Team export artifact has wrong schema")
            require("owner_context': 'personal" not in repr(artifact), "Team export contains personal-context rows")
            artifact["rewrapped_with_destination_team_key"] = True
            export_path.write_text(f"{json.dumps(artifact, indent=2)}\n", encoding="utf-8")
            destination_team_id = create_test_team("CLI Teams import")
            imported = run_cli_json(["teams", "import", "--file", str(export_path), "--team", destination_team_id])
            require(imported.get("success") is True, "Team import did not report success")
    finally:
        if destination_team_id:
            cleanup_team(destination_team_id)
        cleanup_team(source_team_id)
    return {"status": "passed", "team_id_prefix": source_team_id[:8]}


def scenario_chat(api_url: str, skip_build: bool) -> dict[str, Any]:
    setup_cli(api_url, skip_build)
    team_id = create_test_team("CLI Teams chat")
    try:
        first = run_cli_json(["chats", "new", "Team note stored without mate mention", "--team", team_id, "--response-timeout-seconds", "5"], timeout=60)
        chat_id = chat_id_from(first)
        require(first.get("assistant") == "", "No-mention team chat should not wait for or return an assistant response")
        require(first.get("messageId") is None, "No-mention team chat should not return an assistant message ID")
        second = run_cli_json(["chats", "send", "--chat", chat_id, "Second team note stored without AI", "--team", team_id, "--response-timeout-seconds", "5"], timeout=60)
        require(second.get("chatId") == chat_id, "Follow-up team message returned a different chat ID")
        shown = run_cli_json(["chats", "show", chat_id, "--team", team_id], timeout=120)
        messages = shown.get("messages", []) if isinstance(shown, dict) else []
        require(isinstance(messages, list) and len(messages) >= 2, "Team chat show did not return both user messages")
    finally:
        cleanup_team(team_id)
    return {"status": "passed", "team_id_prefix": team_id[:8]}


def scenario_workspace_context(api_url: str, skip_build: bool) -> dict[str, Any]:
    setup_cli(api_url, skip_build)
    team_id = create_test_team("CLI Teams workspace")
    try:
        created = run_cli_json(["chats", "new", "Team workspace isolation note", "--team", team_id, "--response-timeout-seconds", "5"], timeout=60)
        chat_id = chat_id_from(created)
        team_chats = listed_chat_ids(run_cli_json(["chats", "list", "--team", team_id], timeout=120))
        personal_chats = listed_chat_ids(run_cli_json(["chats", "list", "--personal"], timeout=120))
        require(chat_id in team_chats, "Team chat did not appear in team chat list")
        require(chat_id not in personal_chats, "Team chat leaked into personal chat list")
    finally:
        cleanup_team(team_id)
    return {"status": "passed", "team_id_prefix": team_id[:8]}


def scenario_move(api_url: str, skip_build: bool) -> dict[str, Any]:
    setup_cli(api_url, skip_build)
    team_id = create_test_team("CLI Teams move")
    try:
        personal = run_cli_json(["chats", "new", "Reply with ok.", "--personal", "--response-timeout-seconds", "90"], timeout=140)
        chat_id = chat_id_from(personal)
        moved = run_cli_json(["teams", "move", team_id, "chat", "--id", chat_id, "--yes"], timeout=120)
        require(moved.get("success") is True or moved.get("status") in {"success", "moved"}, "Move command did not report success")
        team_chats = listed_chat_ids(run_cli_json(["chats", "list", "--team", team_id], timeout=120))
        personal_chats = listed_chat_ids(run_cli_json(["chats", "list", "--personal"], timeout=120))
        require(chat_id in team_chats, "Moved chat did not appear in team context")
        require(chat_id not in personal_chats, "Moved chat still appeared in personal context")
    finally:
        cleanup_team(team_id)
    return {"status": "passed", "team_id_prefix": team_id[:8]}


def scenario_offboarding(api_url: str, skip_build: bool) -> dict[str, Any]:
    slots = available_test_account_slots()
    require(len(slots) >= 2, "Offboarding verification requires two OPENMATES_TEST_ACCOUNT slots")
    owner_slot, member_slot = slots[0], slots[1]
    if not skip_build:
        run(["npm", "run", "build"], cwd=CLI_DIR, timeout=240)
    login_cli(api_url, owner_slot)
    member_email = test_account_email(member_slot)
    team_id = create_test_team("CLI Teams offboarding")
    try:
        invite = run_cli_json(["teams", "invite", team_id, "--email", member_email, "--role", "member"], timeout=120)["invite"]
        invite_input = invite.get("invite_url") or invite.get("invite_id")
        require(isinstance(invite_input, str) and invite_input, "Invite response did not include an invite URL or ID")
        login_cli(api_url, member_slot)
        member = run_cli_json(["whoami"], timeout=90)
        member_user_id = member.get("id") or member.get("user_id")
        require(isinstance(member_user_id, str) and member_user_id, "Member account whoami did not include a user ID")
        accepted = run_cli_json(["teams", "accept-invite", invite_input, "--email", member_email], timeout=120)
        require(accepted.get("status_label") == "Waiting for team access approval", "Invite accept did not enter access-approval wait state")
        login_cli(api_url, owner_slot)
        requests = run_cli_json(["teams", "access-requests", team_id], timeout=120).get("access_requests", [])
        matching = [request for request in requests if isinstance(request, dict) and request.get("invite_id") == invite.get("invite_id")]
        require(matching, "Owner access-request list did not include accepted invite")
        access_request_id = matching[0].get("access_request_id")
        require(isinstance(access_request_id, str), "Access request lacks access_request_id")
        run_cli_json(["teams", "approve-access", team_id, access_request_id], timeout=120)
        run_cli_json(["teams", "remove-member", team_id, "--user", member_user_id], timeout=120)
        login_cli(api_url, member_slot)
        teams = run_cli_json(["teams", "list"], timeout=120).get("teams", [])
        require(all(not isinstance(team, dict) or team.get("team_id") != team_id for team in teams), "Removed member still sees the team in teams list")
        run_cli_failure(["teams", "show", team_id, "--json"], timeout=120)
    finally:
        login_cli(api_url, owner_slot)
        cleanup_team(team_id)
    return {"status": "passed", "team_id_prefix": team_id[:8]}


def scenario_memory_accounts(api_url: str, skip_build: bool) -> dict[str, Any]:
    setup_cli(api_url, skip_build)
    team_id = create_test_team("CLI Teams memory")
    personal_memory_id = ""
    team_memory_id = ""
    try:
        personal = run_cli_json([
            "settings", "memories", "create",
            "--app-id", "code",
            "--item-type", "preferred_tech",
            "--data", '{"name":"TeamsPersonalVerifier","proficiency":"intermediate"}',
            "--personal",
        ], timeout=120)
        personal_memory_id = str(personal.get("id") or "")
        require(personal_memory_id, "Personal memory create did not return an ID")
        team = run_cli_json([
            "settings", "memories", "create",
            "--app-id", "code",
            "--item-type", "preferred_tech",
            "--data", '{"name":"TeamsTeamVerifier","proficiency":"advanced"}',
            "--team", team_id,
        ], timeout=120)
        team_memory_id = str(team.get("id") or "")
        require(team_memory_id, "Team memory create did not return an ID")
        personal_ids = memory_ids(run_cli_json(["settings", "memories", "list", "--app-id", "code", "--item-type", "preferred_tech", "--personal"], timeout=120))
        team_ids = memory_ids(run_cli_json(["settings", "memories", "list", "--app-id", "code", "--item-type", "preferred_tech", "--team", team_id], timeout=120))
        require(personal_memory_id in personal_ids, "Personal memory did not appear in personal context")
        require(team_memory_id in team_ids, "Team memory did not appear in team context")
        require(team_memory_id not in personal_ids, "Team memory leaked into personal memory list")
        require(personal_memory_id not in team_ids, "Personal memory leaked into team memory list")
        team_connected_accounts_error = run_cli_failure([
            "connected-accounts",
            "import",
            "--team",
            team_id,
            "--payload",
            "OMCA1.disabled-verifier",
            "--json",
        ], timeout=60)
        require(
            "Team connected accounts are not supported yet" in team_connected_accounts_error,
            "Team connected-account CLI command did not fail with the expected disabled message",
        )
    finally:
        if personal_memory_id:
            cleanup_memory(personal_memory_id)
        if team_memory_id:
            cleanup_memory(team_memory_id, team_id)
        cleanup_team(team_id)
    return {"status": "passed", "team_id_prefix": team_id[:8]}


SCENARIOS = {
    "lifecycle": scenario_lifecycle,
    "membership": scenario_membership,
    "billing": scenario_billing,
    "data-portability": scenario_data_portability,
    "chat": scenario_chat,
    "workspace-context": scenario_workspace_context,
    "move": scenario_move,
    "offboarding": scenario_offboarding,
    "memory-accounts": scenario_memory_accounts,
}


def main(name: str) -> int:
    global RUN_ENV
    parser = argparse.ArgumentParser(description=f"Verify Teams CLI {name} flow against a real API.")
    parser.add_argument("--api-url", default="http://127.0.0.1:8000", help="Real API URL to test against")
    parser.add_argument("--skip-build", action="store_true", help="Do not rebuild the CLI before running commands")
    args = parser.parse_args()
    try:
        with tempfile.TemporaryDirectory(prefix="openmates-teams-cli-") as home:
            RUN_ENV = {
                **os.environ,
                "HOME": home,
                "XDG_CONFIG_HOME": str(Path(home) / ".config"),
            }
            result = SCENARIOS[name](args.api_url, args.skip_build)
        print(json.dumps({"scenario": name, "api_url": args.api_url, **result}, indent=2))
        return 0
    except Exception as exc:  # noqa: BLE001 - emit structured failure for CI/dev logs.
        print(json.dumps({"scenario": name, "api_url": args.api_url, "status": "failed", "error": str(exc)}, indent=2))
        return 1
