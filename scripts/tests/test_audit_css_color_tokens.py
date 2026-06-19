#!/usr/bin/env python3
"""Tests for the CSS text-color token audit.

Fixtures are synthetic and focused on the contract: gradient tokens may be used
for backgrounds, but never as foreground text colors.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "audit_css_color_tokens.py"
SPEC = importlib.util.spec_from_file_location("audit_css_color_tokens", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
audit_css_color_tokens = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = audit_css_color_tokens
SPEC.loader.exec_module(audit_css_color_tokens)

audit_text_color_tokens = audit_css_color_tokens.audit_text_color_tokens


def test_flags_primary_gradient_used_as_text_color(tmp_path: Path) -> None:
    component = tmp_path / "Component.svelte"
    component.write_text(
        """
<style>
    .share-url {
        color: var(--color-primary);
    }
</style>
""".strip(),
        encoding="utf-8",
    )

    issues = audit_text_color_tokens([component])

    assert len(issues) == 1
    assert issues[0].line_number == 3
    assert "color: var(--color-primary)" in issues[0].line


def test_allows_concrete_primary_color_and_background_gradient(tmp_path: Path) -> None:
    component = tmp_path / "Component.svelte"
    component.write_text(
        """
<style>
    .share-url {
        color: var(--color-primary-start);
    }

    .share-icon {
        background: var(--color-primary);
        background-color: var(--color-primary);
    }
</style>
""".strip(),
        encoding="utf-8",
    )

    assert audit_text_color_tokens([component]) == []
