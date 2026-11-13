# backend/apps/code/skills/dependency_install.py
"""Install a Node project's dependencies before an E2B test run.

The assistant writes the test run itself and often starts the dev server
(`npm run dev`) without an install step, so the server fails on a missing
package (`@vitejs/plugin-react`) and every run of the turn ends with "Server did
not become ready". When the server or test command runs in a folder with a
package.json and no setup command installs packages, the run gets one
`npm install` there first. Spec: feature.projects (agentic coding test runs).
"""
from __future__ import annotations

import re
from typing import Iterable

from backend.shared.python_schemas.code_test_run import MAX_COMMANDS, TestCommand, TestRunSpec

_INSTALL = re.compile(r"(^|[\s;&|(])(npm|pnpm|yarn|bun)(\s+(i|install|ci|add)\b|\s*($|[;&|)]))")
INSTALL_TIMEOUT_SECONDS = 300


def _folder(cwd: str) -> str:
    folder = cwd.strip().strip("/")
    return "" if folder in ("", ".") else folder.removeprefix("./")


def installs_packages(command: TestCommand) -> bool:
    """True when the command runs a package install (`npm ci`, `pnpm i`, bare `yarn`, ...)."""
    return bool(_INSTALL.search(" ".join(command.argv)))


def with_dependency_install(spec: TestRunSpec, file_paths: Iterable[str]) -> TestRunSpec:
    """Return ``spec`` with an ``npm install`` setup step when one is missing.

    Only the folder the server (or, without a server, the test command) runs in
    is considered; the step is added in front of the existing setup commands.
    A spec that already installs packages, has no package.json in that folder,
    or has no room for another command is returned unchanged.
    """
    command = spec.server.command if spec.server is not None else spec.test_command
    folder = _folder(command.cwd)
    manifest = f"{folder}/package.json" if folder else "package.json"
    if manifest not in set(file_paths) or any(installs_packages(step) for step in spec.setup_commands):
        return spec
    if len(spec.setup_commands) >= MAX_COMMANDS:
        return spec
    install = TestCommand(
        argv=["npm", "install", "--no-audit", "--no-fund"],
        cwd=folder or ".", timeout_seconds=INSTALL_TIMEOUT_SECONDS,
    )
    return spec.model_copy(update={"setup_commands": [install, *spec.setup_commands]})
