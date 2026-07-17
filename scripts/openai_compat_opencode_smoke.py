#!/usr/bin/env python3
"""OpenCode canary for OpenMates' OpenAI-compatible provider surface.

The script discovers a model from `/v1/models`, writes a temporary OpenCode
project config that uses `@ai-sdk/openai-compatible`, and runs `opencode run`
with `openmates/<model>`. It requires `OPENMATES_TEST_ACCOUNT_API_KEY` and an
installed `opencode` CLI.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import argparse
from pathlib import Path

import httpx


DEFAULT_BASE_URL = "https://api.dev.openmates.org/v1"
DEFAULT_ORIGIN = "https://app.dev.openmates.org"


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise SystemExit(f"Missing required environment variable: {name}")
    return value


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run an OpenCode canary against OpenMates' OpenAI-compatible API.")
    parser.add_argument("--base-url", default=os.getenv("OPENMATES_OPENAI_COMPAT_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument("--origin", default=os.getenv("OPENMATES_OPENAI_COMPAT_ORIGIN", DEFAULT_ORIGIN))
    parser.add_argument("--model", default=os.getenv("OPENMATES_OPENAI_COMPAT_MODEL"))
    return parser.parse_args()


def _pick_model(api_key: str, base_url: str, origin: str, configured_model: str | None) -> str:
    if configured_model:
        return configured_model
    response = httpx.get(
        f"{base_url.rstrip('/')}/models",
        headers={"Authorization": f"Bearer {api_key}", "Origin": origin},
        timeout=30,
    )
    response.raise_for_status()
    models = response.json().get("data") or []
    if not models:
        raise SystemExit("/v1/models returned no models")
    return models[0]["id"]


def main() -> int:
    args = _parse_args()
    api_key = _require_env("OPENMATES_TEST_ACCOUNT_API_KEY")
    base_url = args.base_url
    origin = args.origin
    model = _pick_model(api_key, base_url, origin, args.model)
    opencode = shutil.which("opencode")
    if not opencode:
        raise SystemExit("Missing opencode CLI on PATH")

    with tempfile.TemporaryDirectory(prefix="openmates-opencode-") as temp_dir:
        project_dir = Path(temp_dir)
        (project_dir / "opencode.json").write_text(
            json.dumps(
                {
                    "$schema": "https://opencode.ai/config.json",
                    "provider": {
                        "openmates": {
                            "npm": "@ai-sdk/openai-compatible",
                            "name": "OpenMates",
                            "options": {
                                "baseURL": base_url,
                                "apiKey": api_key,
                                "headers": {"Origin": origin},
                            },
                            "models": {model: {"name": model}},
                        }
                    },
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        command = [
            opencode,
            "run",
            "--pure",
            "--format",
            "json",
            "--model",
            f"openmates/{model}",
            "Reply with exactly: OK",
        ]
        print(f"[openai-compat-opencode] model=openmates/{model}")
        result = subprocess.run(
            command,
            cwd=project_dir,
            text=True,
            capture_output=True,
            timeout=180,
            check=False,
        )
        if result.returncode != 0:
            print(result.stdout)
            print(result.stderr, file=sys.stderr)
            raise SystemExit(result.returncode)
        output = f"{result.stdout}\n{result.stderr}"
        if "OK" not in output:
            print(output)
            raise SystemExit("OpenCode canary completed without expected OK response")
        print("[openai-compat-opencode] OpenCode canary passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
