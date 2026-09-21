"""Validate exact pytest targets shared by the CI CLI, queue, and runner.

The validator keeps focused requests from expanding into broad test discovery
and rejects pytest options or paths that could escape the approved test roots.
For example, the dispatcher accepts
``--test-target backend/tests/test_chat.py::test_message_order`` and passes that
same node ID through ``CI_SPECS_JSON`` to the isolated runner.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath


PYTEST_ROOTS = ("backend/tests/", "packages/openmates-python/tests/")


def validate_pytest_targets(
    targets: object, *, root: Path | None = None
) -> list[str]:
    """Return exact safe pytest file/node IDs without broadening selection."""
    if not isinstance(targets, list):
        raise ValueError("pytest targets must be a JSON array")
    normalized: list[str] = []
    for target in targets:
        if not isinstance(target, str) or not target:
            raise ValueError("pytest targets must be non-empty strings")
        if target.startswith("-"):
            raise ValueError(f"pytest options are not test targets: {target}")
        if "\\" in target or any(character in target for character in "\r\n\0"):
            raise ValueError(f"unsafe pytest target: {target!r}")
        file_name, separator, node_id = target.partition("::")
        path = PurePosixPath(file_name)
        if path.is_absolute() or ".." in path.parts or "." in path.parts:
            raise ValueError(f"pytest target must be repository-relative: {target}")
        if not file_name.endswith(".py") or not file_name.startswith(PYTEST_ROOTS):
            raise ValueError(
                "pytest target must be a Python test below backend/tests/ or "
                f"packages/openmates-python/tests/: {target}"
            )
        if separator and not node_id:
            raise ValueError(f"pytest node ID is empty: {target}")
        if root is not None and not (Path(root) / file_name).is_file():
            raise ValueError(f"unknown pytest test file: {file_name}")
        normalized.append(target)
    if len(normalized) != len(set(normalized)):
        raise ValueError("pytest targets must not contain duplicates")
    return normalized
