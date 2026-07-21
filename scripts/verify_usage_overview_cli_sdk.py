#!/usr/bin/env python3
"""Verify usage overview rollups through real CLI and SDK clients.

Purpose: prove the usage overview spec against api.dev with real auth state.
Security: reads existing test-account credentials, never prints API keys or emails.
Scope: CLI daily/weekly/monthly latency and canonical JSON shape; optional npm/pip.
Architecture: docs/specs/usage-overview-rollups/spec.yml.
Run: python3 scripts/verify_usage_overview_cli_sdk.py --surface cli --api-url https://api.dev.openmates.org
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any
from urllib import request as urllib_request
from urllib.error import HTTPError


ROOT = Path(__file__).resolve().parents[1]
CLI_DIR = ROOT / "frontend" / "packages" / "openmates-cli"
CLI_DIST = CLI_DIR / "dist" / "cli.js"
NPM_SDK_ENTRY = "./frontend/packages/openmates-cli/dist/index.js"
PYTHON_SDK_PATH = ROOT / "packages/openmates-python"
DEFAULT_MAX_OVERVIEW_SECONDS = 10.0
DEFAULT_USAGE_WAIT_SECONDS = 90.0


class VerificationError(RuntimeError):
    """Raised when a real usage overview verification assertion fails."""


def _run(command: list[str], *, cwd: Path = ROOT, env: dict[str, str], timeout: int = 180) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(command, cwd=cwd, env=env, text=True, capture_output=True, check=False, timeout=timeout)
    if result.returncode != 0:
        raise VerificationError(
            f"Command failed ({result.returncode}): {' '.join(command)}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result


def _json_from_output(output: str) -> Any:
    output = output.strip()
    starts = [index for index in (output.find("{"), output.find("[")) if index >= 0]
    if not starts:
        raise VerificationError(f"Expected JSON output, got:\n{output}")
    return json.loads(output[min(starts):])


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise VerificationError(message)


def _load_dotenv(env: dict[str, str]) -> None:
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
            value = value[1:-1]
        env.setdefault(key.strip(), value)


def _run_cli(args: list[str], *, env: dict[str, str], timeout: int = 180) -> str:
    return _run(["node", "dist/cli.js", *args], cwd=CLI_DIR, env=env, timeout=timeout).stdout


def _run_cli_json(args: list[str], *, env: dict[str, str], timeout: int = 180) -> Any:
    return _json_from_output(_run_cli([*args, "--json"], env=env, timeout=timeout))


def _setup_cli(api_url: str, *, slot: str | None, skip_build: bool, env: dict[str, str]) -> None:
    if not skip_build:
        _run(["npm", "run", "build"], cwd=CLI_DIR, env=env, timeout=240)
    command = ["node", "scripts/openmates_cli_test_account.mjs", "login", "--api-url", api_url]
    if slot:
        command.extend(["--slot", slot])
    _run(command, cwd=ROOT, env=env, timeout=180)


def _overview_command(granularity: str, count: int) -> list[str]:
    count_flag = {"daily": "--days", "weekly": "--weeks", "monthly": "--months"}[granularity]
    return ["settings", "billing", "usage", "overview", "--granularity", granularity, count_flag, str(count)]


def _validate_overview(payload: dict[str, Any], *, granularity: str, require_real_usage: bool) -> None:
    _require(payload.get("granularity") == granularity, f"Expected {granularity} overview, got {payload.get('granularity')!r}")
    periods = payload.get("periods")
    totals = payload.get("totals")
    freshness = payload.get("freshness")
    token_coverage = payload.get("token_coverage")
    _require(isinstance(periods, list) and periods, f"{granularity} overview did not include periods")
    _require(isinstance(totals, dict), f"{granularity} overview did not include totals")
    _require(isinstance(freshness, dict), f"{granularity} overview did not include freshness metadata")
    _require(isinstance(token_coverage, dict), f"{granularity} overview did not include token coverage")
    _require("credits" in totals and "entries" in totals and "total_tokens" in totals, f"{granularity} totals missing core fields")
    _require("staleness_seconds" in freshness and "is_stale" in freshness, f"{granularity} freshness missing required fields")
    _require("coverage_ratio" in token_coverage, f"{granularity} token coverage missing coverage_ratio")
    first_period = periods[0]
    _require(isinstance(first_period, dict) and "period_key" in first_period, f"{granularity} period missing period_key")
    for breakdown in ("by_model", "by_app", "by_skill", "by_source", "by_provider", "by_region"):
        _require(isinstance(first_period.get(breakdown), list), f"{granularity} period missing {breakdown} list")
    if require_real_usage:
        _require(int(totals.get("entries") or 0) > 0, f"{granularity} overview did not include real usage entries")


def _timed_cli_overview(granularity: str, count: int, *, env: dict[str, str], max_seconds: float, require_real_usage: bool) -> dict[str, Any]:
    started = time.perf_counter()
    payload = _run_cli_json(_overview_command(granularity, count), env=env, timeout=max(int(max_seconds) + 30, 45))
    elapsed = time.perf_counter() - started
    _require(elapsed <= max_seconds, f"{granularity} CLI overview took {elapsed:.2f}s, expected <= {max_seconds:.2f}s")
    _validate_overview(payload, granularity=granularity, require_real_usage=require_real_usage)
    return {"elapsedSeconds": round(elapsed, 3), "payload": payload}


def _ensure_real_usage(api_url: str, *, env: dict[str, str], max_overview_seconds: float, max_wait_seconds: float) -> None:
    current = _timed_cli_overview("daily", 30, env=env, max_seconds=max_overview_seconds, require_real_usage=False)["payload"]
    if int((current.get("totals") or {}).get("entries") or 0) > 0:
        return

    prompt = "Usage overview smoke: answer with exactly 'usage overview ready'."
    _run_cli_json(["chats", "new", prompt, "--api-url", api_url], env=env, timeout=180)
    deadline = time.monotonic() + max_wait_seconds
    last_entries = 0
    while time.monotonic() < deadline:
        time.sleep(5)
        payload = _timed_cli_overview("daily", 30, env=env, max_seconds=max_overview_seconds, require_real_usage=False)["payload"]
        last_entries = int((payload.get("totals") or {}).get("entries") or 0)
        if last_entries > 0:
            return
    raise VerificationError(f"No real usage entries appeared after seeded chat within {max_wait_seconds:.0f}s; last entries={last_entries}")


def _session_cookie_header(env: dict[str, str]) -> str:
    session_path = Path(env["HOME"]) / ".openmates" / "session.json"
    if not session_path.exists():
        raise VerificationError("CLI session file missing after test-account login")
    cookies = json.loads(session_path.read_text(encoding="utf-8")).get("cookies") or {}
    _require(isinstance(cookies, dict) and bool(cookies), "CLI session did not include cookies")
    return "; ".join(f"{key}={value}" for key, value in cookies.items() if isinstance(value, str))


def _settings_request(api_url: str, path: str, *, env: dict[str, str], method: str = "GET") -> dict[str, Any]:
    req = urllib_request.Request(
        f"{api_url.rstrip('/')}/v1/settings/{path.lstrip('/')}",
        method=method,
        headers={"Accept": "application/json", "Cookie": _session_cookie_header(env)},
    )
    if method != "GET":
        req.add_header("Content-Type", "application/json")
        req.data = b"{}"
    try:
        with urllib_request.urlopen(req, timeout=30) as response:
            return json.loads(response.read().decode("utf-8") or "{}")
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise VerificationError(f"Settings request {method} {path} failed with HTTP {exc.code}: {body}") from exc


def _api_key_id(create_result: dict[str, Any]) -> str | None:
    key = create_result.get("key")
    if isinstance(key, dict) and isinstance(key.get("id"), str):
        return key["id"]
    if isinstance(create_result.get("id"), str):
        return create_result["id"]
    return None


def _approve_pending_key_devices(api_url: str, key_id: str, access_types: set[str], *, env: dict[str, str]) -> list[str]:
    data = _settings_request(api_url, "api-key-devices", env=env)
    approved: list[str] = []
    for device in data.get("devices", []):
        if not isinstance(device, dict) or device.get("api_key_id") != key_id or device.get("approved_at"):
            continue
        if device.get("access_type") not in access_types:
            continue
        device_id = device.get("id")
        if not isinstance(device_id, str):
            continue
        _settings_request(api_url, f"api-key-devices/{device_id}/approve", env=env, method="POST")
        approved.append(device_id)
    return approved


def _is_device_approval_error(exc: RuntimeError) -> bool:
    message = str(exc)
    return "approved_device_required" in message or "New device detected" in message or "HTTP 403" in message


def _sdk_device_identity(surface: str) -> str:
    machine = platform.machine().lower()
    arch = {"x86_64": "x64", "amd64": "x64", "aarch64": "arm64"}.get(machine, machine)
    return f"{surface}:{platform.system().lower()}:{arch}:usage-overview"


def _run_npm_sdk(env: dict[str, str], max_seconds: float) -> dict[str, Any]:
    script = f"""
      import {{ OpenMates }} from '{NPM_SDK_ENTRY}';
      const client = new OpenMates({{
        apiKey: process.env.OPENMATES_SMOKE_API_KEY,
        apiUrl: process.env.OPENMATES_API_URL,
        deviceId: process.env.OPENMATES_SMOKE_DEVICE_ID,
      }});
      const started = performance.now();
      const overview = await client.billing.usageOverview({{ query: {{ granularity: 'monthly', months: 2 }} }});
      console.log(JSON.stringify({{ elapsedSeconds: Number(((performance.now() - started) / 1000).toFixed(3)), overview }}));
    """
    result = _run(["node", "--input-type=module", "-e", script], cwd=ROOT, env=env, timeout=max(int(max_seconds) + 30, 45))
    data = json.loads(result.stdout.strip())
    _require(float(data["elapsedSeconds"]) <= max_seconds, f"npm SDK overview took {data['elapsedSeconds']}s")
    _validate_overview(data["overview"], granularity="monthly", require_real_usage=True)
    return data


def _run_pip_sdk(env: dict[str, str], max_seconds: float) -> dict[str, Any]:
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
started = time.perf_counter()
overview = client.billing.usage_overview(granularity="monthly", months=2)
print(json.dumps({"elapsedSeconds": round(time.perf_counter() - started, 3), "overview": overview}))
""" % os.fspath(PYTHON_SDK_PATH)
    result = _run(["python3", "-c", script], cwd=ROOT, env=env, timeout=max(int(max_seconds) + 30, 45))
    data = json.loads(result.stdout.strip())
    _require(float(data["elapsedSeconds"]) <= max_seconds, f"pip SDK overview took {data['elapsedSeconds']}s")
    _validate_overview(data["overview"], granularity="monthly", require_real_usage=True)
    return data


