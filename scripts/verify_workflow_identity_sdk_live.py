#!/usr/bin/env python3
"""Verify Workflow identity and activation readiness through real npm/pip SDKs.

This opt-in smoke creates an ephemeral developer API key through the logged-in
OpenMates CLI, approves only the npm/pip devices created by this run, and
revokes the key during cleanup. See docs/specs/workflows-ui-contract/spec.yml.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import time
from typing import Any

from sdk_cli_parity_live_smoke import (
    CLI_DIST,
    NPM_SDK_ENTRY,
    PYTHON_SDK_PATH,
    _api_key_id,
    _approve_pending_key_devices,
    _is_device_approval_error,
    _parse_json_output,
    _run,
)


WORKFLOW_YAML = """
title: Workflow identity SDK smoke
start_when:
  manual: {}
steps:
  - id: forecast
    use_app_skill: weather.forecast
    input:
      location: Berlin
      days: 1
"""

BLANK_GRAPH = {"version": 1, "trigger_node_id": None, "nodes": [], "edges": []}
READY_GRAPH = {
    "version": 1,
    "trigger_node_id": "trigger",
    "nodes": [
        {"id": "trigger", "type": "schedule_trigger", "config": {"schedule": {"type": "daily", "time": "07:00", "timezone": "UTC"}}},
        {"id": "notify", "type": "send_notification", "config": {"title": "SDK readiness", "body": "Ready"}},
    ],
    "edges": [{"from": "trigger", "to": "notify"}],
}


def _device_identity() -> str:
    machine = platform.machine().lower()
    arch = {"x86_64": "x64", "amd64": "x64", "aarch64": "arm64"}.get(machine, machine)
    return f"cli:{platform.system().lower()}:{arch}"


# contract-test: direct surface=sdks.npm assertions=workflows.activation.reachable-side-effect,workflows.execution.lifecycle-visible,workflows-ui.identity.automatic-category-icon,workflows.surface.semantic-parity,sdk.surface.semantic-parity
def _run_npm(env: dict[str, str]) -> dict[str, Any]:
    script = f"""
      import {{ OpenMates }} from '{NPM_SDK_ENTRY}';
      const client = new OpenMates({{
        apiKey: process.env.OPENMATES_SMOKE_API_KEY,
        apiUrl: process.env.OPENMATES_API_URL,
        deviceId: process.env.OPENMATES_SMOKE_DEVICE_ID,
      }});
      let workflowId = '';
      let readinessId = '';
      try {{
        const created = await client.workflows.createFromYaml({json.dumps(WORKFLOW_YAML)});
        workflowId = created.workflow.id;
        const listed = (await client.workflows.list()).find((item) => item.id === workflowId);
        const fetched = await client.workflows.get(workflowId);
        const identity = {{ category: created.workflow.category, icon: created.workflow.icon }};
        if (identity.category !== 'science' || identity.icon !== 'cloud-rain') throw new Error(`Unexpected npm identity: ${{JSON.stringify(identity)}}`);
        if (listed?.category !== identity.category || listed?.icon !== identity.icon) throw new Error('npm list identity mismatch');
        if (fetched.category !== identity.category || fetched.icon !== identity.icon) throw new Error('npm detail identity mismatch');

        const blank = await client.workflows.create({{ title: `npm SDK readiness smoke ${{Date.now()}}`, graph: {json.dumps(BLANK_GRAPH)}, enabled: false }});
        readinessId = blank.id;
        if (blank.graph.trigger_node_id !== null || blank.graph.nodes.length !== 0) throw new Error('npm blank draft mismatch');
        let rejected = false;
        try {{
          await client.workflows.enable(readinessId);
        }} catch (error) {{
          rejected = [400, 409, 422].includes(error?.status);
        }}
        if (!rejected) throw new Error('npm blank activation was not rejected');
        await client.workflows.update(readinessId, {{ graph: {json.dumps(READY_GRAPH)} }});
        const enabled = await client.workflows.enable(readinessId);
        if (enabled.enabled !== true) throw new Error('npm ready Workflow did not enable');
        const run = await client.workflows.run(readinessId, {{ idempotencyKey: `npm-readiness-${{Date.now()}}`, mode: 'manual' }});
        if (!run.id) throw new Error('npm ready Workflow run was not accepted');
        console.log(JSON.stringify({{ ...identity, readiness: 'passed' }}));
      }} finally {{
        if (readinessId) await client.workflows.delete(readinessId, {{ confirmed: true }}).catch(() => undefined);
        if (workflowId) await client.workflows.delete(workflowId, {{ confirmed: true }}).catch(() => undefined);
      }}
    """
    result = _run(["node", "--input-type=module", "-e", script], env=env, description="npm Workflow identity SDK smoke")
    return json.loads(result.stdout.strip())


# contract-test: direct surface=sdks.pip assertions=workflows.activation.reachable-side-effect,workflows.execution.lifecycle-visible,workflows-ui.identity.automatic-category-icon,workflows.surface.semantic-parity,sdk.surface.semantic-parity
def _run_pip(env: dict[str, str]) -> dict[str, Any]:
    script = """
