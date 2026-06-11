#!/usr/bin/env python3
"""
Regression test for the static documentation-claims validator.

This filename intentionally mirrors scripts/docs_static_claims.py so session
coverage checks can associate the script with a focused test. Detailed anchor
validation behavior remains in test_architecture_static_claims.py.

Architecture: docs/specs/architecture-docs-claim-coverage/spec.yml
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_docs_static_claims_cli_validates_architecture_anchors() -> None:
    result = subprocess.run(
        ["python3", "scripts/docs_static_claims.py", "--json"],
        cwd=REPO_ROOT,
        capture_output=True,
        check=True,
        text=True,
    )
    payload = json.loads(result.stdout)

    assert payload["checked_claims"] >= 1
    assert payload["checked_anchors"] >= 1
    assert payload["errors"] == []
