#!/usr/bin/env python3
"""Verify npm and pip work-control SDK calls against the real dev API.

The verifier creates a temporary developer key in its isolated authenticated CLI
session unless the caller provides one. Each SDK performs encrypted dependency,
typed-proof, revision, and approval-status calls, then the CLI removes fixtures.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
import uuid
from pathlib import Path
from urllib import request as urllib_request
from urllib.error import HTTPError

from sdk_cli_parity_live_smoke import NPM_SDK_ENTRY, PYTHON_SDK_PATH
from verify_project_remote_access_api import CLI_DIR, login_session, run
from verify_user_work_control_cli import cleanup, cli, identifier


VERIFIER_KEY_PREFIX = "work-control-sdk-"
VERIFIER_DEVICE_ID = "work-control-sdk-fixtures"


def sdk_command(command: list[str], env: dict[str, str], label: str) -> None:
    result = subprocess.run(command, cwd=Path(__file__).resolve().parents[1], env=env, text=True, capture_output=True, check=False, timeout=120)
    if result.returncode:
        raise RuntimeError(f"{label} failed: {result.stderr.strip()}")


def api_key_id(payload: dict[str, object]) -> str:
    key = payload.get("key") if isinstance(payload.get("key"), dict) else {}
    return str(payload.get("id") or payload.get("key_id") or key.get("id") or "")


def revoke_stale_verifier_keys(home: Path, api_url: str) -> None:
    payload = cli(home, api_url, ["settings", "developers", "api-keys", "list"])
    keys = payload.get("keys") if isinstance(payload.get("keys"), list) else payload.get("api_keys")
    for key in keys if isinstance(keys, list) else []:
        if not isinstance(key, dict) or not str(key.get("name") or "").startswith(VERIFIER_KEY_PREFIX):
            continue
        key_id = api_key_id(key)
        if key_id:
            cli(home, api_url, ["settings", "developers", "api-keys", "revoke", key_id, "--yes"])


def approve_pending_key_devices(home: Path, api_url: str, key_id: str, access_type: str) -> list[str]:
    session = json.loads((home / ".openmates" / "session.json").read_text())
    cookies = session.get("cookies") if isinstance(session.get("cookies"), dict) else {}
    cookie_header = "; ".join(f"{name}={value}" for name, value in cookies.items() if isinstance(value, str))

    def settings_request(path: str, method: str = "GET") -> dict[str, object]:
        request = urllib_request.Request(f"{api_url.rstrip('/')}/v1/settings/{path}", method=method, headers={"Accept": "application/json", "Cookie": cookie_header})
        if method != "GET":
            request.add_header("Content-Type", "application/json")
            request.data = b"{}"
        try:
            with urllib_request.urlopen(request, timeout=30) as response:
                payload = json.loads(response.read().decode() or "{}")
        except HTTPError as exc:
            raise RuntimeError(f"Settings device approval failed with HTTP {exc.code}") from exc
        return payload if isinstance(payload, dict) else {}

    approved: list[str] = []
    for device in settings_request("api-key-devices").get("devices", []):
        if not isinstance(device, dict) or device.get("api_key_id") != key_id or device.get("approved_at") or device.get("access_type") != access_type:
            continue
        device_id = device.get("id")
        if isinstance(device_id, str):
            settings_request(f"api-key-devices/{device_id}/approve", "POST")
            approved.append(device_id)
    return approved


def sdk_command_with_device_approval(command: list[str], env: dict[str, str], label: str, home: Path, api_url: str, key_id: str) -> None:
    try:
        sdk_command(command, env, label)
    except RuntimeError as exc:
        if not any(marker in str(exc) for marker in ("New device detected", "HTTP 403")) or not approve_pending_key_devices(home, api_url, key_id, label.split()[0].lower()):
            raise
        sdk_command(command, env, label)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default="https://api.dev.openmates.org")
    parser.add_argument("--slot", default=os.getenv("OPENMATES_TEST_ACCOUNT_SOURCE_SLOT"))
    parser.add_argument("--api-key", default=os.getenv("OPENMATES_WORK_CONTROL_SDK_API_KEY"))
    args = parser.parse_args()
    run(["npm", "run", "build"], cwd=CLI_DIR)
    with tempfile.TemporaryDirectory(prefix="openmates-work-control-sdk-") as home_value:
        home = Path(home_value)
        login_session(args.api_url, args.slot, home, "work-control-sdk-fixtures")
        suffix, project_id, plan_id, task_id, created_key_id = uuid.uuid4().hex[:12], "", "", "", ""
        api_key = args.api_key
        try:
            if not api_key:
                revoke_stale_verifier_keys(home, args.api_url)
                created_key = cli(home, args.api_url, ["settings", "developers", "api-keys", "create", f"{VERIFIER_KEY_PREFIX}{suffix}", "--yes"])
                api_key = str(created_key.get("api_key") or "")
                created_key_id = api_key_id(created_key)
                if not api_key or not created_key_id:
                    raise RuntimeError("CLI did not return a revocable developer API key")
            project_id = identifier(cli(home, args.api_url, ["projects", "create", f"sdk-work-control-{suffix}"]), "project_id")
            plan_id = identifier(cli(home, args.api_url, ["plans", "create", "--title", f"sdk-work-control-{suffix}", "--goal", "Verify SDK work control", "--project", project_id]), "plan_id")
            task_id = identifier(cli(home, args.api_url, ["tasks", "create", "--title", f"sdk-work-control-{suffix}", "--project", project_id, "--plan", plan_id]), "task_id")
            cli(home, args.api_url, ["plans", "assumptions", "create", plan_id, "--id", "proof", "--text", "typed proof"])
            env = {**os.environ, "OPENMATES_API_URL": args.api_url, "OPENMATES_SMOKE_API_KEY": api_key, "OPENMATES_WORK_PLAN": plan_id, "OPENMATES_WORK_TASK": task_id, "OPENMATES_SMOKE_DEVICE_ID": VERIFIER_DEVICE_ID}
            npm = f'''import {{ OpenMates }} from {json.dumps(NPM_SDK_ENTRY)}; const c=new OpenMates({{apiKey:process.env.OPENMATES_SMOKE_API_KEY,apiUrl:process.env.OPENMATES_API_URL,deviceId:process.env.OPENMATES_SMOKE_DEVICE_ID}}); const p=process.env.OPENMATES_WORK_PLAN,t=process.env.OPENMATES_WORK_TASK; await c.plans.dependencies.add(p,{{kind:"task",id:t}}); await c.plans.dependencies.list(p); await c.plans.dependencies.remove(p,{{kind:"task",id:t}}); await c.plans.assumptions.update(p,"proof",{{status:"confirmed",evidenceSummary:"typed proof",proofInputs:[{{kind:"file",path:"docs/plans/opencode-openmates-work-control/plan.yml",startLine:1,endLine:2}},{{kind:"url",url:"https://example.invalid/proof"}},{{kind:"embed",embedId:"embed-proof"}}]}}); await c.plans.review.submit(p); await c.plans.revisions.list(p); await c.plans.approval.status(p); if ("approve" in c.plans.approval) throw new Error("approval exposed");'''
            pip = '''import os,sys; sys.path.insert(0,%r); from openmates import OpenMates; c=OpenMates(api_key=os.environ["OPENMATES_SMOKE_API_KEY"],api_url=os.environ["OPENMATES_API_URL"],device_id=os.environ["OPENMATES_SMOKE_DEVICE_ID"]); p=os.environ["OPENMATES_WORK_PLAN"]; t=os.environ["OPENMATES_WORK_TASK"]; c.plans.dependencies.add(p,{"kind":"task","id":t}); c.plans.dependencies.list(p); c.plans.dependencies.remove(p,{"kind":"task","id":t}); c.plans.assumptions.update(p,"proof",{"status":"confirmed","evidence_summary":"typed proof","proof_inputs":[{"kind":"file","path":"docs/plans/opencode-openmates-work-control/plan.yml","start_line":1,"end_line":2},{"kind":"url","url":"https://example.invalid/proof"},{"kind":"embed","embed_id":"embed-proof"}]}); c.plans.review.submit(p); c.plans.revisions.list(p); c.plans.approval.status(p); assert not hasattr(c.plans.approval,"approve")''' % os.fspath(PYTHON_SDK_PATH)
            if created_key_id:
                sdk_command_with_device_approval(["node", "--input-type=module", "-e", npm], env, "npm SDK", home, args.api_url, created_key_id)
                sdk_command_with_device_approval(["python3", "-c", pip], env, "pip SDK", home, args.api_url, created_key_id)
            else:
                sdk_command(["node", "--input-type=module", "-e", npm], env, "npm SDK")
                sdk_command(["python3", "-c", pip], env, "pip SDK")
        finally:
            try:
                cleanup(home, args.api_url, task_id, plan_id, project_id)
            finally:
                if created_key_id:
                    cli(home, args.api_url, ["settings", "developers", "api-keys", "revoke", created_key_id, "--yes"])
    print(json.dumps({"status": "passed", "surfaces": ["npm", "pip"], "approval": "not_invoked"}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
