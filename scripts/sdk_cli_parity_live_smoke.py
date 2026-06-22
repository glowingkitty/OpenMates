#!/usr/bin/env python3
"""Live SDK/CLI parity smoke proof.

Creates a real API key through the typed OpenMates CLI command, then uses that
key through the npm and Python SDKs. This script is intentionally opt-in because
it talks to a live API, may consume credits, and may require approving the new
API-key SDK device in developer settings before the SDK calls can proceed.

Run from the repo root after building the CLI package.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
CLI_DIST = REPO_ROOT / "frontend/packages/openmates-cli/dist/cli.js"
NPM_SDK_ENTRY = "./frontend/packages/openmates-cli/dist/index.js"
PYTHON_SDK_PATH = REPO_ROOT / "packages/openmates-python"


def _run(command: list[str], *, env: dict[str, str], description: str) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        cwd=REPO_ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"{description} failed with exit {result.returncode}\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )
    return result


def _parse_json_output(output: str) -> dict[str, Any]:
    start = output.find("{")
    if start < 0:
        raise RuntimeError(f"Expected JSON object in CLI output, got:\n{output}")
    return json.loads(output[start:])


def _api_key_id(create_result: dict[str, Any]) -> str | None:
    key = create_result.get("key")
    if isinstance(key, dict) and isinstance(key.get("id"), str):
        return key["id"]
    if isinstance(create_result.get("id"), str):
        return create_result["id"]
    return None


def _run_npm_sdk(env: dict[str, str]) -> dict[str, Any]:
    script = f"""
      import {{ OpenMates }} from '{NPM_SDK_ENTRY}';
      const client = new OpenMates({{
        apiKey: process.env.OPENMATES_SMOKE_API_KEY,
        apiUrl: process.env.OPENMATES_API_URL,
      }});
      const account = await client.account.info();
      const chats = await client.chats.list({{ limit: 10 }});
      const loaded = chats[0]?.id ? await client.chats.load(String(chats[0].id)) : null;
      const skill = await client.apps.math.calculate({{ expression: '2 + 2' }});
      await client.settings.setDarkMode(Boolean(account.darkmode));
      const billing = await client.billing.overview();
      const invoices = await client.billing.listInvoices();
      console.log(JSON.stringify({{
        account: Boolean(account.id),
        chats: chats.length,
        loadedMessages: Array.isArray(loaded?.messages) ? loaded.messages.length : null,
        loadedEmbeds: Array.isArray(loaded?.embeds) ? loaded.embeds.length : null,
        skill: Boolean(skill),
        billing: Boolean(billing),
        invoices: Array.isArray(invoices.invoices) ? invoices.invoices.length : null,
      }}));
    """
    result = _run(["node", "--input-type=module", "-e", script], env=env, description="npm SDK smoke")
    return json.loads(result.stdout.strip())


def _run_python_sdk(env: dict[str, str]) -> dict[str, Any]:
    script = """
import json
import os
import sys

sys.path.insert(0, os.fspath(%r))
from openmates import OpenMates

client = OpenMates(api_key=os.environ["OPENMATES_SMOKE_API_KEY"], api_url=os.environ["OPENMATES_API_URL"])
account = client.account.info()
chats = client.chats.list(limit=10)
loaded = client.chats.load(str(chats[0]["id"])) if chats and chats[0].get("id") else None
skill = client.apps.math.calculate({"expression": "3 + 4"})
client.settings.set_dark_mode(bool(account.get("darkmode")))
billing = client.billing.overview()
invoices = client.billing.list_invoices()
print(json.dumps({
    "account": bool(account.get("id")),
    "chats": len(chats),
    "loadedMessages": len(loaded.get("messages", [])) if isinstance(loaded, dict) else None,
    "loadedEmbeds": len(loaded.get("embeds", [])) if isinstance(loaded, dict) else None,
    "skill": bool(skill),
    "billing": bool(billing),
    "invoices": len(invoices.get("invoices", [])) if isinstance(invoices.get("invoices"), list) else None,
}))
""" % os.fspath(PYTHON_SDK_PATH)
    result = _run(["python3", "-c", script], env=env, description="Python SDK smoke")
    return json.loads(result.stdout.strip())


def main() -> int:
    parser = argparse.ArgumentParser(description="Run live SDK/CLI parity smoke proof.")
    parser.add_argument("--api-url", default=os.getenv("OPENMATES_API_URL", "https://api.openmates.org"))
    parser.add_argument("--name", default=f"sdk-cli-parity-smoke-{int(time.time())}")
    parser.add_argument("--skip-python", action="store_true")
    parser.add_argument("--skip-revoke", action="store_true")
    args = parser.parse_args()

    if os.getenv("OPENMATES_LIVE_SMOKE") != "1":
        print("Refusing to run live smoke. Set OPENMATES_LIVE_SMOKE=1 to opt in.", file=sys.stderr)
        return 2
    if not CLI_DIST.exists():
        print("Missing CLI dist/cli.js. Run: cd frontend/packages/openmates-cli && npm run build", file=sys.stderr)
        return 2

    env = os.environ.copy()
    env["OPENMATES_API_URL"] = args.api_url

    created: dict[str, Any] | None = None
    key_id: str | None = None
    try:
        create_result = _run(
            ["node", os.fspath(CLI_DIST), "settings", "developers", "api-keys", "create", args.name, "--yes", "--json"],
            env=env,
            description="CLI API-key creation",
        )
        created = _parse_json_output(create_result.stdout)
        api_key = created.get("api_key")
        if not isinstance(api_key, str) or not api_key.startswith("sk-api-"):
            raise RuntimeError("CLI did not return a one-time API key")
        key_id = _api_key_id(created)
        env["OPENMATES_SMOKE_API_KEY"] = api_key

        npm_result = _run_npm_sdk(env)
        python_result = None if args.skip_python else _run_python_sdk(env)
        print(json.dumps({"apiUrl": args.api_url, "keyId": key_id, "npm": npm_result, "python": python_result}, indent=2))
        return 0
    finally:
        if key_id and not args.skip_revoke:
            try:
                _run(
                    ["node", os.fspath(CLI_DIST), "settings", "developers", "api-keys", "revoke", key_id, "--yes", "--json"],
                    env=env,
                    description="CLI API-key revocation",
                )
                print(f"Revoked API key {key_id}.", file=sys.stderr)
            except RuntimeError as exc:
                print(f"WARNING: failed to revoke API key {key_id}: {exc}", file=sys.stderr)
        elif created and not key_id:
            print("WARNING: API key was created but no key id was returned; revoke it manually in developer settings.", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
