#!/usr/bin/env python3
"""Run real Code image-to-HTML dev-server evals and Discord reporting.

Purpose: exercise `code.image_to_html` through the real dev REST, CLI, npm SDK,
and pip SDK surfaces using the existing OpenMates CLI test account.
Architecture: generation runs through `/v1/apps/code/skills/image_to_html`, so
Gemini and E2B credentials are resolved by the API worker through existing
Vault-backed provider paths. Output screenshots are downloaded from the worker's
signed generated-asset URL and are posted with input images for visual review.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import http.client
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CLI_DIR = ROOT / "frontend" / "packages" / "openmates-cli"
CLI_DIST = CLI_DIR / "dist" / "cli.js"
PYTHON_SDK_PATH = ROOT / "packages" / "openmates-python"
DEFAULT_API_URL = "https://api.dev.openmates.org"
TASK_POLL_INTERVAL_SECONDS = 5.0
TASK_POLL_TIMEOUT_SECONDS = 1200.0
E2B_FIXTURE_RENDER_TIMEOUT_SECONDS = 720
E2B_FIXTURE_RENDER_CONTAINERS = ("app-code-worker", "api")
DOCKER_E2B_RENDER_CODE = r"""
import asyncio
import base64
import json
import os
import sys

from backend.core.api.app.utils.secrets_manager import SecretsManager
from backend.shared.providers.e2b_code_runner import get_e2b_api_key_async
from backend.shared.providers.e2b_html_renderer import render_html_in_e2b

async def main():
    html = sys.stdin.read()
    viewport_width = int(os.environ.get("OPENMATES_EVAL_VIEWPORT_WIDTH") or "1440")
    viewport_height = int(os.environ.get("OPENMATES_EVAL_VIEWPORT_HEIGHT") or "1200")
    secrets_manager = SecretsManager()
    await secrets_manager.initialize()
    try:
        api_key = await get_e2b_api_key_async(secrets_manager)
        render = render_html_in_e2b(html=html, api_key=api_key, viewport_width=viewport_width, viewport_height=viewport_height)
        print(json.dumps({"screenshot_base64": base64.b64encode(render.screenshot_bytes).decode("ascii"), "duration_seconds": render.duration_seconds}))
    finally:
        await secrets_manager.aclose()

