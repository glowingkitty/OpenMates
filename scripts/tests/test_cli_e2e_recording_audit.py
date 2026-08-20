"""Tests for deterministic real CLI E2E recording coverage.

The audit prevents new Playwright CLI process entry points from bypassing the
shared recorder. Direct process spawning remains allowed only for explicitly
classified interactive login and the recorder-aware helper fallback.
"""

# contract-test-file: tooling

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts" / "audit_cli_e2e_recording.py"


def load_module():
    spec = importlib.util.spec_from_file_location("audit_cli_e2e_recording", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_direct_cli_spawn_requires_supported_classification(tmp_path: Path) -> None:
    module = load_module()
    source = tmp_path / "example.spec.ts"
    source.write_text(
        "const child = spawn('node', [CLI_DIST, ...args], {});\n",
        encoding="utf-8",
    )
    findings = module.scan_path(source)
    assert len(findings) == 1
    assert findings[0].kind == "unclassified-direct-spawn"

    source.write_text(
        "// cli-e2e-recording: interactive-pair-login\n"
        "const child = spawn('node', [CLI_DIST, 'login'], {});\n",
        encoding="utf-8",
    )
    assert module.scan_path(source) == []


def test_invalid_or_mismatched_classification_is_rejected(tmp_path: Path) -> None:
    module = load_module()
    source = tmp_path / "example.spec.ts"
    source.write_text(
        "// cli-e2e-recording: interactive-pair-login\n"
        "const child = spawn('node', [CLI_DIST, ...args], {});\n",
        encoding="utf-8",
    )
    findings = module.scan_path(source)
    assert len(findings) == 1
    assert findings[0].kind == "classification-mismatch"


def test_repository_cli_e2e_entry_points_are_covered() -> None:
    module = load_module()
    report = module.build_report()
    assert report["ok"], report["findings"]
