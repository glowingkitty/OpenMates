#!/usr/bin/env python3
"""Audit object-storage outage isolation and fail-before-cost coverage.

The audit prevents API lifespan and shared task initialization from regaining a
mandatory S3 dependency. It also keeps durable generated-output tasks bound to
the shared storage availability guard before provider execution.
"""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STORAGE_GUARD = "require_storage_available"
MEDIA_TASKS = (
    ("backend/apps/images/tasks/generate_task.py", "_async_generate_image", "ensure_credit_headroom("),
    ("backend/apps/models3d/tasks/generate_task.py", "_async_generate_model", "ensure_credit_headroom("),
    ("backend/apps/music/tasks/generate_task.py", "_async_generate_music", "ensure_credit_headroom("),
    ("backend/apps/audio/tasks/generate_task.py", "_async_generate_audio", "ensure_audio_credit_headroom("),
    ("backend/apps/audio/tasks/speak_task.py", "_async_speak_audio", "classify_audio_speech_safety("),
    ("backend/apps/videos/tasks/generate_task.py", "_async_generate_video", "ensure_credit_headroom("),
    ("backend/apps/videos/tasks/render_remotion_task.py", "_async_render_remotion", "render_remotion_in_e2b("),
)
PRESERVATION_TASKS = (
    "backend/core/api/app/tasks/usage_archive_tasks.py",
    "backend/core/api/app/tasks/auto_delete_tasks.py",
    "backend/core/api/app/tasks/storage_billing_tasks.py",
)
PRESERVATION_SERVICES = (
    "backend/core/api/app/services/usage_archive_service.py",
    "backend/core/api/app/services/directus/embed_methods.py",
)


def _async_function_source(path: Path, function_name: str) -> str:
    source = path.read_text()
    tree = ast.parse(source, filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == function_name:
            return ast.get_source_segment(source, node) or ""
    raise AssertionError(f"Missing async function {function_name} in {path.relative_to(ROOT)}")


def audit() -> list[str]:
    failures: list[str] = []
    api_source = (ROOT / "backend/core/api/main.py").read_text()
    if "await app.state.s3_service.initialize()" in api_source:
        failures.append("API lifespan synchronously requires remote S3 initialization")

    s3_source = (ROOT / "backend/core/api/app/services/s3/service.py").read_text()
    reconciliation_source = s3_source[
        s3_source.index("async def _initialize_buckets("):s3_source.index("def get_s3_url(")
    ]
    if 'raise RuntimeError("object_storage_reconciliation_failed")' not in reconciliation_source:
        failures.append("S3 bucket reconciliation failures do not reach the background retry loop")

    cli_server_source = (ROOT / "frontend/packages/openmates-cli/src/server.ts").read_text()
    if "output.checks.filter((check) => check.required)" in cli_server_source:
        failures.append("CLI incident processing discards optional storage checks")
    if "applied.events[0]" in cli_server_source:
        failures.append("CLI incident delivery discards simultaneous storage transitions")

    for relative_path, function_name, first_cost_marker in MEDIA_TASKS:
        source = _async_function_source(ROOT / relative_path, function_name)
        guard_position = source.find(f"await {STORAGE_GUARD}(")
        cost_position = source.find(first_cost_marker)
        if guard_position < 0:
            failures.append(f"{relative_path} does not use {STORAGE_GUARD}")
        elif cost_position < 0 or guard_position > cost_position:
            failures.append(f"{relative_path} does not guard storage before provider or credit work")
        if "initialize_core_services" not in source or "initialize_task_storage" not in source:
            failures.append(f"{relative_path} does not isolate core task services from storage")

    for relative_path in PRESERVATION_TASKS:
        source = (ROOT / relative_path).read_text()
        if STORAGE_GUARD not in source:
            failures.append(f"{relative_path} does not preserve state behind {STORAGE_GUARD}")

    for relative_path in PRESERVATION_SERVICES:
        source = (ROOT / relative_path).read_text()
        if "storage_unavailable" not in source:
            failures.append(f"{relative_path} does not propagate storage outage state")

    return failures


def main() -> int:
    failures = audit()
    if failures:
        print("S3 outage resilience audit failed:")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print("S3 outage resilience audit passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
