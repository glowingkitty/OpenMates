#!/usr/bin/env python3
"""Verify live audio generated assets through REST, CLI, npm SDK, and pip SDK.

Purpose: prove the deployed audio app skills return async generated-asset
metadata across every developer surface, without persisting API keys, prompts,
or signed download URLs. Architecture: docs/specs/elevenlabs-audio-skills.
Security: creates a temporary developer API key, approves only the needed SDK
devices, downloads audio only to hash byte payloads, then revokes the key.
Run: OPENMATES_LIVE_AUDIO_SDK_SMOKE=1 python3 scripts/verify_audio_sdk_cli_live_smoke.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_API_URL = "https://api.dev.openmates.org"
DEFAULT_CLI = "/home/superdev/.npm-global/bin/openmates"
DEFAULT_NPM_GENERATED_ENTRY = REPO_ROOT / "frontend/packages/openmates-cli/src/generated/appSkills.ts"
PYTHON_SDK_PATH = REPO_ROOT / "packages/openmates-python"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "docs/specs/elevenlabs-audio-skills/artifacts"
DEFAULT_SPEECH_MODEL = "eleven_v3"
SOUND_MODEL = "eleven_text_to_sound_v2"

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from generate_audio_sample_artifacts import (  # noqa: E402
    _create_temp_api_key,
    _download_generated_audio,
    _poll_task_result,
    _post_skill,
    _redact,
    _revoke_temp_api_key,
    _unwrap_skill_payload,
)
from sdk_cli_parity_live_smoke import (  # noqa: E402
    _approve_pending_key_devices,
    _is_device_approval_error,
    _parse_json_output,
)


def _device_identity(access_type: str) -> str:
    machine = platform.machine().lower()
    arch = {"x86_64": "x64", "amd64": "x64", "aarch64": "arm64"}.get(machine, machine)
    return f"{access_type}:{platform.system().lower()}:{arch}:audio-live-smoke"


def _run_json(command: list[str], *, env: dict[str, str], description: str) -> dict[str, Any]:
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
            f"stdout:\n{_redact(result.stdout)}\n"
            f"stderr:\n{_redact(result.stderr)}"
        )
    return _parse_json_output(result.stdout)


def _rest_call(
    *,
    api_url: str,
    api_key: str,
    device_id: str,
    app_id: str,
    skill_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    response = _post_skill(
        api_url=api_url,
        api_key=api_key,
        device_id=device_id,
        app_id=app_id,
        skill_id=skill_id,
        payload=payload,
    )
    skill_payload = _unwrap_skill_payload(response)
    results = skill_payload.get("results")
    if not isinstance(results, list) or not results or not isinstance(results[0], dict):
        raise RuntimeError(f"{app_id}.{skill_id} returned no result object")
    first = results[0]
    if first.get("status") == "processing":
        task_id = first.get("task_id") or skill_payload.get("task_id")
        if not isinstance(task_id, str) or not task_id:
            raise RuntimeError(f"{app_id}.{skill_id} processing response omitted task_id")
        first = _poll_task_result(api_url=api_url, api_key=api_key, device_id=device_id, task_id=task_id)
    return first


def _cli_call(*, cli_path: str, env: dict[str, str], app_id: str, skill_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    return _run_json(
        [cli_path, "apps", app_id, skill_id, "--input", json.dumps(payload, separators=(",", ":")), "--json"],
        env=env,
        description=f"CLI {app_id}.{skill_id}",
    )


def _npm_call(*, generated_entry: Path, env: dict[str, str], skill: str, payload: dict[str, Any]) -> dict[str, Any]:
    if not generated_entry.exists():
        raise RuntimeError(f"Missing npm generated app-skill entry at {generated_entry}")
    method = "generate" if skill == "generate" else "speak"
    script = f"""
      import {{ GeneratedAppSkills }} from {json.dumps(generated_entry.as_uri())};
      const headers = {{
        'Accept': 'application/json',
        'Authorization': `Bearer ${{process.env.OPENMATES_SMOKE_API_KEY}}`,
        'Content-Type': 'application/json',
        'X-OpenMates-SDK': 'npm',
        'X-OpenMates-Device-Identity': process.env.OPENMATES_SMOKE_DEVICE_ID,
      }};
      const apiUrl = process.env.OPENMATES_API_URL.replace(/\\/$/, '');
      const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
      async function requestJson(url, options) {{
        const response = await fetch(url, options);
        const text = await response.text();
        const data = text ? JSON.parse(text) : {{}};
        if (!response.ok) throw new Error(`HTTP ${{response.status}}: ${{text}}`);
        return data;
      }}
      async function pollTask(taskId) {{
        const started = Date.now();
        while (Date.now() - started < 240000) {{
          const task = await requestJson(`${{apiUrl}}/v1/tasks/${{encodeURIComponent(taskId)}}`, {{ method: 'GET', headers }});
          if (task.status === 'completed') return task.result;
          if (task.status === 'failed') throw new Error(task.error || 'Task failed');
          await sleep(2000);
        }}
        throw new Error(`Task ${{taskId}} did not complete`);
      }}
      const apps = new GeneratedAppSkills(async (appId, skillId, input) => {{
        const response = await requestJson(`${{apiUrl}}/v1/apps/${{appId}}/skills/${{skillId}}`, {{
          method: 'POST',
          headers,
          body: JSON.stringify(input),
        }});
        const data = response?.data ?? response;
        const taskId = typeof data?.task_id === 'string' ? data.task_id : null;
        if (taskId) return await pollTask(taskId);
        return response;
      }});
      const response = await apps.audio.{method}({json.dumps(payload)});
      console.log(JSON.stringify(response));
    """
    result = subprocess.run(
        ["node", "--experimental-strip-types", "--input-type=module", "-e", script],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"npm SDK audio.{skill} failed with exit {result.returncode}\n"
            f"stdout:\n{_redact(result.stdout)}\n"
            f"stderr:\n{_redact(result.stderr)}"
        )
    return json.loads(result.stdout.strip())


def _pip_call(*, env: dict[str, str], skill: str, payload: dict[str, Any]) -> dict[str, Any]:
    method = "generate" if skill == "generate" else "speak"
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
response = getattr(client.apps.audio, %r)(%s)
print(json.dumps(response))
""" % (os.fspath(PYTHON_SDK_PATH), method, repr(payload))
    result = subprocess.run(
        ["python3", "-c", script],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"pip SDK audio.{skill} failed with exit {result.returncode}\n"
            f"stdout:\n{_redact(result.stdout)}\n"
            f"stderr:\n{_redact(result.stderr)}"
        )
    return json.loads(result.stdout.strip())


