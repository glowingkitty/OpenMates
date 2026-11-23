"""Multi-path `project_read_text`: one sandbox read per path, one merged tool result.

The device/remote executors (Rust core) take exactly one path per job and only one
Project operation may be pending per turn, so several files are fanned out here
for the hosted sandbox, which runs inline. A device source gets a clear rejection
telling the model to read one file per call; nothing is silently truncated.
"""

from __future__ import annotations

from typing import Any, Optional

from backend.apps.ai.processing.project_sandbox_executor import run_project_tool_in_sandbox

MAX_READ_PATHS = 10


def normalize_read_paths(arguments: dict[str, Any]) -> list[str]:
    """Return the ordered, de-duplicated paths of a read call (`path` and/or `paths`)."""
    raw: list[Any] = []
    if isinstance(arguments.get("paths"), list):
        raw.extend(arguments["paths"])
    if arguments.get("path") is not None:
        raw.insert(0, arguments["path"])
    seen: list[str] = []
    for value in raw:
        if isinstance(value, str) and value and value not in seen:
            seen.append(value)
    return seen


async def run_read_text_in_sandbox(
    *, operation: str, operation_arguments: dict[str, Any], **kwargs: Any,
) -> Optional[dict[str, Any]]:
    """Run `run_project_tool_in_sandbox`; fan a multi-path read out into one merged result."""
    if operation != "read_text" or "paths" not in operation_arguments:
        return await run_project_tool_in_sandbox(
            operation=operation, operation_arguments=operation_arguments, **kwargs)
    paths = normalize_read_paths(operation_arguments)
    if not paths:
        return {"status": "rejected", "reason": "Give at least one Project-relative path."}
    if len(paths) > MAX_READ_PATHS:
        return {"status": "rejected",
                "reason": f"Read at most {MAX_READ_PATHS} files per call; split the request."}
    if len(paths) == 1:
        single = {k: v for k, v in operation_arguments.items() if k != "paths"}
        return await run_project_tool_in_sandbox(
            operation=operation, operation_arguments={**single, "path": paths[0]}, **kwargs)
    files: list[dict[str, Any]] = []
    for path in paths:
        single = {k: v for k, v in operation_arguments.items() if k not in {"paths", "path"}}
        result = await run_project_tool_in_sandbox(
            operation=operation, operation_arguments={**single, "path": path}, **kwargs)
        if result is None:
            return {"status": "rejected",
                    "reason": "Several files per call are only supported for the hosted Project "
                              "workspace. Read one file per call for this source."}
        files.append({**result, "path": path})
    failed = [row for row in files if row.get("status") != "completed"]
    return {"status": "completed" if not failed else "partial", "operation": operation,
            "operation_id": files[0].get("operation_id"), "files": files}