asyncio.run(main())
"""

DEFAULT_FIXTURES = [
    ("simple-card", ROOT / "tmp/code-image-to-html-eval/20260721-170124/simple-card-input.png"),
    ("complex-dashboard", ROOT / "tmp/code-image-to-html-eval/20260721-170124/complex-dashboard-input.png"),
    ("figma-openmates-tasks", ROOT / "tmp/code-image-to-html-eval/20260721-170124/figma-openmates-tasks-input.png"),
]


class EvalError(RuntimeError):
    """Raised when a real image-to-HTML eval step fails."""


class ApiError(RuntimeError):
    def __init__(self, status: int, body: str) -> None:
        super().__init__(f"HTTP {status}: {body[:500]}")
        self.status = status
        self.body = body


def load_dotenv(env: dict[str, str]) -> None:
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


def run(command: list[str], *, cwd: Path = ROOT, env: dict[str, str], timeout: int = 180) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(command, cwd=cwd, env=env, text=True, capture_output=True, check=False, timeout=timeout)
    if result.returncode != 0:
        raise EvalError(
            f"Command failed ({result.returncode}): {' '.join(command)}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result


def json_from_output(output: str) -> Any:
    stripped = output.strip()
    starts = [index for index in (stripped.find("{"), stripped.find("[")) if index >= 0]
    if not starts:
        raise EvalError(f"Expected JSON output, got:\n{output}")
    return json.loads(stripped[min(starts):])


def setup_cli_session(api_url: str, *, env: dict[str, str], skip_build: bool, slot: str | None) -> None:
    if not skip_build:
        run(["npm", "run", "build"], cwd=CLI_DIR, env=env, timeout=240)
    command = ["node", "scripts/openmates_cli_test_account.mjs", "login", "--api-url", api_url]
    if slot:
        command.extend(["--slot", slot])
    run(command, cwd=ROOT, env=env, timeout=180)


def run_cli_json(args: list[str], *, env: dict[str, str], timeout: int = 1500) -> Any:
    result = run(["node", "dist/cli.js", *args, "--json"], cwd=CLI_DIR, env=env, timeout=timeout)
    return json_from_output(result.stdout)


def create_api_key(api_url: str, *, env: dict[str, str]) -> tuple[str, str]:
    name = f"code-image-to-html-eval-{int(time.time())}"
    created = run_cli_json(["settings", "developers", "api-keys", "create", name, "--yes", "--api-url", api_url], env=env)
    api_key = created.get("api_key")
    key = created.get("key") if isinstance(created.get("key"), dict) else {}
    key_id = created.get("id") or key.get("id")
    if not isinstance(api_key, str) or not api_key.startswith("sk-api-"):
        raise EvalError("CLI did not return a one-time API key")
    if not isinstance(key_id, str) or not key_id:
        raise EvalError("CLI did not return API key id")
    return key_id, api_key


def revoke_api_key(key_id: str, api_url: str, *, env: dict[str, str]) -> None:
    try:
        run_cli_json(["settings", "developers", "api-keys", "revoke", key_id, "--yes", "--api-url", api_url], env=env, timeout=120)
    except Exception as exc:  # noqa: BLE001 - cleanup must not hide eval result.
        print(f"WARNING: failed to revoke API key {key_id}: {exc}", file=sys.stderr)


def session_cookie_header(env: dict[str, str]) -> str:
    session_path = Path(env["HOME"]) / ".openmates" / "session.json"
    if not session_path.exists():
        raise EvalError("CLI session file missing after test-account login")
    cookies = json.loads(session_path.read_text(encoding="utf-8")).get("cookies") or {}
    if not isinstance(cookies, dict) or not cookies:
        raise EvalError("CLI session did not include cookies")
    return "; ".join(f"{key}={value}" for key, value in cookies.items() if isinstance(value, str))


def settings_request(api_url: str, path: str, *, env: dict[str, str], method: str = "GET") -> dict[str, Any]:
    request = urllib.request.Request(
        f"{api_url.rstrip('/')}/v1/settings/{path.lstrip('/')}",
        method=method,
        headers={"Accept": "application/json", "Cookie": session_cookie_header(env)},
    )
    if method != "GET":
        request.add_header("Content-Type", "application/json")
        request.data = b"{}"
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise EvalError(f"Settings request {method} {path} failed with HTTP {exc.code}: {body}") from exc


def approve_pending_key_devices(api_url: str, key_id: str, access_types: set[str], *, env: dict[str, str]) -> list[str]:
    data = settings_request(api_url, "api-key-devices", env=env)
    approved: list[str] = []
    for device in data.get("devices", []):
        if not isinstance(device, dict) or device.get("api_key_id") != key_id or device.get("approved_at"):
            continue
        if device.get("access_type") not in access_types:
            continue
        device_id = device.get("id")
        if not isinstance(device_id, str):
            continue
        settings_request(api_url, f"api-key-devices/{device_id}/approve", env=env, method="POST")
        approved.append(device_id)
    return approved


def is_device_approval_error(error: Exception) -> bool:
    message = str(error)
    return "approved_device_required" in message or "New device detected" in message or "HTTP 403" in message


def sdk_device_identity(surface: str) -> str:
    machine = platform.machine().lower()
    arch = {"x86_64": "x64", "amd64": "x64", "aarch64": "arm64"}.get(machine, machine)
    return f"{surface}:{platform.system().lower()}:{arch}:code-image-to-html"


def request_json(
    api_url: str,
    method: str,
    path: str,
    *,
    api_key: str,
    payload: dict[str, Any] | None = None,
    sdk_name: str = "cli",
    device_id: str = "cli:linux:x64:code-image-to-html",
) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        f"{api_url.rstrip('/')}{path}",
        data=body,
        method=method,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-OpenMates-SDK": sdk_name,
            "X-OpenMates-Device-Identity": device_id,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            return json.loads(response.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        raise ApiError(exc.code, exc.read().decode("utf-8", errors="replace")) from exc


def poll_task(api_url: str, api_key: str, task_id: str, *, device_id: str) -> dict[str, Any]:
    deadline = time.monotonic() + TASK_POLL_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        status = request_json(api_url, "GET", f"/v1/tasks/{urllib.parse.quote(task_id)}", api_key=api_key, device_id=device_id)
        state = status.get("status")
        if state == "completed":
            result = status.get("result")
            if not isinstance(result, dict):
                raise EvalError(f"Task {task_id} completed without object result")
            return result
        if state == "failed":
            raise EvalError(f"Task {task_id} failed: {status.get('error')}")
        time.sleep(TASK_POLL_INTERVAL_SECONDS)
    raise TimeoutError(f"Task {task_id} did not complete within {TASK_POLL_TIMEOUT_SECONDS:.0f}s")


async def render_html_with_vault_e2b_stdin() -> int:
    from backend.core.api.app.utils.secrets_manager import SecretsManager
    from backend.shared.providers.e2b_code_runner import get_e2b_api_key_async
    from backend.shared.providers.e2b_html_renderer import render_html_in_e2b

    html = sys.stdin.read()
    viewport_width = int(os.environ.get("OPENMATES_EVAL_VIEWPORT_WIDTH") or "1440")
    viewport_height = int(os.environ.get("OPENMATES_EVAL_VIEWPORT_HEIGHT") or "1200")
    secrets_manager = SecretsManager()
    await secrets_manager.initialize()
    try:
        api_key = await get_e2b_api_key_async(secrets_manager)
        render = render_html_in_e2b(html=html, api_key=api_key, viewport_width=viewport_width, viewport_height=viewport_height)
        print(json.dumps({"screenshot_base64": base64.b64encode(render.screenshot_bytes).decode("ascii"), "duration_seconds": render.duration_seconds}))
        return 0
    finally:
        await secrets_manager.aclose()


def render_trusted_html_fixture_in_e2b(
    html_path: Path,
    *,
    env: dict[str, str],
    viewport_width: int = 1440,
    viewport_height: int = 1200,
) -> tuple[bytes, float]:
    html = html_path.read_text(encoding="utf-8")
    env_key = (env.get("SECRET__E2B__API_KEY") or env.get("E2B_API_KEY") or "").strip()
    if env_key and env_key != "IMPORTED_TO_VAULT":
        from backend.shared.providers.e2b_html_renderer import render_html_in_e2b

        render = render_html_in_e2b(html=html, api_key=env_key, viewport_width=viewport_width, viewport_height=viewport_height)
        return render.screenshot_bytes, render.duration_seconds

    if shutil.which("docker"):
        failures: list[str] = []
        for container in E2B_FIXTURE_RENDER_CONTAINERS:
            result = subprocess.run(
                [
                    "docker",
                    "exec",
                    "-i",
                    "-e",
                    f"OPENMATES_EVAL_VIEWPORT_WIDTH={viewport_width}",
                    "-e",
                    f"OPENMATES_EVAL_VIEWPORT_HEIGHT={viewport_height}",
                    container,
                    "python",
                    "-c",
                    DOCKER_E2B_RENDER_CODE,
                ],
                input=html,
                text=True,
                capture_output=True,
                check=False,
                timeout=E2B_FIXTURE_RENDER_TIMEOUT_SECONDS,
            )
            if result.returncode == 0:
                payload = json.loads(result.stdout)
                return base64.b64decode(payload["screenshot_base64"]), float(payload.get("duration_seconds") or 0.0)
            failures.append(
                f"{container}: exit={result.returncode}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
            )
        raise EvalError("Docker E2B fixture render failed:\n" + "\n\n".join(failures))

    raise EvalError("E2B API key is not available in env and docker fallback is unavailable")


def fixture_mime(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".webp":
        return "image/webp"
    return "image/png"


def prepare_fixture(fixture_id: str, source: Path, *, output_dir: Path, env: dict[str, str]) -> dict[str, Any]:
    if not source.exists():
        raise EvalError(f"Fixture not found: {source}")
    if source.suffix.lower() in {".html", ".htm"}:
        screenshot_bytes, render_seconds = render_trusted_html_fixture_in_e2b(source, env=env)
        if not screenshot_bytes:
            raise EvalError(f"Rendered fixture screenshot is empty: {source}")
        image_path = output_dir / f"{fixture_id}-input.png"
        image_path.write_bytes(screenshot_bytes)
        dimensions = image_dimensions(image_path)
        return {
            "id": fixture_id,
            "source": str(source),
            "input_image_path": image_path,
            "mime_type": "image/png",
            "input_render_seconds": round(render_seconds, 3),
            "width": dimensions[0] if dimensions else 1440,
            "height": dimensions[1] if dimensions else 1200,
        }
    image_path = output_dir / f"{fixture_id}-input{source.suffix.lower() or '.png'}"
    shutil.copyfile(source, image_path)
    if image_path.stat().st_size <= 0:
        raise EvalError(f"Fixture image is empty: {source}")
    dimensions = image_dimensions(image_path)
    return {
        "id": fixture_id,
        "source": str(source),
        "input_image_path": image_path,
        "mime_type": fixture_mime(source),
        "width": dimensions[0] if dimensions else 1440,
        "height": dimensions[1] if dimensions else 1200,
    }


def image_dimensions(path: Path) -> tuple[int, int] | None:
    data = path.read_bytes()
    if len(data) >= 24 and data[:8] == b"\x89PNG\r\n\x1a\n":
        return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
    return None


def download_output_screenshot(result: dict[str, Any], *, output_path: Path) -> bool:
    screenshot = result.get("latest_screenshot")
    download_url = screenshot.get("download_url") if isinstance(screenshot, dict) else None
    if not isinstance(download_url, str) or not download_url:
        return False
    try:
        with urllib.request.urlopen(download_url, timeout=90) as response:
            output_path.write_bytes(response.read())
        return output_path.stat().st_size > 0
    except (urllib.error.URLError, http.client.RemoteDisconnected, TimeoutError) as exc:
        print(f"WARNING: failed to download output screenshot {download_url}: {exc}", file=sys.stderr)
        return False


def run_rest_eval(
    fixture: dict[str, Any],
    *,
    api_url: str,
    api_key: str,
    key_id: str,
    env: dict[str, str],
    output_dir: Path,
    max_correction_passes: int,
) -> dict[str, Any]:
    image_path = Path(fixture["input_image_path"])
    device_id = sdk_device_identity("cli")
    payload = {
        "requests": [
            {
                "image_base64": base64.b64encode(image_path.read_bytes()).decode("ascii"),
                "mime_type": fixture["mime_type"],
                "filename": image_path.name,
                "max_correction_passes": max_correction_passes,
            }
        ]
    }
    started = time.perf_counter()
    try:
        response = request_json(api_url, "POST", "/v1/apps/code/skills/image_to_html", api_key=api_key, payload=payload, device_id=device_id)
    except ApiError as exc:
        if exc.status != 403:
            raise
        approve_pending_key_devices(api_url, key_id, {"cli"}, env=env)
        response = request_json(api_url, "POST", "/v1/apps/code/skills/image_to_html", api_key=api_key, payload=payload, device_id=device_id)

    data = response.get("data") if isinstance(response.get("data"), dict) else {}
    task_id = data.get("task_id")
    embed_id = data.get("embed_id")
    if not isinstance(task_id, str) or not task_id:
        raise EvalError(f"REST response missing task_id: {json.dumps(response)[:500]}")
    result = poll_task(api_url, api_key, task_id, device_id=device_id)
    elapsed = time.perf_counter() - started
    html = result.get("html")
    if not isinstance(html, str) or "<html" not in html.lower():
        raise EvalError(f"REST task {task_id} did not return generated HTML")
    html_path = output_dir / f"{fixture['id']}-output.html"
    html_path.write_text(html, encoding="utf-8")
    output_screenshot_path = output_dir / f"{fixture['id']}-output.png"
    downloaded_screenshot = download_output_screenshot(result, output_path=output_screenshot_path)
    rendered_output_screenshot_path = None
    rendered_output_screenshot_seconds = None
    if not downloaded_screenshot:
        screenshot_bytes, render_seconds = render_trusted_html_fixture_in_e2b(
            html_path,
            env=env,
            viewport_width=int(fixture.get("width") or 1440),
            viewport_height=int(fixture.get("height") or 1200),
        )
        output_screenshot_path.write_bytes(screenshot_bytes)
        rendered_output_screenshot_path = str(output_screenshot_path)
        rendered_output_screenshot_seconds = round(render_seconds, 3)
    usage = result.get("usage") if isinstance(result.get("usage"), dict) else {}
    return {
        "fixture_id": fixture["id"],
        "surface": "rest",
        "task_id": task_id,
        "embed_id": embed_id,
        "elapsed_seconds": round(elapsed, 3),
        "html_path": str(html_path),
        "input_image_path": str(fixture["input_image_path"]),
        "output_screenshot_path": str(output_screenshot_path) if downloaded_screenshot else None,
        "rendered_output_screenshot_path": rendered_output_screenshot_path,
        "rendered_output_screenshot_seconds": rendered_output_screenshot_seconds,
        "downloaded_output_screenshot": downloaded_screenshot,
        "usage": usage,
    }


def run_cli_smoke(fixture: dict[str, Any], *, api_url: str, env: dict[str, str], max_correction_passes: int) -> dict[str, Any]:
    started = time.perf_counter()
    result = run_cli_json(
        [
            "--api-url",
            api_url,
            "apps",
            "code",
            "image_to_html",
            "--file",
            str(fixture["input_image_path"]),
            "--max-correction-passes",
            str(max_correction_passes),
        ],
        env=env,
        timeout=1500,
    )
    elapsed = time.perf_counter() - started
    data = result.get("data") if isinstance(result.get("data"), dict) else result
    if not isinstance(data, dict) or not isinstance(data.get("html"), str):
        raise EvalError(f"CLI image_to_html did not return final HTML: {json.dumps(result)[:500]}")
    return {"surface": "cli", "fixture_id": fixture["id"], "elapsed_seconds": round(elapsed, 3), "usage": data.get("usage") or {}}


def run_npm_sdk_smoke(
    fixture: dict[str, Any],
    *,
    api_url: str,
    api_key: str,
    key_id: str,
    env: dict[str, str],
    max_correction_passes: int,
) -> dict[str, Any]:
    script = """
