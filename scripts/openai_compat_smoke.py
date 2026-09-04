#!/usr/bin/env python3
"""Live smoke test for OpenMates' OpenAI-compatible `/v1` API.

Requires `OPENMATES_TEST_ACCOUNT_API_KEY` or `--create-api-key-from-cli-session`
and the official `openai` Python package. The script targets the dev API by
default, discovers a model from `/v1/models`, then checks model retrieval, text
chat, streaming, forced function tool calls, and a tool-result follow-up through
the official SDK.
"""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from pathlib import Path
import subprocess
import sys
import time
from typing import Any
import argparse
import uuid
from urllib import request as urllib_request
from urllib.error import HTTPError


DEFAULT_BASE_URL = "https://api.dev.openmates.org/v1"
DEFAULT_ORIGIN = "https://app.dev.openmates.org"
DEFAULT_DEVICE_ID = "openai-compat-smoke"
DEFAULT_MAX_TOKENS = 128
STANDARDIZED_AI_ERROR_PREFIX = "The AI service encountered an error while processing your request."
REPO_ROOT = Path(__file__).resolve().parents[1]
CLI_DIST = REPO_ROOT / "frontend/packages/openmates-cli/dist/cli.js"
CLI_TIMEOUT_SECONDS = 90
HTTP_TIMEOUT_SECONDS = 30
SDK_TIMEOUT_SECONDS = 90


