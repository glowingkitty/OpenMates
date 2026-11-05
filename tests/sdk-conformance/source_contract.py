"""Formatting-independent source contracts for the conformance tooling tests.

Several tooling tests pin that a runner or gate still contains a specific
assertion, deadline or cleanup statement. Comparing raw text made those pins
fail whenever a formatter changed quotes, spacing or split ``a;b`` into two
lines, although the code was unchanged. These helpers keep the exact same
requirement (the statement or expression must be present) but compare Python
code by its canonical ``ast.unparse`` form, so only a semantic change fails.
"""

from __future__ import annotations

import ast
from functools import lru_cache


@lru_cache(maxsize=None)
def _canonical(source: str) -> str:
    """Canonical Python text with per-line indentation removed."""
    tree = ast.parse(source)
    return "\n".join(line.strip() for line in ast.unparse(tree).splitlines())


def _canonical_snippet(snippet: str) -> str | None:
    # Expression mode first: a lone string constant would otherwise be
    # rendered as a module docstring by ast.unparse.
    try:
        return ast.unparse(ast.parse(snippet, mode="eval"))
    except SyntaxError:
        pass
    try:
        return _canonical(snippet)
    except SyntaxError:
        return None


def python_contains(source: str, snippet: str) -> bool:
    """True when ``snippet`` occurs verbatim or as canonical code in ``source``.

    ``snippet`` is either literal text (for example a string constant's content)
    or a parseable Python expression/statement sequence such as
    ``"os.killpg(p.pid,signal.SIGKILL);p.wait(timeout=2)"``.
    """
    if snippet in source:
        return True
    canonical = _canonical_snippet(snippet)
    return canonical is not None and canonical in _canonical(source)


def assert_python_contains(source: str, *snippets: str) -> None:
    missing = [snippet for snippet in snippets if not python_contains(source, snippet)]
    assert not missing, f"source contract missing: {missing}"


def python_index(source: str, snippet: str, start: int = 0) -> int:
    """Position of ``snippet`` in the canonical form of ``source`` (after ``start``).

    Positions from this function are comparable with each other for the same
    ``source``, so tests can keep asserting statement order independently of
    formatting. Raises ``ValueError`` when the code is absent.
    """
    canonical = _canonical_snippet(snippet)
    if canonical is None:
        raise ValueError(f"snippet is not Python code: {snippet!r}")
    return _canonical(source).index(canonical, start)