import { readFileSync } from 'node:fs';
import { performance } from 'node:perf_hooks';
import { OpenMates } from './frontend/packages/openmates-cli/dist/index.js';
const started = performance.now();
const client = new OpenMates({ apiKey: process.env.OPENMATES_SMOKE_API_KEY, apiUrl: process.env.OPENMATES_API_URL, deviceId: process.env.OPENMATES_SMOKE_DEVICE_ID });
const result = await client.apps.code.imageToHtml({ requests: [{ image_base64: readFileSync(process.env.OPENMATES_FIXTURE_PATH).toString('base64'), mime_type: process.env.OPENMATES_FIXTURE_MIME, filename: process.env.OPENMATES_FIXTURE_NAME, max_correction_passes: Number(process.env.OPENMATES_MAX_CORRECTION_PASSES) }] });
console.log(JSON.stringify({ elapsed_seconds: Number(((performance.now() - started) / 1000).toFixed(3)), result }));
"""
    sdk_env = {
        **env,
        "OPENMATES_API_URL": api_url,
        "OPENMATES_SMOKE_API_KEY": api_key,
        "OPENMATES_SMOKE_DEVICE_ID": sdk_device_identity("npm"),
        "OPENMATES_FIXTURE_PATH": str(fixture["input_image_path"]),
        "OPENMATES_FIXTURE_MIME": str(fixture["mime_type"]),
        "OPENMATES_FIXTURE_NAME": Path(fixture["input_image_path"]).name,
        "OPENMATES_MAX_CORRECTION_PASSES": str(max_correction_passes),
    }
    try:
        result = run(["node", "--input-type=module", "-e", script], cwd=ROOT, env=sdk_env, timeout=1500)
    except EvalError as exc:
        if not is_device_approval_error(exc):
            raise
        approve_pending_key_devices(api_url, key_id, {"npm"}, env=env)
        result = run(["node", "--input-type=module", "-e", script], cwd=ROOT, env=sdk_env, timeout=1500)
    payload = json.loads(result.stdout.strip())
    data = payload["result"].get("data") if isinstance(payload.get("result"), dict) else None
    if not isinstance(data, dict) or not isinstance(data.get("html"), str):
        raise EvalError(f"npm SDK did not return final HTML: {payload}")
    return {"surface": "npm", "fixture_id": fixture["id"], "elapsed_seconds": payload["elapsed_seconds"], "usage": data.get("usage") or {}}


def run_pip_sdk_smoke(
    fixture: dict[str, Any],
    *,
    api_url: str,
    api_key: str,
    key_id: str,
    env: dict[str, str],
    max_correction_passes: int,
) -> dict[str, Any]:
    script = """
