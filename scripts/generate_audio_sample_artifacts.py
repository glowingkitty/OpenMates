#!/usr/bin/env python3
"""Generate live OpenMates audio sample artifacts.

Purpose: call audio app-skill REST endpoints against the real dev API and save
MP3 evidence for spec review. Architecture: docs/specs/elevenlabs-audio-skills.
Security: temporary API keys, webhook URLs, raw prompts, and audio_base64 values
are never printed or persisted in the manifest. The temp key is revoked on exit.
Run: OPENMATES_LIVE_AUDIO_SAMPLES=1 python3 scripts/generate_audio_sample_artifacts.py --plan-json <path>
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib import request as urllib_request
from urllib.error import HTTPError, URLError


REPO_ROOT = Path(__file__).resolve().parents[1]
CONTROL_PLANE_ROOT = REPO_ROOT.parent.parent if REPO_ROOT.parent.name == ".openmates-agent-worktrees" else REPO_ROOT
DEFAULT_API_URL = "https://api.dev.openmates.org"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "docs/specs/elevenlabs-audio-skills/artifacts"
DEFAULT_CLI = "/home/superdev/.npm-global/bin/openmates"
SECRET_PATTERN = re.compile(r"sk-api-[A-Za-z0-9._-]+")

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from discord_webhook import post_attachment  # noqa: E402
from sdk_cli_parity_live_smoke import (  # noqa: E402
    _api_key_id,
    _approve_pending_key_devices,
    _is_device_approval_error,
    _parse_json_output,
)


def _load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            values[key] = value
    return values


def _redact(value: str) -> str:
    return SECRET_PATTERN.sub("sk-api-<redacted>", value)


def _run_cli_json(command: list[str], *, env: dict[str, str], description: str) -> dict[str, Any]:
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


def _device_identity() -> str:
    machine = platform.machine().lower()
    arch = {"x86_64": "x64", "amd64": "x64", "aarch64": "arm64"}.get(machine, machine)
    return f"cli:{platform.system().lower()}:{arch}:audio-samples"


def _create_temp_api_key(*, cli_path: str, api_url: str, name: str) -> tuple[str, str | None, dict[str, str]]:
    env = os.environ.copy()
    env["OPENMATES_API_URL"] = api_url
    result = _run_cli_json(
        [cli_path, "settings", "developers", "api-keys", "create", name, "--yes", "--json"],
        env=env,
        description="CLI API-key creation",
    )
    api_key = result.get("api_key")
    if not isinstance(api_key, str) or not api_key.startswith("sk-api-"):
        raise RuntimeError("CLI did not return a one-time API key")
    key_id = _api_key_id(result)
    return api_key, key_id, env


def _revoke_temp_api_key(*, cli_path: str, env: dict[str, str], key_id: str | None) -> bool:
    if not key_id:
        return False
    result = subprocess.run(
        [cli_path, "settings", "developers", "api-keys", "revoke", key_id, "--yes", "--json"],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    return result.returncode == 0


def _post_skill(
    *,
    api_url: str,
    api_key: str,
    device_id: str,
    app_id: str,
    skill_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    request = urllib_request.Request(
        f"{api_url.rstrip('/')}/v1/apps/{app_id}/skills/{skill_id}",
        data=body,
        method="POST",
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "X-OpenMates-SDK": "cli",
            "X-OpenMates-Device-Identity": device_id,
        },
    )
    try:
        with urllib_request.urlopen(request, timeout=90) as response:
            return json.loads(response.read().decode("utf-8") or "{}")
    except HTTPError as exc:
        body_text = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{app_id}.{skill_id} failed with HTTP {exc.code}: {_redact(body_text[:1200])}") from exc
    except (URLError, TimeoutError) as exc:
        raise RuntimeError(f"{app_id}.{skill_id} request failed: {exc}") from exc


def _unwrap_skill_payload(response: dict[str, Any]) -> dict[str, Any]:
    current: Any = response
    for _ in range(3):
        if not isinstance(current, dict):
            break
        if current.get("success") is False:
            raise RuntimeError(str(current.get("error") or "skill returned success=false"))
        if "results" in current:
            return current
        data = current.get("data")
        if not isinstance(data, dict):
            break
        current = data
    raise RuntimeError(f"Skill response did not include results: {json.dumps(response, sort_keys=True)[:500]}")


def _load_plan(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    samples = data.get("samples") if isinstance(data, dict) else None
    if not isinstance(samples, list) or not samples:
        raise RuntimeError("Plan JSON must contain a non-empty samples array")
    for sample in samples:
        if not isinstance(sample, dict):
            raise RuntimeError("Each sample must be an object")
        for field in ("id", "filename", "app", "skill", "payload"):
            if field not in sample:
                raise RuntimeError(f"Sample missing required field: {field}")
    return samples


def _plan_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_sample(
    *,
    output_dir: Path,
    sample: dict[str, Any],
    response: dict[str, Any],
    latency_ms: int,
    webhook_url: str,
) -> dict[str, Any]:
    payload = _unwrap_skill_payload(response)
    results = payload.get("results")
    if not isinstance(results, list) or not results:
        raise RuntimeError(f"{sample['id']} returned no results")
    first = results[0]
    if not isinstance(first, dict) or first.get("status") != "finished":
        raise RuntimeError(f"{sample['id']} did not finish: {first!r}")
    audio_base64 = first.get("audio_base64")
    if not isinstance(audio_base64, str) or not audio_base64:
        raise RuntimeError(f"{sample['id']} returned no audio_base64")
    audio = base64.b64decode(audio_base64, validate=True)
    filename = str(sample["filename"])
    if not filename.endswith(".mp3") or "/" in filename or ".." in filename:
        raise RuntimeError(f"Unsafe sample filename: {filename}")
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / filename
    path.write_bytes(audio)

    discord_result = None
    if webhook_url:
        discord_result = post_attachment(
            webhook_url=webhook_url,
            payload={"content": f"OpenMates audio sample: `{filename}`"},
            content=audio,
            filename=filename,
            timeout=45,
        )

    return {
        "id": sample["id"],
        "file": str(path.relative_to(REPO_ROOT)),
        "app": sample["app"],
        "skill": sample["skill"],
        "status": first.get("status"),
        "generation_type": first.get("generation_type"),
        "provider": first.get("provider") or payload.get("provider"),
        "model": first.get("model"),
        "voice": first.get("voice"),
        "mime_type": first.get("mime_type"),
        "duration_seconds": first.get("duration_seconds"),
        "byte_length": len(audio),
        "sha256": hashlib.sha256(audio).hexdigest(),
        "latency_ms": latency_ms,
        "credits_charged": first.get("credits_charged"),
        "discord": {
            "posted": bool(discord_result),
            "message_id": discord_result.get("message_id") if discord_result else None,
            "attachment_id": discord_result.get("attachment_id") if discord_result else None,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate live audio sample MP3 artifacts.")
    parser.add_argument("--api-url", default=os.getenv("OPENMATES_API_URL", DEFAULT_API_URL))
    parser.add_argument("--plan-json", required=True, type=Path)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--cli", default=os.getenv("OPENMATES_CLI", DEFAULT_CLI))
    parser.add_argument("--skip-discord", action="store_true")
    args = parser.parse_args()

    if os.getenv("OPENMATES_LIVE_AUDIO_SAMPLES") != "1":
        print("Refusing to run live audio samples. Set OPENMATES_LIVE_AUDIO_SAMPLES=1 to opt in.", file=sys.stderr)
        return 2

    samples = _load_plan(args.plan_json)
    env = {**_load_env_file(CONTROL_PLANE_ROOT / ".env"), **os.environ}
    webhook_url = "" if args.skip_discord else env.get("DISCORD_WEBHOOK_DEV_SMOKE", "")
    run_id = f"elevenlabs-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}"
    output_dir = args.output_dir / datetime.now(UTC).strftime("%Y-%m-%d")
    api_key = ""
    key_id: str | None = None
    cli_env: dict[str, str] | None = None
    revoked = False
    approved_devices: list[str] = []

    try:
        api_key, key_id, cli_env = _create_temp_api_key(
            cli_path=args.cli,
            api_url=args.api_url,
            name=f"audio-samples-{run_id}",
        )
        device_id = _device_identity()
        artifacts: list[dict[str, Any]] = []
        for sample in samples:
            started = time.perf_counter()
            try:
                response = _post_skill(
                    api_url=args.api_url,
                    api_key=api_key,
                    device_id=device_id,
                    app_id=str(sample["app"]),
                    skill_id=str(sample["skill"]),
                    payload=sample["payload"],
                )
            except RuntimeError as exc:
                if not key_id or not _is_device_approval_error(exc):
                    raise
                approved_devices.extend(_approve_pending_key_devices(args.api_url, key_id, {"cli"}))
                response = _post_skill(
                    api_url=args.api_url,
                    api_key=api_key,
                    device_id=device_id,
                    app_id=str(sample["app"]),
                    skill_id=str(sample["skill"]),
                    payload=sample["payload"],
                )
            latency_ms = int((time.perf_counter() - started) * 1000)
            artifacts.append(
                _write_sample(
                    output_dir=output_dir,
                    sample=sample,
                    response=response,
                    latency_ms=latency_ms,
                    webhook_url=webhook_url,
                )
            )
    finally:
        if cli_env is not None:
            revoked = _revoke_temp_api_key(cli_path=args.cli, env=cli_env, key_id=key_id)

    manifest = {
        "run_id": run_id,
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "api_url": args.api_url,
        "endpoint_access_model": "developer_api_key_rest",
        "auth": {
            "temporary_api_key_created": True,
            "temporary_api_key_revoked": revoked,
            "approved_device_count": len(set(approved_devices)),
            "access_type": "cli",
        },
        "privacy": {
            "api_key_persisted": False,
            "webhook_url_persisted": False,
            "prompts_persisted": False,
            "audio_base64_persisted": False,
        },
        "plan_sha256": _plan_hash(args.plan_json),
        "artifacts": artifacts,
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"run_id": run_id, "manifest": str(manifest_path.relative_to(REPO_ROOT)), "artifacts": len(artifacts)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
