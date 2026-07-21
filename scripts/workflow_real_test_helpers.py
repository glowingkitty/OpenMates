#!/usr/bin/env python3
"""Shared helpers for real Workflow CLI verification scripts.

These helpers intentionally shell out to the built OpenMates CLI and never mock
OpenMates API calls. They require a paired CLI session in HOME or an explicit
OPENMATES_CLI_HOME, matching the Workflow CLI's current cookie-auth contract.
They are kept small so real-dev scripts remain deterministic and auditable.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CLI_PATH = REPO_ROOT / "frontend" / "packages" / "openmates-cli" / "dist" / "cli.js"


def resolve_cli_path(cli_path: str | None = None) -> Path:
    resolved = Path(cli_path or os.getenv("OPENMATES_CLI_PATH") or DEFAULT_CLI_PATH)
    if not resolved.exists():
        raise RuntimeError(
            f"OpenMates CLI not found at {resolved}. Build it with `npm run build` in "
            "frontend/packages/openmates-cli or set OPENMATES_CLI_PATH."
        )
    return resolved


def cli_env(api_url: str, home: str | None = None) -> dict[str, str]:
    env = dict(os.environ)
    env["OPENMATES_API_URL"] = api_url.rstrip("/")
    home_dir = home or os.getenv("OPENMATES_CLI_HOME")
    if home_dir:
        env["HOME"] = home_dir
    return env


def run_cli_json(
    cli_path: Path,
    api_url: str,
    args: list[str],
    *,
    home: str | None = None,
    timeout_seconds: int = 120,
) -> Any:
    result = subprocess.run(
        ["node", str(cli_path), *args, "--api-url", api_url.rstrip("/"), "--json"],
        env=cli_env(api_url, home),
        text=True,
        capture_output=True,
        timeout=timeout_seconds,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"CLI command failed: openmates {' '.join(args)}\n"
            f"exit={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
        )
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"CLI command returned non-JSON stdout: {result.stdout}\nstderr={result.stderr}") from exc


def run_cli(
    cli_path: Path,
    api_url: str,
    args: list[str],
    *,
    home: str | None = None,
    timeout_seconds: int = 120,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["node", str(cli_path), *args, "--api-url", api_url.rstrip("/")],
        env=cli_env(api_url, home),
        text=True,
        capture_output=True,
        timeout=timeout_seconds,
        check=False,
    )


def yaml_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(str(value))


def dump_yaml_value(value: Any, indent: int = 0) -> str:
    prefix = " " * indent
    if isinstance(value, dict):
        lines: list[str] = []
        for key, item in value.items():
            if isinstance(item, (dict, list)):
                lines.append(f"{prefix}{key}:")
                lines.append(dump_yaml_value(item, indent + 2))
            else:
                lines.append(f"{prefix}{key}: {yaml_scalar(item)}")
        return "\n".join(lines)
    if isinstance(value, list):
        lines = []
        for item in value:
            if isinstance(item, dict):
                lines.append(f"{prefix}-")
                lines.append(dump_yaml_value(item, indent + 2))
            elif isinstance(item, list):
                lines.append(f"{prefix}-")
                lines.append(dump_yaml_value(item, indent + 2))
            else:
                lines.append(f"{prefix}- {yaml_scalar(item)}")
        return "\n".join(lines)
    return f"{prefix}{yaml_scalar(value)}"


def step_id_for(capability_id: str, index: int = 0) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9_]+", "_", capability_id.replace(".", "_"))
    normalized = normalized.strip("_").lower() or "step"
    return normalized if index == 0 else f"{normalized}_{index}"