import base64
import json
import os
import sys
import time

sys.path.insert(0, os.fspath(%r))
from openmates import OpenMates

started = time.perf_counter()
client = OpenMates(api_key=os.environ['OPENMATES_SMOKE_API_KEY'], api_url=os.environ['OPENMATES_API_URL'], device_id=os.environ['OPENMATES_SMOKE_DEVICE_ID'])
with open(os.environ['OPENMATES_FIXTURE_PATH'], 'rb') as handle:
    image_base64 = base64.b64encode(handle.read()).decode('ascii')
result = client.apps.code.image_to_html({'requests': [{'image_base64': image_base64, 'mime_type': os.environ['OPENMATES_FIXTURE_MIME'], 'filename': os.environ['OPENMATES_FIXTURE_NAME'], 'max_correction_passes': int(os.environ['OPENMATES_MAX_CORRECTION_PASSES'])}]})
print(json.dumps({'elapsed_seconds': round(time.perf_counter() - started, 3), 'result': result}))
""" % os.fspath(PYTHON_SDK_PATH)
    sdk_env = {
        **env,
        "OPENMATES_API_URL": api_url,
        "OPENMATES_SMOKE_API_KEY": api_key,
        "OPENMATES_SMOKE_DEVICE_ID": sdk_device_identity("pip"),
        "OPENMATES_FIXTURE_PATH": str(fixture["input_image_path"]),
        "OPENMATES_FIXTURE_MIME": str(fixture["mime_type"]),
        "OPENMATES_FIXTURE_NAME": Path(fixture["input_image_path"]).name,
        "OPENMATES_MAX_CORRECTION_PASSES": str(max_correction_passes),
    }
    try:
        result = run(["python3", "-c", script], cwd=ROOT, env=sdk_env, timeout=1500)
    except EvalError as exc:
        if not is_device_approval_error(exc):
            raise
        approve_pending_key_devices(api_url, key_id, {"pip"}, env=env)
        result = run(["python3", "-c", script], cwd=ROOT, env=sdk_env, timeout=1500)
    payload = json.loads(result.stdout.strip())
    data = payload["result"].get("data") if isinstance(payload.get("result"), dict) else None
    if not isinstance(data, dict) or not isinstance(data.get("html"), str):
        raise EvalError(f"pip SDK did not return final HTML: {payload}")
    return {"surface": "pip", "fixture_id": fixture["id"], "elapsed_seconds": payload["elapsed_seconds"], "usage": data.get("usage") or {}}


def post_to_discord(summary: dict[str, Any], *, files: list[tuple[str, Path]], env: dict[str, str]) -> dict[str, Any] | None:
    webhook = env.get("DISCORD_WEBHOOK_CODE_IMAGE_TO_HTML") or env.get("DISCORD_WEBHOOK_DEV_NIGHTLY")
    if not webhook or webhook == "IMPORTED_TO_VAULT":
        print("DISCORD_WEBHOOK_CODE_IMAGE_TO_HTML and DISCORD_WEBHOOK_DEV_NIGHTLY not set; skipping Discord.", file=sys.stderr)
        return None

    lines = ["Code image_to_html real eval complete", ""]
    for item in summary["rest_evals"]:
        usage = item.get("usage") or {}
        lines.append(
            f"{item['fixture_id']}: {item['elapsed_seconds']}s, credits={usage.get('credits_charged')}, "
            f"provider_usd={usage.get('provider_cost_usd')}, e2b_s={usage.get('e2b_render_seconds')}, "
            f"passes={usage.get('correction_passes_used')}"
        )
    quality_notes = summary.get("quality_notes")
    if isinstance(quality_notes, list) and quality_notes:
        lines.append("")
        lines.append("Quality notes:")
        lines.extend(f"- {note}" for note in quality_notes[:6])
    lines.append("")
    if summary.get("reference_outputs"):
        lines.append("Attachments are grouped as `<fixture>-input`, `<fixture>-reference`, and `<fixture>-openmates`.")
    else:
        lines.append("Attachments are paired as `<fixture>-input` and `<fixture>-openmates`.")
    content = "\n".join(lines)[:1900]
    payload = {"content": content}
    boundary = f"----openmates-{uuid.uuid4().hex}"
    body = bytearray()

    def add_field(name: str, value: bytes, filename: str | None = None, content_type: str = "application/octet-stream") -> None:
        body.extend(f"--{boundary}\r\n".encode("utf-8"))
        disposition = f'Content-Disposition: form-data; name="{name}"'
        if filename:
            disposition += f'; filename="{filename}"'
        body.extend(f"{disposition}\r\n".encode("utf-8"))
        if filename:
            body.extend(f"Content-Type: {content_type}\r\n".encode("utf-8"))
        body.extend(b"\r\n")
        body.extend(value)
        body.extend(b"\r\n")

    add_field("payload_json", json.dumps(payload).encode("utf-8"), content_type="application/json")
    for index, (name, path) in enumerate(files[:10]):
        content_type = "image/png" if path.suffix.lower() == ".png" else "application/json"
        add_field(f"files[{index}]", path.read_bytes(), filename=name, content_type=content_type)
    body.extend(f"--{boundary}--\r\n".encode("utf-8"))
    request = urllib.request.Request(
        f"{webhook}?wait=true",
        data=bytes(body),
        method="POST",
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 OpenMates-Eval/1.0",
        },
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8") or "{}")


def write_summary(summary: dict[str, Any], output_dir: Path) -> Path:
    path = output_dir / "summary.json"
    path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    return path


def parse_fixture(value: str) -> tuple[str, Path]:
    if "=" in value:
        fixture_id, path = value.split("=", 1)
        return fixture_id.strip(), Path(path).expanduser()
    path = Path(value).expanduser()
    return path.stem, path


def parse_reference_outputs(values: list[str] | None) -> dict[str, Path]:
    outputs: dict[str, Path] = {}
    for value in values or []:
        if "=" not in value:
            raise EvalError("--reference-output must use fixture_id=/path/to/output.png")
        fixture_id, path = value.split("=", 1)
        resolved = Path(path).expanduser()
        if not resolved.exists():
            raise EvalError(f"Reference output not found: {resolved}")
        outputs[fixture_id.strip()] = resolved
    return outputs


def main() -> int:
    parser = argparse.ArgumentParser(description="Run real Code image-to-HTML evals and Discord reporting.")
    parser.add_argument("--api-url", default=os.getenv("OPENMATES_API_URL", DEFAULT_API_URL))
    parser.add_argument("--slot", default=os.getenv("OPENMATES_TEST_ACCOUNT_SOURCE_SLOT"))
    parser.add_argument("--fixture", action="append", help="Fixture as id=/path/to/image-or-html. Defaults to original eval fixtures.")
    parser.add_argument("--reference-output", action="append", help="Comparison output as fixture_id=/path/to/reference-output.png; posted to Discord when provided.")
    parser.add_argument("--max-correction-passes", type=int, default=2)
    parser.add_argument("--skip-build", action="store_true")
    parser.add_argument("--skip-cli-sdk", action="store_true", help="Only run REST evals for all fixtures.")
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--no-discord", action="store_true")
    parser.add_argument("--render-html-stdin", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.render_html_stdin:
        return asyncio.run(render_html_with_vault_e2b_stdin())

    api_url = args.api_url.rstrip("/")
    fixtures = [parse_fixture(value) for value in args.fixture] if args.fixture else DEFAULT_FIXTURES
    reference_outputs = parse_reference_outputs(args.reference_output)
    output_dir = (args.output_dir or ROOT / "tmp" / "code-image-to-html-eval" / time.strftime("%Y%m%d-%H%M%S")).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="openmates-code-image-to-html-") as temp_home:
        env = os.environ.copy()
        load_dotenv(env)
        env["HOME"] = temp_home
        env["USERPROFILE"] = temp_home
        env["OPENMATES_API_URL"] = api_url
        setup_cli_session(api_url, env=env, skip_build=args.skip_build, slot=args.slot)
        key_id, api_key = create_api_key(api_url, env=env)
        try:
            prepared = [prepare_fixture(fixture_id, path, output_dir=output_dir, env=env) for fixture_id, path in fixtures]
            rest_evals = [
                run_rest_eval(
                    fixture,
                    api_url=api_url,
                    api_key=api_key,
                    key_id=key_id,
                    env=env,
                    output_dir=output_dir,
                    max_correction_passes=args.max_correction_passes,
                )
                for fixture in prepared
            ]
            surface_smokes: list[dict[str, Any]] = []
            if not args.skip_cli_sdk and prepared:
                smoke_fixture = prepared[0]
                surface_smokes.append(run_cli_smoke(smoke_fixture, api_url=api_url, env=env, max_correction_passes=0))
                surface_smokes.append(run_npm_sdk_smoke(smoke_fixture, api_url=api_url, api_key=api_key, key_id=key_id, env=env, max_correction_passes=0))
                surface_smokes.append(run_pip_sdk_smoke(smoke_fixture, api_url=api_url, api_key=api_key, key_id=key_id, env=env, max_correction_passes=0))

            summary = {
                "success": True,
                "api_url": api_url,
                "output_dir": str(output_dir),
                "max_correction_passes": args.max_correction_passes,
                "fixtures": [{key: str(value) if isinstance(value, Path) else value for key, value in fixture.items()} for fixture in prepared],
                "reference_outputs": {key: str(value) for key, value in reference_outputs.items()},
                "rest_evals": rest_evals,
                "surface_smokes": surface_smokes,
            }
            summary_path = write_summary(summary, output_dir)
            discord_result = None
            if not args.no_discord:
                attachments: list[tuple[str, Path]] = []
                for item in rest_evals:
                    attachments.append((f"{item['fixture_id']}-input.png", Path(item["input_image_path"])))
                    reference_output = reference_outputs.get(str(item["fixture_id"]))
                    if reference_output:
                        attachments.append((f"{item['fixture_id']}-reference.png", reference_output))
                    if item.get("output_screenshot_path"):
                        attachments.append((f"{item['fixture_id']}-openmates.png", Path(item["output_screenshot_path"])))
                    elif item.get("rendered_output_screenshot_path"):
                        attachments.append((f"{item['fixture_id']}-openmates.png", Path(item["rendered_output_screenshot_path"])))
                attachments.append(("summary.json", summary_path))
                discord_result = post_to_discord(summary, files=attachments, env=env)
                summary["discord"] = {"message_id": discord_result.get("id")} if isinstance(discord_result, dict) else None
                write_summary(summary, output_dir)
            print(json.dumps(summary, indent=2, sort_keys=True))
            return 0
        finally:
            revoke_api_key(key_id, api_url, env=env)


if __name__ == "__main__":
    raise SystemExit(main())
