#!/usr/bin/env python3
"""sessions.py lint/deploy must run the Rust migration YAML check for its inputs."""

# contract-test-file: tooling

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

SESSIONS_PATH = Path(__file__).resolve().parents[1] / "sessions.py"


def load():
    spec = importlib.util.spec_from_file_location("openmates_sessions_rust_lint", SESSIONS_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_failing_check_blocks_with_fix_hint(monkeypatch) -> None:
    sessions = load()
    calls = []

    def fake(cmd, cwd=None, timeout=120):
        calls.append(cmd)
        return 1, "", "performance-history.yml: bad flow"

    monkeypatch.setattr(sessions, "_run_cmd", fake)
    rc, _out, err = sessions._run_lint(["docs/migration/rust/performance-history.yml"])
    assert rc == 1
    assert calls[0][-2:] == ["scripts/rust_migration_yaml.py", "--check"][-2:]
    assert "rust_migration_yaml.py" in err and "Fix:" in err


def test_clean_check_passes_and_unrelated_files_skip(monkeypatch) -> None:
    sessions = load()
    calls = []

    def fake(cmd, cwd=None, timeout=120):
        calls.append(cmd)
        return 0, "", ""

    monkeypatch.setattr(sessions, "_run_cmd", fake)
    rc, out, _err = sessions._run_lint(["config/sdk-capabilities.json"])
    assert rc == 0 and "Rust migration YAML: ok" in out and len(calls) == 1
    calls.clear()
    assert sessions._run_lint(["README.md"]) == (0, "", "")
    assert calls == []