def _extract_result(response: dict[str, Any]) -> dict[str, Any]:
    current: Any = response
    for _ in range(4):
        if not isinstance(current, dict):
            break
        if current.get("status") == "finished" and isinstance(current.get("files"), dict):
            return current
        results = current.get("results")
        if isinstance(results, list) and results and isinstance(results[0], dict):
            current = results[0]
            continue
        data = current.get("data")
        if isinstance(data, dict):
            current = data
            continue
        result = current.get("result")
        if isinstance(result, dict):
            current = result
            continue
        break
    raise RuntimeError(f"Could not find finished generated-audio result in response: {json.dumps(response)[:500]}")


def _assert_generated_asset(
    *,
    client: str,
    skill: str,
    response: dict[str, Any],
    expected_generation_type: str,
    expected_model: str | None = None,
) -> dict[str, Any]:
    response_text = json.dumps(response, sort_keys=True)
    if "audio_base64" in response_text:
        raise RuntimeError(f"{client} audio.{skill} leaked audio_base64")
    result = _extract_result(response)
    if result.get("generation_type") != expected_generation_type:
        raise RuntimeError(f"{client} audio.{skill} generation type mismatch: {result!r}")
    if expected_model and result.get("model") != expected_model:
        raise RuntimeError(f"{client} audio.{skill} model mismatch: {result.get('model')!r}")
    files = result.get("files")
    original = files.get("original") if isinstance(files, dict) else None
    download_url = original.get("download_url") if isinstance(original, dict) else None
    if not isinstance(download_url, str) or not download_url.startswith(("https://", "http://")):
        raise RuntimeError(f"{client} audio.{skill} missing generated-asset download URL")
    audio_bytes = _download_generated_audio(download_url)
    return {
        "client": client,
        "skill": f"audio.{skill}",
        "status": result.get("status"),
        "generation_type": result.get("generation_type"),
        "provider": result.get("provider"),
        "model": result.get("model"),
        "mime_type": result.get("mime_type"),
        "duration_seconds": result.get("duration_seconds"),
        "credits_charged": result.get("credits_charged"),
        "byte_length": len(audio_bytes),
        "sha256": hashlib.sha256(audio_bytes).hexdigest(),
        "has_download_url": True,
        "inline_audio_base64_present": False,
        "signed_download_url_persisted": False,
    }


