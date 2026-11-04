"""Run the node:test suite for the app/focus-mode translation-key deploy gate.

The checker lives in frontend/packages/ui/scripts/validate-app-translation-keys.js and runs as
Step 8 of validate-locales.js (deploy translation gate). This wrapper keeps its fixture tests in
the scripts pytest suite.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
UI = ROOT / "frontend/packages/ui"


# contract-test: tooling
@pytest.mark.skipif(shutil.which("node") is None or not (UI / "node_modules/yaml").exists(), reason="node and ui deps required")
def test_app_translation_key_checker_fixtures():
    result = subprocess.run(
        ["node", "--test", "scripts/validate-app-translation-keys.test.mjs"],
        cwd=UI,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-2000:]
