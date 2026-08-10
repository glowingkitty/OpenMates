#!/usr/bin/env python3
"""Workspace ask history guardrail tests.

Purpose: prevent mutating ask commands from bypassing workspace history.
Scope: static checks only, so the guard is fast enough for local/CI runs.
Spec: docs/specs/workspace-change-history/spec.yml.
Run: python3 -m pytest scripts/tests/test_workspace_ask_history_gate.py -q.
"""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CLI_SOURCE = ROOT / "frontend/packages/openmates-cli/src/cli.ts"
ROUTE_FILES = [
    ROOT / "backend/core/api/app/routes/user_tasks.py",
    ROOT / "backend/core/api/app/routes/user_plans.py",
    ROOT / "backend/core/api/app/routes/projects.py",
    ROOT / "backend/core/api/app/routes/workflows.py",
]


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _ts_ask_block(source: str, marker: str) -> str:
    start = source.index(marker)
    next_section = source.find("\n// ---------------------------------------------------------------------------", start + len(marker))
    if next_section == -1:
        next_section = len(source)
    return source[start:next_section]


def test_cli_task_plan_and_project_ask_return_history_commands() -> None:
    source = _source(CLI_SOURCE)
    task_block = _ts_ask_block(source, 'if (subcommand === "ask") {')
    plan_marker = 'const instruction = requiredAskInstruction(flags, rest, "openmates plans ask'
    plan_block = _ts_ask_block(source, plan_marker)
    project_marker = 'const instruction = requiredAskInstruction(flags, rest, "openmates projects ask'
    project_block = _ts_ask_block(source, project_marker)

    assert "await client.askUserTasks" in task_block
    assert "planUserTaskAsk" in task_block
    assert "encryptedCreates" in task_block
    assert "printAskApplyResult" in task_block
    assert "await client.askUserPlans" in plan_block
    assert "planUserPlanAsk" in plan_block
    assert "printAskApplyResult" in plan_block
    assert "await client.askProject" in project_block
    assert "planProjectAsk" in project_block
    assert "printAskApplyResult" in project_block


def test_cli_workflow_ask_uses_workspace_ask_endpoint() -> None:
    source = _source(CLI_SOURCE)
    workflow_block = _ts_ask_block(source, 'const instruction = requiredAskInstruction(flags, rest, "openmates workflows ask')

    assert "await client.askWorkflow" in workflow_block
    assert "create: explicitCreate" in workflow_block
    assert "workflowAskGraphFromFlags" in workflow_block
    assert "printAskApplyResult" in workflow_block


def test_backend_ask_routes_must_import_and_use_history_service() -> None:
    for route_file in ROUTE_FILES:
        source = _source(route_file)
        if not re.search(r'@router\.post\("/ask"\)', source):
            continue

        assert "WorkspaceChangeHistoryService" in source, f"{route_file} defines /ask without workspace history service"
        assert "build_history_commands" in source, f"{route_file} defines /ask without undo command output"
        assert "record_change_set" in source or "_record_" in source, f"{route_file} defines /ask without a history write"
        assert "WorkspaceAskPlanningError" in source or route_file.name == "user_tasks.py", f"{route_file} defines /ask without inference planner errors"
