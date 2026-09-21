#!/usr/bin/env python3
# contract-test-file: tooling
"""Contracts for the shared shell safety guard.

The guard must keep all Docker Compose lifecycle mutations behind the
registered OpenMates server CLI while leaving read-only inspection available.
Run: python3 -m pytest scripts/tests/test_safe_bash_guard.py.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
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


def load_guard():
    spec = importlib.util.spec_from_file_location("openmates_safe_bash_guard", GUARD)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


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


def test_blocks_local_branch_creation_and_mutation() -> None:
    for command in [
        "git branch feature",
        "git branch -D feature",
        "git switch -c feature",
        "git checkout -b feature",
        "git update-ref refs/heads/feature HEAD",
    ]:
        result = run_guard(command)
        assert result.returncode == 2, command
        assert "branch" in json.loads(result.stderr)["reason"].lower()


def test_allows_branch_inventory_and_detached_checkout() -> None:
    for command in ["git branch --show-current", "git branch --list", "git switch --detach HEAD"]:
        result = run_guard(command)
        assert result.returncode == 0, command


def test_blocks_destructive_git_cleanup() -> None:
    for command in ["git reset --hard HEAD", "git clean -fd", "git clean --force -d"]:
        result = run_guard(command)
        assert result.returncode == 2, command
        assert "destroy" in json.loads(result.stderr)["reason"].lower()


def test_allows_scoped_static_frontend_checks() -> None:
    commands = [
        "pnpm --dir frontend/apps/web_app lint",
        "pnpm --dir frontend/apps/web_app check",
        "pnpm --dir frontend/apps/web_app check-types",
        "pnpm --dir frontend/packages/ui test:run",
        "pnpm --dir frontend/packages/openmates-cli build",
        "pnpm exec tsc --noEmit",
        "pnpm exec tsc --watch=false --noEmit",
        "npx eslint frontend/packages/ui/src",
        "npx vitest run frontend/packages/ui/src/example.test.ts",
        "npx vitest run --watch false frontend/packages/ui/src/example.test.ts",
    ]
    for command in commands:
        result = run_guard(command)
        assert result.returncode == 0, (command, result.stderr)


def test_blocks_dev_browser_product_and_watching_commands() -> None:
    commands = [
        "pnpm --dir frontend/apps/web_app dev",
        "pnpm --dir frontend/apps/web_app preview",
        "pnpm --dir frontend/apps/web_app test:integration",
        "pnpm --dir frontend/apps/web_app test",
        "pnpm --dir frontend/packages/openmates-cli test:real-sdk-projects",
        "npx playwright test frontend/apps/web_app/tests/example.spec.ts",
        "npx vitest --watch",
        "pnpm dlx eslint .",
        "pnpm exec /tmp/tsc --noEmit",
        "npx ./untrusted/eslint .",
    ]
    for command in commands:
        result = run_guard(command)
        assert result.returncode == 2, command
        assert json.loads(result.stderr)["decision"] == "block"


def test_inspects_script_body_instead_of_trusting_safe_sounding_name(
    tmp_path: Path, monkeypatch,
) -> None:
    guard = load_guard()
    package = tmp_path / "package.json"
    package.write_text(
        json.dumps({"scripts": {"lint": "vite dev", "check": "eslint .", "loop": "pnpm loop"}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(guard, "REPO_ROOT", tmp_path)

    assert guard.check_package_script(tmp_path, "check") is None
    assert "unapproved command" in guard.check_package_script(tmp_path, "lint")
    assert "recursive package script" in guard.check_package_script(tmp_path, "loop")


def test_chained_commands_are_all_checked_but_quoted_data_is_not_executed() -> None:
    blocked = run_guard("pnpm --dir frontend/apps/web_app lint && pnpm --dir frontend/apps/web_app dev")
    assert blocked.returncode == 2
    substituted = run_guard("echo $(pnpm --dir frontend/apps/web_app dev)")
    assert substituted.returncode == 2
    multiline = run_guard("pnpm --dir frontend/apps/web_app lint\npnpm --dir frontend/apps/web_app dev")
    assert multiline.returncode == 2
    shell_wrapped = run_guard("sh -c 'git reset --hard HEAD'")
    assert shell_wrapped.returncode == 2
    grouped = run_guard("(pnpm --dir frontend/apps/web_app dev)")
    assert grouped.returncode == 2
    unknown_nested_shell = run_guard("bash scripts/example.sh")
    assert unknown_nested_shell.returncode == 2

    quoted = run_guard("python3 -c 'print(\"pnpm dev && npx playwright test\")'")
    assert quoted.returncode == 0
    quoted_substitution = run_guard("echo '$(pnpm --dir frontend/apps/web_app dev)'")
    assert quoted_substitution.returncode == 0
    quoted_shell = run_guard("printf '%s' \"sh -c 'git reset --hard HEAD'\"")
    assert quoted_shell.returncode == 0
