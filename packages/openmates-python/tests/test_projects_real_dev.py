"""Real dev-server pip SDK Project verification.

Runs the shared temporary-key harness for Personal and Team encrypted CRUD.
The harness owns credential creation, device approval, cleanup, and revocation,
and never emits API keys, ciphertext, or Project cleartext.
"""

# contract-test-file: tooling

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]


def has_test_account_credentials() -> bool:
    if os.getenv("OPENMATES_TEST_ACCOUNT_EMAIL") and os.getenv("OPENMATES_TEST_ACCOUNT_PASSWORD"):
        return True
    return any(
        os.getenv(f"OPENMATES_TEST_ACCOUNT_{slot}_EMAIL") and os.getenv(f"OPENMATES_TEST_ACCOUNT_{slot}_PASSWORD")
        for slot in range(1, 21)
    )


@pytest.mark.skipif(
    not has_test_account_credentials(),
    reason="Set OPENMATES_TEST_ACCOUNT_* credentials to run real dev SDK Project tests",
)
def test_pip_sdk_personal_and_team_projects_real_dev() -> None:
    subprocess.run(
        [
            "node",
            "--experimental-strip-types",
            "--loader",
            "./frontend/packages/openmates-cli/tests/loader.mjs",
            "scripts/verify_sdk_projects_live_smoke.mjs",
            "--pip",
        ],
        cwd=ROOT,
        env=os.environ.copy(),
        check=True,
        timeout=180,
    )
