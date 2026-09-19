"""Prevent retired local tooling and generated clutter from returning."""

# contract-test-file: infrastructure

from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[2]
FORBIDDEN_ROOTS = (
    ".opencode/",
    ".planning/",
    ".vscode/",
    "marketing/",
    "test-results/",
    "vscode_extension/",
)


def test_retired_repository_roots_are_not_committed() -> None:
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    present_tracked_paths = [
        path
        for path in result.stdout.splitlines()
        if (ROOT / path).exists()
    ]
    clutter = [
        path
        for path in present_tracked_paths
        if path.startswith(FORBIDDEN_ROOTS)
    ]

    assert clutter == [], f"retired repository clutter is tracked: {clutter}"