def _stage(message: str) -> None:
    print(f"[openai-compat] {message}", flush=True)


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise SystemExit(f"Missing required environment variable: {name}")
    return value


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Smoke test OpenMates' OpenAI-compatible API.")
    parser.add_argument("--base-url", default=os.getenv("OPENMATES_OPENAI_COMPAT_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument("--origin", default=os.getenv("OPENMATES_OPENAI_COMPAT_ORIGIN", DEFAULT_ORIGIN))
    parser.add_argument("--model", default=os.getenv("OPENMATES_OPENAI_COMPAT_MODEL"))
    parser.add_argument(
        "--required-model",
        action="append",
        default=[],
        help="Require a model ID in /v1/models; repeat for multiple IDs.",
    )
    parser.add_argument("--mode", default="all", help="Accepted for spec command compatibility; this script runs the full smoke.")
    parser.add_argument("--device-id", default=DEFAULT_DEVICE_ID)
    parser.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    parser.add_argument(
        "--create-api-key-from-cli-session",
        action="store_true",
        help="Create and revoke a temporary API key using the current logged-in CLI session.",
    )
    return parser.parse_args()


def _api_url_from_base_url(base_url: str) -> str:
    return base_url.removesuffix("/").removesuffix("/v1")


def _validate_cli_session_api_url(api_url: str) -> None:
    expected_api_url = _api_url_from_base_url(DEFAULT_BASE_URL)
    if api_url != expected_api_url:
        raise RuntimeError(
            "--create-api-key-from-cli-session is restricted to "
            f"{expected_api_url}; use OPENMATES_TEST_ACCOUNT_API_KEY for custom API URLs"
        )


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


def _find_api_key_id_by_name(*, api_url: str, env: dict[str, str], name: str) -> str | None:
    listed = _run_cli_json(["settings", "developers", "api-keys", "list"], api_url=api_url, env=env)
    matching_ids = []
    for key in listed.get("api_keys", []):
        if isinstance(key, dict) and key.get("name") == name and isinstance(key.get("id"), str):
            matching_ids.append(key["id"])
    return matching_ids[0] if len(matching_ids) == 1 else None


def _run_cli_json(args: list[str], *, api_url: str, env: dict[str, str]) -> dict[str, Any]:
    if not CLI_DIST.exists():
        raise RuntimeError("Missing CLI dist/cli.js. Run: cd frontend/packages/openmates-cli && npm run build")
    command = ["node", os.fspath(CLI_DIST), *args, "--json"]
    try:
        result = subprocess.run(
            command,
            cwd=REPO_ROOT,
            env={**env, "OPENMATES_API_URL": api_url},
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=CLI_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        safe_command = " ".join(command[:4])
        raise RuntimeError(f"CLI command timed out after {CLI_TIMEOUT_SECONDS}s: {safe_command} ...") from exc
    if result.returncode != 0:
        raise RuntimeError(f"CLI command failed with exit {result.returncode}: {result.stderr or result.stdout}")
    return _parse_json_output(result.stdout)


def _session_cookie_header() -> str:
    session_path = Path.home() / ".openmates" / "session.json"
    if not session_path.exists():
        raise RuntimeError("No logged-in CLI session found; run `openmates login` before temporary-key smoke.")
    session = json.loads(session_path.read_text(encoding="utf-8"))
    cookies = session.get("cookies") or {}
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
        with urllib_request.urlopen(req, timeout=HTTP_TIMEOUT_SECONDS) as response:
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
        if device.get("api_key_id") != key_id or device.get("approved_at"):
            continue
        if device.get("access_type") not in access_types:
            continue
        device_id = device.get("id")
        if not isinstance(device_id, str):
            continue
        _settings_request(api_url, f"api-key-devices/{device_id}/approve", method="POST")
        approved.append(device_id)
    return approved


def _is_device_approval_error(exc: Exception) -> bool:
    message = str(exc)
    return "approved_device_required" in message or "New device detected" in message or "HTTP 403" in message


@contextmanager
def _api_key_from_cli_session(api_url: str, name: str):
    env = os.environ.copy()
    primary_error: BaseException | None = None
    key_id: str | None = None
    _stage("creating temporary API key from CLI session")
    try:
        created = _run_cli_json(["settings", "developers", "api-keys", "create", name, "--yes"], api_url=api_url, env=env)
        api_key = created.get("api_key")
        key_id = _api_key_id(created)
        if not isinstance(api_key, str) or not api_key.startswith("sk-api-"):
            raise RuntimeError("CLI did not return a one-time API key")
        if not isinstance(key_id, str) or not key_id:
            raise RuntimeError("CLI did not return API key id")
        _stage(f"created temporary API key id={key_id}")
        yield api_key, key_id
    except BaseException as exc:
        primary_error = exc
        raise
    finally:
        try:
            if key_id is None:
                key_id = _find_api_key_id_by_name(api_url=api_url, env=env, name=name)
            if key_id is None:
                if primary_error is None:
                    raise RuntimeError(f"could not locate temporary API key named {name!r} for revocation")
                print(
                    f"WARNING: could not locate temporary API key named {name!r} for revocation",
                    file=sys.stderr,
                )
            else:
                _stage(f"revoking temporary API key id={key_id}")
                _run_cli_json(["settings", "developers", "api-keys", "revoke", key_id, "--yes"], api_url=api_url, env=env)
                _stage(f"revoked temporary API key id={key_id}")
        except Exception as exc:  # noqa: BLE001 - cleanup must not mask smoke result.
            message = f"failed to revoke temporary API key {key_id}: {exc}"
            if primary_error is not None:
                print(f"WARNING: {message}", file=sys.stderr)
            else:
                raise RuntimeError(message) from exc


def _client(args: argparse.Namespace, api_key: str | None = None) -> Any:
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise SystemExit("Install the official OpenAI Python SDK to run this smoke test: pip install openai") from exc

    return OpenAI(
        api_key=api_key or _require_env("OPENMATES_TEST_ACCOUNT_API_KEY"),
        base_url=args.base_url,
        timeout=SDK_TIMEOUT_SECONDS,
        default_headers={
            "Origin": args.origin,
            "X-OpenMates-SDK": "rest_api",
            "X-OpenMates-Device-Identity": args.device_id,
        },
    )


def _list_model_ids(client: Any) -> list[str]:
    return sorted(str(model.id) for model in client.models.list().data)


def _pick_model(client: Any, configured_model: str | None) -> str:
    model_ids = _list_model_ids(client)
    if not model_ids:
        raise SystemExit("/v1/models returned no models")
    if configured_model:
        if configured_model not in model_ids:
            preview = ", ".join(model_ids[:20])
            raise SystemExit(
                f"/v1/models did not include configured model {configured_model!r}; "
                f"available_count={len(model_ids)} available_prefix=[{preview}]"
            )
        return configured_model
    return model_ids[0]


def _validate_required_models(client: Any, required_models: list[str]) -> None:
    if not required_models:
        return
    model_ids = set(_list_model_ids(client))
    missing_models = sorted(set(required_models) - model_ids)
    if missing_models:
        raise SystemExit(f"/v1/models omitted required model IDs: {', '.join(missing_models)}")
    _stage(f"required_models={','.join(required_models)}")


def _assert_completion_text(label: str, text: str) -> None:
    stripped = text.strip()
    assert stripped, f"{label} returned empty content"
    assert not stripped.startswith(STANDARDIZED_AI_ERROR_PREFIX), f"{label} returned standardized AI error text: {stripped!r}"


def _run_smoke(args: argparse.Namespace, api_key: str | None = None) -> None:
    client = _client(args, api_key)
    _stage("listing models")
    _validate_required_models(client, args.required_model)
    model = _pick_model(client, args.model)
    _stage(f"model={model}")

    _stage("retrieving model")
    retrieved = client.models.retrieve(model)
    assert retrieved.id == model, f"Unexpected model retrieve result: {retrieved}"

    _stage("creating plain chat completion")
    text_response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": "Reply with exactly: OK"}],
        max_tokens=args.max_tokens,
        temperature=0,
    )
    text = text_response.choices[0].message.content or ""
    _assert_completion_text("Plain chat completion", text)
    _stage(f"text={text[:80]!r}")

    _stage("creating streaming chat completion")
    stream_chunks = []
    stream = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": "Reply with one short word."}],
        max_tokens=args.max_tokens,
        temperature=0,
        stream=True,
    )
    for chunk in stream:
        delta = chunk.choices[0].delta
        if delta.content:
            stream_chunks.append(delta.content)
    _assert_completion_text("Streaming chat completion", "".join(stream_chunks))
    _stage(f"stream={''.join(stream_chunks)[:80]!r}")

    tools = [
        {
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "Get weather for a city.",
                "parameters": {
                    "type": "object",
                    "properties": {"city": {"type": "string"}},
                    "required": ["city"],
                },
            },
        }
    ]
    _stage("creating forced tool-call completion")
    tool_response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": "What is the weather in Berlin?"}],
        max_tokens=args.max_tokens,
        tools=tools,
        tool_choice={"type": "function", "function": {"name": "get_weather"}},
    )
    tool_calls = tool_response.choices[0].message.tool_calls or []
    assert len(tool_calls) == 1, f"Forced function tool call returned {len(tool_calls)} tool_calls instead of one"
    assert tool_calls[0].function.name == "get_weather"
    assert tool_calls[0].id, "Forced function tool call returned no tool_call id"
    _stage(f"tool_call={tool_calls[0].id}:{tool_calls[0].function.name}")

    _stage("creating tool-result follow-up completion")
    followup = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "user", "content": "What is the weather in Berlin?"},
            tool_response.choices[0].message,
            {"role": "tool", "tool_call_id": tool_calls[0].id, "content": '{"weather":"sunny"}'},
            {"role": "user", "content": "Summarize the weather in five words."},
        ],
        max_tokens=args.max_tokens,
        tools=tools,
    )
    final_text = followup.choices[0].message.content or ""
    _assert_completion_text("Tool follow-up", final_text)
    _stage(f"followup={final_text[:80]!r}")
    _stage("python SDK smoke passed")


def main() -> int:
    args = _parse_args()
    if args.create_api_key_from_cli_session:
        api_url = _api_url_from_base_url(args.base_url)
        _validate_cli_session_api_url(api_url)
        name = f"openai-compat-smoke-{time.time_ns()}-{uuid.uuid4().hex}"
        with _api_key_from_cli_session(api_url, name) as (temporary_api_key, key_id):
            try:
                _run_smoke(args, temporary_api_key)
            except Exception as exc:
                if not _is_device_approval_error(exc):
                    raise
                _stage("approving pending API-key device")
                approved_devices = _approve_pending_key_devices(api_url, key_id, {"rest_api", "cli"})
                if not approved_devices:
                    raise RuntimeError("No pending API-key device was available to approve") from exc
                _stage(f"approved {len(approved_devices)} pending API-key device(s); retrying smoke")
                _run_smoke(args, temporary_api_key)
        return 0

    _run_smoke(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
