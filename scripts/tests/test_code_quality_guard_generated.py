#!/usr/bin/env python3
"""Regression test: generated UniFFI Swift is exempt from the source-size and marker rules."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
GUARD_PATH = PROJECT_ROOT / "scripts" / "code_quality_guard.py"
GENERATED = "apple/OpenMatesCore/Sources/OpenMatesCore/OpenMatesCore.swift"
HANDWRITTEN = "apple/OpenMates/Sources/Big.swift"


def load_guard_module():
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location("openmates_code_quality_guard_generated", GUARD_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# contract-test: tooling
def test_generated_bindings_skip_line_limit_and_todo_check(monkeypatch, capsys):
    guard = load_guard_module()
    monkeypatch.setattr(guard, "_staged_files", lambda: [GENERATED, HANDWRITTEN])
    monkeypatch.setattr(guard, "_staged_file_line_count", lambda path: 2585)
    monkeypatch.setattr(guard, "_is_new_file", lambda path: True)
    monkeypatch.setattr(
        guard, "_added_lines_with_numbers",
        lambda: [(GENERATED, 1, "// TODO generated"), (HANDWRITTEN, 1, "// TODO manual")],
    )
    monkeypatch.setattr(guard, "_git", lambda args, check=True: subprocess.CompletedProcess(args, 0, stdout="", stderr=""))
    assert guard.main() == 1
    err = capsys.readouterr().err
    assert GENERATED not in err
    assert f"{HANDWRITTEN}: new source file has 2585 lines" in err
    assert f"{HANDWRITTEN}: new TODO" in err
