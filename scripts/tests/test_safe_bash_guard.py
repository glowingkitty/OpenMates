#!/usr/bin/env python3
"""Contracts for the shared shell safety guard.

The guard must keep all Docker Compose lifecycle mutations behind the
registered OpenMates server CLI while leaving read-only inspection available.
Run: python3 -m pytest scripts/tests/test_safe_bash_guard.py.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


# contract-test-file: tooling


PROJECT_ROOT = Path(__file__).resolve().parents[2]
GUARD = PROJECT_ROOT / "scripts" / "safe_bash_guard.py"


def run_guard(command: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["python3", str(GUARD), command],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


def test_blocks_direct_docker_compose_lifecycle_mutations() -> None:
    commands = [
        "docker compose restart api",
        "docker compose --env-file .env -f backend/core/docker-compose.yml build api",
        "docker-compose up -d",
        "env OPENMATES_TEST=1 docker compose down",
        "timeout 30 docker compose stop worker",
    ]
    for command in commands:
        result = run_guard(command)
        assert result.returncode == 2, command
        payload = json.loads(result.stderr)
        assert payload["decision"] == "block"
        assert "openmates server" in payload["reason"]


def test_allows_compose_inspection_and_openmates_lifecycle_commands() -> None:
    for command in [
        "docker compose ps",
        "docker compose logs api",
        "docker compose config",
        "docker compose run --rm api python --version",
        "openmates server restart --rebuild --services api",
    ]:
        result = run_guard(command)
        assert result.returncode == 0, command
        assert result.stderr == ""
