# backend/apps/code/test_run_target.py
# contract-test-file: infrastructure
#
# Default-target selection for Code Run test runs. Pure helpers plus one async
# lookup, kept out of run_code_skill.py. Contract:
# docs/plans/agentic-tests-and-git-sync/contracts/test-run.md

from __future__ import annotations

from typing import Any

from backend.shared.python_schemas.code_test_run import TestRunSpec, TestTarget, select_test_target


def pick_remote_run_source(sources: list[dict[str, Any]]) -> str | None:
    """Return the first connected source that grants run_command, else None."""
    for source in sources:
        if source.get("status") in {"revoked", "offline"}:
            continue
        if "run_command" in set(source.get("capabilities") or []):
            source_id = source.get("source_id")
            if isinstance(source_id, str) and source_id:
                return source_id
    return None


async def resolve_test_run_target(
    spec: TestRunSpec,
    *,
    directus_service: Any,
    focus: dict[str, Any] | None,
    user_id: str,
) -> tuple[TestTarget, str | None, str | None]:
    """Resolve (target, project_id, source_id) for a test run.

    An explicit spec.target wins. Otherwise a remote_source default applies only
    when the active Project focus has a connected source with run_command.
    """
    project_id = spec.project_id
    source_id = spec.source_id
    if focus and isinstance(focus.get("project_id"), str):
        project_id = project_id or focus["project_id"]
    if spec.target is None and source_id is None and focus and project_id == focus.get("project_id"):
        team_id = focus.get("team_id") if isinstance(focus.get("team_id"), str) else None
        sources = await directus_service.project.list_sources(project_id, user_id, team_id=team_id)
        source_id = pick_remote_run_source(sources)
    target = select_test_target(spec.target, focus_has_remote_run_source=source_id is not None)
    return target, project_id, source_id if target == "remote_source" else None
