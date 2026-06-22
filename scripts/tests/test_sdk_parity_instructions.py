"""Tests for SDK parity audit guardrails.

Purpose: prove CLI-to-SDK parity drift is caught deterministically.
Architecture: import the audit module and mutate in-memory classifications only.
Security: destructive SDK confirmations are covered by package SDK tests.
Tests: python3 -m pytest scripts/tests/test_sdk_parity_instructions.py.
Spec: docs/specs/sdk-cli-parity-v1/spec.yml.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
AUDIT_PATH = ROOT / "scripts/audit_sdk_cli_parity.py"


def load_audit_module():
    spec = importlib.util.spec_from_file_location("audit_sdk_cli_parity", AUDIT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_sdk_parity_audit_passes_current_surface():
    audit = load_audit_module()

    assert audit.main() == 0


def test_sdk_parity_audit_keeps_newsletter_cli_only():
    audit = load_audit_module()

    assert "newsletter" not in audit.SDK_TS.read_text(encoding="utf-8").lower()
    assert "newsletter" not in audit.SDK_PY.read_text(encoding="utf-8").lower()
    assert all("newsletter" not in entry.npm for entry in audit.PARITY_ENTRIES)
    assert all("newsletter" not in entry.pip for entry in audit.PARITY_ENTRIES)


def test_sdk_parity_audit_fails_unclassified_cli_command(monkeypatch, tmp_path):
    audit = load_audit_module()
    cli_copy = tmp_path / "cli.ts"
    cli_copy.write_text(
        audit.CLI_TS.read_text(encoding="utf-8") + '\nif (command === "new-cli-command") {}\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(audit, "CLI_TS", cli_copy)

    assert audit.main() == 1
