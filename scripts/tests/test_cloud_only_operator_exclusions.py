"""Cloud-only operator exclusion checks.

These tests protect the open-source/self-hosted edition from accidentally
shipping private official-cloud setup helpers. The helper names here are for
operator machines only; the runtime code uses Vault-imported secrets instead.
They intentionally verify repository packaging metadata, not secret values.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CLOUD_ONLY_OPERATOR_FILES = ("scripts/revolut_business_setup.py",)


def test_cloud_only_operator_helpers_are_gitignored_and_dockerignored() -> None:
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")

    for relative_path in CLOUD_ONLY_OPERATOR_FILES:
        assert relative_path in gitignore
        assert relative_path in dockerignore


def test_cloud_only_operator_helpers_are_not_tracked() -> None:
    result = subprocess.run(
        ["git", "ls-files", "--", *CLOUD_ONLY_OPERATOR_FILES],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == ""
