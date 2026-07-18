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
import platform
from pathlib import Path
import subprocess
import sys
import time
from typing import Any
from urllib import request as urllib_request
from urllib.error import HTTPError


REPO_ROOT = Path(__file__).resolve().parents[1]
CLI_DIST = REPO_ROOT / "frontend/packages/openmates-cli/dist/cli.js"
NPM_SDK_ENTRY = "./frontend/packages/openmates-cli/dist/index.js"
PYTHON_SDK_PATH = REPO_ROOT / "packages/openmates-python"


def _home_state_session() -> dict[str, Any]:
    session_path = Path.home() / ".openmates" / "session.json"
    if not session_path.exists():
        raise RuntimeError("No logged-in CLI session found; run `openmates login` before live SDK smoke.")
    return json.loads(session_path.read_text(encoding="utf-8"))


def _session_cookie_header() -> str:
    cookies = _home_state_session().get("cookies") or {}
    if not isinstance(cookies, dict) or not cookies:
        raise RuntimeError("Logged-in CLI session has no cookies; run `openmates login` again.")
    return "; ".join(f"{key}={value}" for key, value in cookies.items() if isinstance(value, str))


def _settings_request(api_url: str, path: str, *, method: str = "GET") -> dict[str, Any]:
    req = urllib_request.Request(
        f"{api_url.rstrip('/')}/v1/settings/{path.lstrip('/')}",
        method=method,
        headers={"Accept": "application/json", "Cookie": _session_cookie_header()},
    )
    if method != "GET":
        req.add_header("Content-Type", "application/json")
        req.data = b"{}"
    try:
        with urllib_request.urlopen(req, timeout=30) as response:
            return json.loads(response.read().decode("utf-8") or "{}")
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Settings request {method} {path} failed with HTTP {exc.code}: {body}") from exc


def _approve_pending_key_devices(api_url: str, key_id: str, access_types: set[str]) -> list[str]:
    data = _settings_request(api_url, "api-key-devices")
    approved: list[str] = []
    for device in data.get("devices", []):
        if not isinstance(device, dict):
            continue
        if device.get("api_key_id") != key_id:
            continue
        if device.get("approved_at"):
            continue
        if device.get("access_type") not in access_types:
            continue
        device_id = device.get("id")
        if not isinstance(device_id, str):
            continue
        _settings_request(api_url, f"api-key-devices/{device_id}/approve", method="POST")
        approved.append(device_id)
    return approved


