"""Real dev-server pip SDK Project verification.

Runs the shared temporary-key harness for Personal and Team encrypted CRUD.
The harness owns credential creation, device approval, cleanup, and revocation,
and never emits API keys, ciphertext, or Project cleartext.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def test_pip_sdk_personal_and_team_projects_real_dev():
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
