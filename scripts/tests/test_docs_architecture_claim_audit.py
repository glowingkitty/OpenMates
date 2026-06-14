#!/usr/bin/env python3
"""
Regression test for the architecture claim-audit script.

This filename intentionally mirrors scripts/docs_architecture_claim_audit.py so
session coverage checks can associate the script with a focused test. Detailed
audit behavior remains in test_architecture_docs_claim_audit.py.

Architecture: docs/specs/architecture-docs-claim-coverage/spec.yml
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_docs_architecture_claim_audit_cli_reports_complete_coverage() -> None:
    result = subprocess.run(
        ["python3", "scripts/docs_architecture_claim_audit.py", "--json"],
        cwd=REPO_ROOT,
        capture_output=True,
        check=True,
        text=True,
    )
    payload = json.loads(result.stdout)

    assert payload["totals"]["active_architecture_docs"] >= 1
    assert payload["totals"]["active_architecture_docs_with_claims"] == payload["totals"]["active_architecture_docs"]
    assert not any(payload["failures"].values())