def _create_api_key(api_url: str, *, env: dict[str, str]) -> tuple[str, str]:
    name = f"usage-overview-live-{int(time.time())}"
    created = _run_cli_json(["settings", "developers", "api-keys", "create", name, "--yes", "--api-url", api_url], env=env)
    api_key = created.get("api_key")
    key_id = _api_key_id(created)
    _require(isinstance(api_key, str) and api_key.startswith("sk-api-"), "CLI did not return a one-time API key")
    _require(isinstance(key_id, str) and key_id, "CLI did not return API key id")
    return key_id, api_key


def _revoke_api_key(key_id: str, api_url: str, *, env: dict[str, str]) -> None:
    try:
        _run_cli_json(["settings", "developers", "api-keys", "revoke", key_id, "--yes", "--api-url", api_url], env=env)
    except Exception as exc:  # noqa: BLE001 - best-effort cleanup must not mask verification result.
        print(f"WARNING: failed to revoke API key {key_id}: {exc}", file=sys.stderr)


def verify_cli(api_url: str, *, env: dict[str, str], max_overview_seconds: float, max_wait_seconds: float) -> dict[str, Any]:
    _ensure_real_usage(api_url, env=env, max_overview_seconds=max_overview_seconds, max_wait_seconds=max_wait_seconds)
    results = {
        granularity: _timed_cli_overview(granularity, count, env=env, max_seconds=max_overview_seconds, require_real_usage=True)
        for granularity, count in (("daily", 30), ("weekly", 12), ("monthly", 12))
    }
    return {
        "surface": "cli",
        "apiUrl": api_url,
        "maxOverviewSeconds": max_overview_seconds,
        "results": {
            key: {
                "elapsedSeconds": value["elapsedSeconds"],
                "entries": value["payload"]["totals"]["entries"],
                "credits": value["payload"]["totals"]["credits"],
                "periodCount": len(value["payload"]["periods"]),
                "freshness": value["payload"].get("freshness"),
            }
            for key, value in results.items()
        },
    }


