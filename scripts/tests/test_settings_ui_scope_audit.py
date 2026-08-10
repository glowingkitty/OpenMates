"""Tests for deterministic, snapshot-scoped settings UI audits.

The scoped report must stay stable for unchanged files, derive the canonical
component inventory from disk, and reject paths outside the settings tree.
Tests use a temporary repository root and never inspect private chat data.
Run: python3 -m pytest scripts/tests/test_settings_ui_scope_audit.py.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
AUDIT_PATH = ROOT / "scripts" / "contract_audits.py"


def load_audit_module():
    scripts_dir = str(AUDIT_PATH.parent)
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    spec = importlib.util.spec_from_file_location("settings_scope_contract_audits", AUDIT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def configure_repo(audit, tmp_path: Path) -> tuple[Path, Path]:
    audit.REPO_ROOT = tmp_path
    audit.SETTINGS_ROOT = tmp_path / "frontend/packages/ui/src/components/settings"
    audit.SETTINGS_ELEMENTS_ROOT = audit.SETTINGS_ROOT / "elements"
    audit.SETTINGS_ELEMENTS_ROOT.mkdir(parents=True)
    (audit.SETTINGS_ELEMENTS_ROOT / "SettingsButton.svelte").write_text("<button data-testid=\"ok\">OK</button>\n")
    target = audit.SETTINGS_ROOT / "account/AccountSettings.svelte"
    target.parent.mkdir(parents=True)
    target.write_text("<button>Save</button>\n")
    return target, audit.SETTINGS_ELEMENTS_ROOT


def test_scoped_report_is_stable_and_uses_live_component_inventory(tmp_path: Path) -> None:
    audit = load_audit_module()
    target, elements = configure_repo(audit, tmp_path)

    first = audit.build_settings_scope_report([target])
    second = audit.build_settings_scope_report([target])

    assert first == second
    assert first["canonical_components"] == ["SettingsButton"]
    assert first["summary"]["counts_by_rule"] == {"SETTINGS-MISSING-TESTID": 1}
    assert first["files"][0]["path"].endswith("AccountSettings.svelte")

    (elements / "SettingsItem.svelte").write_text("<div><slot /></div>\n")
    updated = audit.build_settings_scope_report([target])
    assert updated["snapshot_id"] != first["snapshot_id"]
    assert updated["canonical_components"] == ["SettingsButton", "SettingsItem"]


def test_scoped_report_changes_when_target_content_changes(tmp_path: Path) -> None:
    audit = load_audit_module()
    target, _ = configure_repo(audit, tmp_path)
    original = audit.build_settings_scope_report([target])

    target.write_text("<button data-testid=\"save\">Save</button>\n")
    updated = audit.build_settings_scope_report([target])

    assert updated["snapshot_id"] != original["snapshot_id"]
    assert updated["summary"]["total_findings"] == 0


def test_scoped_report_rejects_paths_outside_settings(tmp_path: Path) -> None:
    audit = load_audit_module()
    configure_repo(audit, tmp_path)
    outside = tmp_path / "frontend/Other.svelte"
    outside.parent.mkdir(parents=True, exist_ok=True)
    outside.write_text("<button>Outside</button>\n")

    with pytest.raises(ValueError, match="outside"):
        audit.build_settings_scope_report([outside])