import json
import os
import sys
import time

sys.path.insert(0, os.fspath(%r))
from openmates import OpenMates

client = OpenMates(
    api_key=os.environ["OPENMATES_SMOKE_API_KEY"],
    api_url=os.environ["OPENMATES_API_URL"],
    device_id=os.environ["OPENMATES_SMOKE_DEVICE_ID"],
)
workflow_id = ""
readiness_id = ""
try:
    created = client.workflows.create_from_yaml(%r)["workflow"]
    workflow_id = created["id"]
    listed = next(item for item in client.workflows.list() if item["id"] == workflow_id)
    fetched = client.workflows.get(workflow_id)
    identity = {"category": created.get("category"), "icon": created.get("icon")}
    if identity != {"category": "science", "icon": "cloud-rain"}:
        raise RuntimeError(f"Unexpected pip identity: {identity!r}")
    if {"category": listed.get("category"), "icon": listed.get("icon")} != identity:
        raise RuntimeError("pip list identity mismatch")
    if {"category": fetched.get("category"), "icon": fetched.get("icon")} != identity:
        raise RuntimeError("pip detail identity mismatch")

    blank = client.workflows.create(title=f"pip SDK readiness smoke {int(time.time())}", graph=%r, enabled=False)
    readiness_id = blank["id"]
    if blank.get("graph", {}).get("trigger_node_id") is not None or blank.get("graph", {}).get("nodes") != []:
        raise RuntimeError("pip blank draft mismatch")
    try:
        client.workflows.enable(readiness_id)
    except Exception as exc:
        if getattr(exc, "status_code", None) not in {400, 409, 422}:
            raise
    else:
        raise RuntimeError("pip blank activation was not rejected")
    client.workflows.update(readiness_id, graph=%r)
    enabled = client.workflows.enable(readiness_id)
    if enabled.get("enabled") is not True:
        raise RuntimeError("pip ready Workflow did not enable")
    run = client.workflows.run(readiness_id, idempotency_key=f"pip-readiness-{int(time.time())}", mode="manual")
    if not run.get("id"):
        raise RuntimeError("pip ready Workflow run was not accepted")
    print(json.dumps({**identity, "readiness": "passed"}))
finally:
    if readiness_id:
        try:
            client.workflows.delete(readiness_id, confirmed=True)
        except Exception:
            pass
    if workflow_id:
        try:
            client.workflows.delete(workflow_id, confirmed=True)
        except Exception:
            pass
""" % (os.fspath(PYTHON_SDK_PATH), WORKFLOW_YAML, BLANK_GRAPH, READY_GRAPH)
    result = _run(["python3", "-c", script], env=env, description="pip Workflow identity SDK smoke")
    return json.loads(result.stdout.strip())


def _run_with_approval(run, env: dict[str, str], api_url: str, key_id: str, access_type: str) -> tuple[dict[str, Any], list[str]]:
    try:
        return run(env), []
    except RuntimeError as exc:
        if not _is_device_approval_error(exc):
            raise
        approved = _approve_pending_key_devices(api_url, key_id, {access_type})
        if not approved:
            raise RuntimeError(f"No pending {access_type} device was available for approval") from exc
        return run(env), approved


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify real dev npm/pip Workflow identity parity.")
    parser.add_argument("--api-url", default=os.getenv("OPENMATES_API_URL", "https://api.dev.openmates.org"))
    args = parser.parse_args()

    if not CLI_DIST.is_file():
        raise RuntimeError("Missing built OpenMates CLI; run npm --prefix frontend/packages/openmates-cli run build")

    env = os.environ.copy()
    env["OPENMATES_API_URL"] = args.api_url
    env["OPENMATES_SMOKE_DEVICE_ID"] = _device_identity()
    key_id = ""
    try:
        created = _parse_json_output(_run(
            ["node", os.fspath(CLI_DIST), "settings", "developers", "api-keys", "create", f"workflow-identity-sdk-{int(time.time())}", "--yes", "--json"],
            env=env,
            description="CLI API-key creation",
        ).stdout)
        api_key = created.get("api_key")
        key_id = _api_key_id(created) or ""
        if not isinstance(api_key, str) or not api_key.startswith("sk-api-") or not key_id:
            raise RuntimeError("CLI did not return a revocable one-time API key")
        env["OPENMATES_SMOKE_API_KEY"] = api_key

        npm, npm_devices = _run_with_approval(_run_npm, env, args.api_url, key_id, "npm")
        pip, pip_devices = _run_with_approval(_run_pip, env, args.api_url, key_id, "pip")
        print(json.dumps({"status": "passed", "npm": npm, "pip": pip, "approved_device_counts": {"npm": len(npm_devices), "pip": len(pip_devices)}}, sort_keys=True))
        return 0
    finally:
        if key_id:
            _run(
                ["node", os.fspath(CLI_DIST), "settings", "developers", "api-keys", "revoke", key_id, "--yes", "--json"],
                env=env,
                description="CLI API-key revocation",
            )


if __name__ == "__main__":
    raise SystemExit(main())