def verify_sdk(surface: str, api_url: str, *, env: dict[str, str], max_overview_seconds: float) -> dict[str, Any]:
    key_id, api_key = _create_api_key(api_url, env=env)
    sdk_env = {**env, "OPENMATES_API_URL": api_url, "OPENMATES_SMOKE_API_KEY": api_key, "OPENMATES_SMOKE_DEVICE_ID": _sdk_device_identity(surface)}
    try:
        try:
            result = _run_npm_sdk(sdk_env, max_overview_seconds) if surface == "npm" else _run_pip_sdk(sdk_env, max_overview_seconds)
        except RuntimeError as exc:
            if not _is_device_approval_error(exc):
                raise
            approved = _approve_pending_key_devices(api_url, key_id, {surface}, env=env)
            _require(bool(approved), f"No pending {surface} SDK device was available to approve")
            result = _run_npm_sdk(sdk_env, max_overview_seconds) if surface == "npm" else _run_pip_sdk(sdk_env, max_overview_seconds)
        overview = result["overview"]
        return {
            "surface": surface,
            "apiUrl": api_url,
            "elapsedSeconds": result["elapsedSeconds"],
            "entries": overview["totals"]["entries"],
            "credits": overview["totals"]["credits"],
            "periodCount": len(overview["periods"]),
            "freshness": overview.get("freshness"),
        }
    finally:
        _revoke_api_key(key_id, api_url, env=env)


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify real usage overview CLI/SDK behavior against a dev API.")
    parser.add_argument("--surface", choices=["cli", "npm", "pip", "all"], default="cli")
    parser.add_argument("--api-url", default=os.getenv("OPENMATES_API_URL", "https://api.dev.openmates.org"))
    parser.add_argument("--slot", default=os.getenv("OPENMATES_TEST_ACCOUNT_SOURCE_SLOT"), help="Optional OPENMATES_TEST_ACCOUNT_<slot> credentials to use")
    parser.add_argument("--skip-build", action="store_true")
    parser.add_argument("--max-overview-seconds", type=float, default=DEFAULT_MAX_OVERVIEW_SECONDS)
    parser.add_argument("--max-usage-wait-seconds", type=float, default=DEFAULT_USAGE_WAIT_SECONDS)
    args = parser.parse_args()

    api_url = args.api_url.rstrip("/")
    with tempfile.TemporaryDirectory(prefix="openmates-usage-overview-") as temp_home:
        env = os.environ.copy()
        _load_dotenv(env)
        env["HOME"] = temp_home
        env["USERPROFILE"] = temp_home
        env["OPENMATES_API_URL"] = api_url
        _setup_cli(api_url, slot=args.slot, skip_build=args.skip_build, env=env)

        surfaces = ["cli", "npm", "pip"] if args.surface == "all" else [args.surface]
        results: dict[str, Any] = {}
        _ensure_real_usage(api_url, env=env, max_overview_seconds=args.max_overview_seconds, max_wait_seconds=args.max_usage_wait_seconds)
        if "cli" in surfaces:
            results["cli"] = verify_cli(api_url, env=env, max_overview_seconds=args.max_overview_seconds, max_wait_seconds=args.max_usage_wait_seconds)
        for sdk_surface in (surface for surface in surfaces if surface in {"npm", "pip"}):
            results[sdk_surface] = verify_sdk(sdk_surface, api_url, env=env, max_overview_seconds=args.max_overview_seconds)

    print(json.dumps({"success": True, "apiUrl": api_url, "results": results}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
