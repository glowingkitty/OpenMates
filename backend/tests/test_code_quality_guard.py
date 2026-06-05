# backend/tests/test_code_quality_guard.py
#
# Unit coverage for the staged maintainability guard used by git hooks. The
# tests monkeypatch git-facing helpers so no repository state is modified.
# Architecture context: scripts/code_quality_guard.py

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import code_quality_guard  # noqa: E402


def test_guard_blocks_generated_locale_json(monkeypatch) -> None:
    """Generated locale JSON edits should always block commits."""

    monkeypatch.setattr(code_quality_guard, "_staged_files", lambda: ["frontend/packages/ui/src/i18n/locales/en.json"])
    monkeypatch.setattr(code_quality_guard, "_added_lines", lambda: [])

    assert code_quality_guard.main() == 1


def test_guard_blocks_new_large_source_file(monkeypatch) -> None:
    """New source files above the limit should be split before committing."""

    monkeypatch.setattr(code_quality_guard, "_staged_files", lambda: ["frontend/packages/ui/src/components/Huge.svelte"])
    monkeypatch.setattr(code_quality_guard, "_added_lines", lambda: [])
    monkeypatch.setattr(code_quality_guard, "_is_new_file", lambda _path: True)
    monkeypatch.setattr(code_quality_guard, "_staged_file_line_count", lambda _path: code_quality_guard.NEW_FILE_LINE_LIMIT + 1)

    assert code_quality_guard.main() == 1


def test_guard_warns_but_allows_broad_exception_by_default(monkeypatch) -> None:
    """Broad catches are warnings unless strict mode is enabled."""

    monkeypatch.delenv("CODE_QUALITY_GUARD_STRICT", raising=False)
    monkeypatch.setattr(code_quality_guard, "_staged_files", lambda: [])
    monkeypatch.setattr(code_quality_guard, "_added_lines", lambda: [("backend/example.py", "except Exception as exc:")])

    assert code_quality_guard.main() == 0


def test_guard_strict_mode_blocks_warnings(monkeypatch) -> None:
    """Strict mode lets CI or future hooks promote warnings to failures."""

    monkeypatch.setenv("CODE_QUALITY_GUARD_STRICT", "1")
    monkeypatch.setattr(code_quality_guard, "_staged_files", lambda: [])
    monkeypatch.setattr(code_quality_guard, "_added_lines", lambda: [("frontend/example.ts", "// TODO: follow up")])

    assert code_quality_guard.main() == 1
