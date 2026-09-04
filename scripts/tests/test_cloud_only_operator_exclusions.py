"""Cloud-only operator exclusion checks.

These tests protect the open-source/self-hosted edition from accidentally
shipping private official-cloud setup helpers. The helper names here are for
operator machines only; the runtime code uses Vault-imported secrets instead.
They intentionally verify repository packaging metadata, not secret values.
"""

# contract-test-file: tooling

from __future__ import annotations

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CLOUD_ONLY_OPERATOR_FILES = ("scripts/revolut_business_setup.py",)
PUBLIC_OPERATOR_DOCS = (
    "frontend/packages/openmates-cli/README.md",
    "docs/user-guide/cli/server-management.md",
)
PRIVATE_OPERATOR_TERMS = (
    "--official-cloud",
    "--deployment-mode",
    "--openmatescloud-path",
    "OPENMATES_DEPLOYMENT_MODE",
    "OpenMatesCloud",
    "official_cloud",
    "official-cloud billing-readiness",
)


def doc_assert(_claim_id: str) -> None:
    """Mark documentation claims that this test module verifies."""


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


def test_public_cli_docs_exclude_private_operator_details() -> None:
    doc_assert("public-cli-docs-exclude-private-cloud-operations")
    for relative_path in PUBLIC_OPERATOR_DOCS:
        content = (ROOT / relative_path).read_text(encoding="utf-8")
        for term in PRIVATE_OPERATOR_TERMS:
            assert term not in content, f"{relative_path} exposes private operator term: {term}"
