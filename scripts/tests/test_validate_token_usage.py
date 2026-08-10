"""
Regression tests for the UI design-token usage validator.

These tests keep dark-mode failures from hiding behind CSS var fallbacks.
The original interactive-question bug used an undefined token with a white
fallback, which passed static CSS parsing but broke computed dark-mode
contrast in the browser.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
VALIDATOR = REPO_ROOT / "frontend/packages/ui/scripts/validate-token-usage.js"


def run_validator(file_path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["node", str(VALIDATOR), "--file", str(file_path)],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_validator_rejects_undefined_design_token_with_fallback(tmp_path: Path) -> None:
    component = tmp_path / "UndefinedToken.svelte"
    component.write_text(
        """
<div class="selected">Choice</div>

<style>
  .selected {
    background: var(--color-grey-5, #ffffff);
    color: var(--color-font-primary, #212529);
  }
</style>
""".strip(),
        encoding="utf-8",
    )

    result = run_validator(component)

    assert result.returncode == 1
    assert "Undefined grey color token --color-grey-5" in result.stdout
    assert "undefined-token" not in result.stderr


def test_validator_accepts_defined_design_tokens(tmp_path: Path) -> None:
    component = tmp_path / "DefinedToken.svelte"
    component.write_text(
        """
<div class="selected">Choice</div>

<style>
  .selected {
    background: var(--color-grey-0, #ffffff);
    color: var(--color-font-primary, #212529);
  }
</style>
""".strip(),
        encoding="utf-8",
    )

    result = run_validator(component)

    assert result.returncode == 0
    assert "Undefined grey color token" not in result.stdout
