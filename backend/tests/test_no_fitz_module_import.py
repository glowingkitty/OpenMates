# backend/tests/test_no_fitz_module_import.py
# contract-test-file: tooling
#
# Importing PyMuPDF under its legacy module name `fitz` prints
# "warning: The `fitz` API is deprecated ..." to stdout. CLI and E2E checks
# that parse the stdout of backend scripts (JSON receipts, exact output)
# failed on that line in the daily run. Backend code imports `pymupdf`.

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOTS = ("backend", "scripts")


def _fitz_imports(path: Path) -> list[int]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (SyntaxError, UnicodeDecodeError):
        return []
    lines = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import) and any(
            alias.name == "fitz" or alias.name.startswith("fitz.") for alias in node.names
        ):
            lines.append(node.lineno)
        if isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] == "fitz":
            lines.append(node.lineno)
    return lines


def test_no_module_imports_pymupdf_as_fitz() -> None:
    offenders = []
    for root in SOURCE_ROOTS:
        for path in (REPO_ROOT / root).rglob("*.py"):
            if "node_modules" in path.parts or ".venv" in path.parts:
                continue
            offenders.extend(f"{path.relative_to(REPO_ROOT)}:{line}" for line in _fitz_imports(path))
    assert offenders == [], "use `import pymupdf as fitz`: " + ", ".join(offenders)
