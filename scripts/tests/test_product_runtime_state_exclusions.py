"""Keep coordinator-only runtime state out of OpenCode filesystem patches."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_product_runtime_state_is_gitignored() -> None:
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()

    assert ".claude/product-runtime-state.json" in gitignore
    assert ".claude/product-runtime-state.lock" in gitignore
    assert ".claude/product-runtime-state.tmp" in gitignore