def _is_device_approval_error(exc: RuntimeError) -> bool:
    message = str(exc)
    return (
        "approved_device_required" in message
        or "New device detected" in message
        or "OpenMates API request failed with HTTP 403" in message
    )


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
        deviceId: process.env.OPENMATES_SMOKE_DEVICE_ID,
      }});
      const models3dOnly = process.env.OPENMATES_MODELS3D_ONLY === '1';
      const account = models3dOnly ? null : await client.account.info();
      const chats = models3dOnly ? [] : await client.chats.list({{ limit: 10 }});
      const loaded = !models3dOnly && chats[0]?.id ? await client.chats.load(String(chats[0].id)) : null;
      const skill = models3dOnly ? null : await client.apps.math.calculate({{ expression: '2 + 2' }});
      const modelSearches = [];
      for (const [label, input] of [
        ['benchy', {{ requests: [{{ query: 'benchy', count: 2, providers: ['Printables'] }}] }}],
        ['phone-stand', {{ requests: [{{ query: 'phone stand', count: 2, providers: ['Printables'], sort: 'newest', free_only: true }}] }}],
      ]) {{
        const response = await client.apps.models3d.search(input);
        const group = response?.data?.results?.[0];
        const first = group?.results?.[0] ?? {{}};
        const requiredDetailFields = ['title', 'description', 'preview_image_url', 'source_page_url', 'creator_name', 'provider'];
        const missingDetailFields = requiredDetailFields.filter((field) => !first[field]);
        modelSearches.push({{
          label,
          success: response?.data?.success === true,
          provider: response?.data?.provider,
          resultCount: response?.data?.result_count,
          warnings: response?.data?.warnings ?? [],
          titles: (group?.results ?? []).map((item) => item.title),
          firstResult: {{
            title: first.title,
            description: first.description,
            previewImageUrl: first.preview_image_url,
            sourcePageUrl: first.source_page_url,
            creatorName: first.creator_name,
            license: first.license,
            filesCount: first.files_count,
            isFree: first.is_free,
          }},
          missingDetailFields,
          hasOpenCtaLabel: JSON.stringify(response).includes('open_cta_label'),
        }});
      }}
      const designIconSearch = models3dOnly ? null : await client.apps.design.searchIcons({{
        requests: [{{ query: 'home', count: 2, license_policy: 'permissive' }}],
      }});
      const iconGroup = designIconSearch?.data?.results?.[0];
      const firstIcon = iconGroup?.results?.[0] ?? {{}};
      if (!models3dOnly) await client.settings.setDarkMode(Boolean(account.darkmode));
      const billing = models3dOnly ? null : await client.billing.overview();
      const invoices = models3dOnly ? {{ invoices: [] }} : await client.billing.listInvoices();
      console.log(JSON.stringify({{
        account: account ? Boolean(account.id) : null,
        chats: chats.length,
        loadedMessages: Array.isArray(loaded?.messages) ? loaded.messages.length : null,
        loadedEmbeds: Array.isArray(loaded?.embeds) ? loaded.embeds.length : null,
        skill: Boolean(skill),
        models3d: modelSearches,
        designIcons: designIconSearch ? {{
          success: designIconSearch?.data?.success === true,
          provider: designIconSearch?.data?.provider,
          resultCount: designIconSearch?.data?.result_count,
          firstIcon: {{
            iconId: firstIcon.icon_id,
            licenseSpdx: firstIcon.license_spdx,
            svgPath: firstIcon.svg_path,
            hasSvgMarkup: Boolean(firstIcon.svg || firstIcon.svg_markup || firstIcon.png || firstIcon.preview_server_url),
          }},
        }} : null,
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

client = OpenMates(
    api_key=os.environ["OPENMATES_SMOKE_API_KEY"],
    api_url=os.environ["OPENMATES_API_URL"],
    device_id=os.environ["OPENMATES_SMOKE_DEVICE_ID"],
)
models3d_only = os.environ.get("OPENMATES_MODELS3D_ONLY") == "1"
account = None if models3d_only else client.account.info()
chats = [] if models3d_only else client.chats.list(limit=10)
loaded = client.chats.load(str(chats[0]["id"])) if not models3d_only and chats and chats[0].get("id") else None
skill = None if models3d_only else client.apps.math.calculate({"expression": "3 + 4"})
model_searches = []
for label, payload in [
    ("benchy", {"requests": [{"query": "benchy", "count": 2, "providers": ["Printables"]}]}),
    ("phone-stand", {"requests": [{"query": "phone stand", "count": 2, "providers": ["Printables"], "sort": "newest", "free_only": True}]}),
]:
    response = client.apps.models3d.search(payload)
    data = response.get("data", {})
    group = (data.get("results") or [{}])[0]
    first = (group.get("results") or [{}])[0]
    required_detail_fields = ["title", "description", "preview_image_url", "source_page_url", "creator_name", "provider"]
    missing_detail_fields = [field for field in required_detail_fields if not first.get(field)]
    model_searches.append({
        "label": label,
        "success": data.get("success") is True,
        "provider": data.get("provider"),
        "resultCount": data.get("result_count"),
        "warnings": data.get("warnings", []),
        "titles": [item.get("title") for item in group.get("results", [])],
        "firstResult": {
            "title": first.get("title"),
            "description": first.get("description"),
            "previewImageUrl": first.get("preview_image_url"),
            "sourcePageUrl": first.get("source_page_url"),
            "creatorName": first.get("creator_name"),
            "license": first.get("license"),
            "filesCount": first.get("files_count"),
            "isFree": first.get("is_free"),
        },
        "missingDetailFields": missing_detail_fields,
        "hasOpenCtaLabel": "open_cta_label" in json.dumps(response),
    })
design_icon_search = None
if not models3d_only:
    design_icon_search = client.apps.design.search_icons({"requests": [{"query": "home", "count": 2, "license_policy": "permissive"}]})
    icon_data = design_icon_search.get("data", {})
    icon_group = (icon_data.get("results") or [{}])[0]
    first_icon = (icon_group.get("results") or [{}])[0]
if not models3d_only:
    client.settings.set_dark_mode(bool(account.get("darkmode")))
billing = None if models3d_only else client.billing.overview()
invoices = {"invoices": []} if models3d_only else client.billing.list_invoices()
print(json.dumps({
    "account": bool(account.get("id")) if account else None,
    "chats": len(chats),
    "loadedMessages": len(loaded.get("messages", [])) if isinstance(loaded, dict) else None,
    "loadedEmbeds": len(loaded.get("embeds", [])) if isinstance(loaded, dict) else None,
    "skill": bool(skill),
    "models3d": model_searches,
    "designIcons": {
        "success": icon_data.get("success") is True,
        "provider": icon_data.get("provider"),
        "resultCount": icon_data.get("result_count"),
        "firstIcon": {
            "iconId": first_icon.get("icon_id"),
            "licenseSpdx": first_icon.get("license_spdx"),
            "svgPath": first_icon.get("svg_path"),
            "hasSvgMarkup": any(first_icon.get(field) for field in ["svg", "svg_markup", "png", "preview_server_url"]),
        },
    } if design_icon_search else None,
    "billing": bool(billing),
    "invoices": len(invoices.get("invoices", [])) if isinstance(invoices.get("invoices"), list) else None,
}))
""" % os.fspath(PYTHON_SDK_PATH)
    result = _run(["python3", "-c", script], env=env, description="Python SDK smoke")
    return json.loads(result.stdout.strip())


def _assert_models3d_details(result: dict[str, Any], *, sdk_name: str) -> None:
    searches = result.get("models3d")
    if not isinstance(searches, list):
        raise RuntimeError(f"{sdk_name} SDK smoke did not return models3d search summaries")
    for search in searches:
        if not isinstance(search, dict):
            raise RuntimeError(f"{sdk_name} SDK smoke returned invalid models3d summary: {search!r}")
        if search.get("success") is not True:
            raise RuntimeError(f"{sdk_name} SDK models3d search failed: {search!r}")
        if search.get("hasOpenCtaLabel") is True:
            raise RuntimeError(f"{sdk_name} SDK models3d search leaked open_cta_label: {search!r}")
        missing = search.get("missingDetailFields") or []
        if missing:
            raise RuntimeError(f"{sdk_name} SDK models3d search missing detail fields {missing}: {search!r}")


def _assert_design_icon_search(result: dict[str, Any], *, sdk_name: str) -> None:
    search = result.get("designIcons")
    if not isinstance(search, dict):
        raise RuntimeError(f"{sdk_name} SDK smoke did not return design icon search summary")
    if search.get("success") is not True or search.get("provider") != "Iconify":
        raise RuntimeError(f"{sdk_name} SDK design icon search failed: {search!r}")
    if not isinstance(search.get("resultCount"), int) or search["resultCount"] < 1:
        raise RuntimeError(f"{sdk_name} SDK design icon search returned no results: {search!r}")
    first_icon = search.get("firstIcon")
    if not isinstance(first_icon, dict):
        raise RuntimeError(f"{sdk_name} SDK design icon search returned invalid first icon: {search!r}")
    svg_path = first_icon.get("svgPath")
    if not isinstance(svg_path, str) or not svg_path.startswith("/v1/apps/design/icons/iconify/"):
        raise RuntimeError(f"{sdk_name} SDK design icon search did not use OpenMates SVG path: {search!r}")
    if first_icon.get("hasSvgMarkup") is True:
        raise RuntimeError(f"{sdk_name} SDK design icon search returned forbidden SVG/PNG markup: {search!r}")


def _cli_device_identity() -> str:
    machine = platform.machine().lower()
    arch = {"x86_64": "x64", "amd64": "x64", "aarch64": "arm64"}.get(machine, machine)
    return f"cli:{platform.system().lower()}:{arch}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run live SDK/CLI parity smoke proof.")
    parser.add_argument("--api-url", default=os.getenv("OPENMATES_API_URL", "https://api.openmates.org"))
    parser.add_argument("--name", default=f"sdk-cli-parity-smoke-{int(time.time())}")
    parser.add_argument("--skip-python", action="store_true")
    parser.add_argument("--skip-revoke", action="store_true")
    parser.add_argument("--models3d-only", action="store_true", help="Run only the real models3d.search npm/pip SDK calls.")
    args = parser.parse_args()

    if os.getenv("OPENMATES_LIVE_SMOKE") != "1":
        print("Refusing to run live smoke. Set OPENMATES_LIVE_SMOKE=1 to opt in.", file=sys.stderr)
        return 2
    if not CLI_DIST.exists():
        print("Missing CLI dist/cli.js. Run: cd frontend/packages/openmates-cli && npm run build", file=sys.stderr)
        return 2

    env = os.environ.copy()
    env["OPENMATES_API_URL"] = args.api_url
    env["OPENMATES_SMOKE_DEVICE_ID"] = _cli_device_identity()
    if args.models3d_only:
        env["OPENMATES_MODELS3D_ONLY"] = "1"

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

        approved_devices: dict[str, list[str]] = {"npm": [], "pip": []}
        try:
            npm_result = _run_npm_sdk(env)
        except RuntimeError as exc:
            if not key_id or not _is_device_approval_error(exc):
                raise
            approved_devices["npm"] = _approve_pending_key_devices(args.api_url, key_id, {"npm"})
            npm_result = _run_npm_sdk(env)
        if args.models3d_only:
            _assert_models3d_details(npm_result, sdk_name="npm")
        else:
            _assert_design_icon_search(npm_result, sdk_name="npm")

        python_result = None
        if not args.skip_python:
            try:
                python_result = _run_python_sdk(env)
            except RuntimeError as exc:
                if not key_id or not _is_device_approval_error(exc):
                    raise
                approved_devices["pip"] = _approve_pending_key_devices(args.api_url, key_id, {"pip"})
                python_result = _run_python_sdk(env)
            if args.models3d_only:
                _assert_models3d_details(python_result, sdk_name="pip")
            else:
                _assert_design_icon_search(python_result, sdk_name="pip")

        print(json.dumps({"apiUrl": args.api_url, "keyId": key_id, "approvedDevices": approved_devices, "npm": npm_result, "python": python_result}, indent=2))
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