def _call_with_device_approval(
    call: Any,
    *,
    api_url: str,
    key_id: str | None,
    access_type: str,
) -> dict[str, Any]:
    try:
        return call()
    except RuntimeError as exc:
        if not key_id or not _is_device_approval_error(exc):
            raise
        _approve_pending_key_devices(api_url, key_id, {access_type})
        return call()


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify live audio REST/CLI/SDK generated-asset outputs.")
    parser.add_argument("--api-url", default=os.getenv("OPENMATES_API_URL", DEFAULT_API_URL))
    parser.add_argument("--cli", default=os.getenv("OPENMATES_CLI", DEFAULT_CLI))
    parser.add_argument("--skip-cli-reason", default="")
    parser.add_argument("--npm-generated-entry", type=Path, default=DEFAULT_NPM_GENERATED_ENTRY)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()

    if os.getenv("OPENMATES_LIVE_AUDIO_SDK_SMOKE") != "1":
        print("Refusing to run live audio SDK smoke. Set OPENMATES_LIVE_AUDIO_SDK_SMOKE=1 to opt in.", file=sys.stderr)
        return 2

    run_id = f"audio-sdk-cli-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}"
    api_key = ""
    key_id: str | None = None
    cli_key_env: dict[str, str] | None = None
    revoked = False
    checks: list[dict[str, Any]] = []

    try:
        api_key, key_id, cli_key_env = _create_temp_api_key(cli_path=args.cli, api_url=args.api_url, name=run_id)

        rest_device_id = _device_identity("cli")
        rest_response = _call_with_device_approval(
            lambda: _rest_call(
                api_url=args.api_url,
                api_key=api_key,
                device_id=rest_device_id,
                app_id="audio",
                skill_id="speak",
                payload={
                    "requests": [
                        {
                            "id": f"{run_id}-rest-speak-default",
                            "text": "Audio verification complete.",
                            "provider": "elevenlabs",
                            "voice": "warm_neutral",
                            "output_format": "mp3_44100_128",
                        }
                    ]
                },
            ),
            api_url=args.api_url,
            key_id=key_id,
            access_type="cli",
        )
        checks.append(
            _assert_generated_asset(
                client="rest",
                skill="speak",
                response=rest_response,
                expected_generation_type="speech",
                expected_model=DEFAULT_SPEECH_MODEL,
            )
        )

        if args.skip_cli_reason:
            checks.append(
                {
                    "client": "cli",
                    "skill": "audio.generate",
                    "status": "blocked",
                    "reason": args.skip_cli_reason,
                }
            )
        else:
            cli_env = os.environ.copy()
            cli_env["OPENMATES_API_URL"] = args.api_url
            cli_env["OPENMATES_API_KEY"] = api_key
            cli_env["OPENMATES_SMOKE_DEVICE_ID"] = _device_identity("cli")
            cli_response = _call_with_device_approval(
                lambda: _cli_call(
                    cli_path=args.cli,
                    env=cli_env,
                    app_id="audio",
                    skill_id="generate",
                    payload={
                        "requests": [
                            {
                                "id": f"{run_id}-cli-generate",
                                "prompt": "tiny positive interface tick, no speech, no music",
                                "provider": "elevenlabs",
                                "duration_seconds": 0.8,
                                "prompt_influence": 0.35,
                                "output_format": "mp3_44100_128",
                                "model": SOUND_MODEL,
                            }
                        ]
                    },
                ),
                api_url=args.api_url,
                key_id=key_id,
                access_type="cli",
            )
            checks.append(
                _assert_generated_asset(
                    client="cli",
                    skill="generate",
                    response=cli_response,
                    expected_generation_type="sound_effect",
                    expected_model=SOUND_MODEL,
                )
            )

        npm_env = os.environ.copy()
        npm_env["OPENMATES_API_URL"] = args.api_url
        npm_env["OPENMATES_SMOKE_API_KEY"] = api_key
        npm_env["OPENMATES_SMOKE_DEVICE_ID"] = _device_identity("npm")
        npm_response = _call_with_device_approval(
            lambda: _npm_call(
                generated_entry=args.npm_generated_entry,
                env=npm_env,
                skill="speak",
                payload={
                    "requests": [
                        {
                            "id": f"{run_id}-npm-speak-default",
                            "text": "NPM audio verification complete.",
                            "provider": "elevenlabs",
                            "voice": "warm_neutral",
                            "output_format": "mp3_44100_128",
                        }
                    ]
                },
            ),
            api_url=args.api_url,
            key_id=key_id,
            access_type="npm",
        )
        checks.append(
            _assert_generated_asset(
                client="npm",
                skill="speak",
                response=npm_response,
                expected_generation_type="speech",
                expected_model=DEFAULT_SPEECH_MODEL,
            )
        )

        pip_env = os.environ.copy()
        pip_env["OPENMATES_API_URL"] = args.api_url
        pip_env["OPENMATES_SMOKE_API_KEY"] = api_key
        pip_env["OPENMATES_SMOKE_DEVICE_ID"] = _device_identity("pip")
        pip_response = _call_with_device_approval(
            lambda: _pip_call(
                env=pip_env,
                skill="generate",
                payload={
                    "requests": [
                        {
                            "id": f"{run_id}-pip-generate",
                            "prompt": "brief friendly confirmation click, no speech, no music",
                            "provider": "elevenlabs",
                            "duration_seconds": 0.8,
                            "prompt_influence": 0.35,
                            "output_format": "mp3_44100_128",
                            "model": SOUND_MODEL,
                        }
                    ]
                },
            ),
            api_url=args.api_url,
            key_id=key_id,
            access_type="pip",
        )
        checks.append(
            _assert_generated_asset(
                client="pip",
                skill="generate",
                response=pip_response,
                expected_generation_type="sound_effect",
                expected_model=SOUND_MODEL,
            )
        )
    finally:
        if cli_key_env is not None:
            revoked = _revoke_temp_api_key(cli_path=args.cli, env=cli_key_env, key_id=key_id)

    manifest = {
        "run_id": run_id,
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "api_url": args.api_url,
        "endpoint_access_model": "developer_api_key_rest",
        "auth": {
            "temporary_api_key_created": True,
            "temporary_api_key_revoked": revoked,
            "access_types": ["cli", "npm", "pip"],
        },
        "privacy": {
            "api_key_persisted": False,
            "inline_audio_base64_persisted": False,
            "signed_download_url_persisted": False,
            "prompts_persisted": False,
        },
        "checks": checks,
    }
    output_dir = args.output_dir / datetime.now(UTC).strftime("%Y-%m-%d")
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / f"{run_id}.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"run_id": run_id, "manifest": str(manifest_path.relative_to(REPO_ROOT)), "checks": len(checks)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
