#!/usr/bin/env python3
"""
Regression test for the architecture behavioral-claims audit script.

This filename intentionally mirrors scripts/docs_architecture_behavioral_claims.py
so session coverage checks can associate the script with a focused test. Detailed
claim-level coverage remains in test_architecture_behavioral_claims.py.

Architecture: docs/specs/architecture-docs-claim-coverage/spec.yml
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_docs_architecture_behavioral_claims_cli_reports_verified_claims() -> None:
    result = subprocess.run(
        ["python3", "scripts/docs_architecture_behavioral_claims.py", "--json"],
        cwd=REPO_ROOT,
        capture_output=True,
        check=True,
        text=True,
    )
    payload = json.loads(result.stdout)

    assert payload["totals"]["behavioral_claims"] >= 1
    assert payload["totals"]["verified_behavioral_claims"] >= 1
    assert not any(payload["failures"].values())
