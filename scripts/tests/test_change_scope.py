# contract-test-file: tooling
"""Small-fix change-scope limits for AI test-user sessions (TASK-8809)."""
import pytest

from scripts import change_scope as cs


def _files(n, lines=10):
    return [(f"backend/core/mod{i}.py", lines, 0, False) for i in range(n)]


def test_within_limits():
    assert cs.check_small_fix(_files(6, 25)) == []


def test_too_many_files():
    assert any("files changed" in r for r in cs.check_small_fix(_files(7, 1)))


def test_too_many_lines_but_tests_excluded():
    assert any("non-test lines" in r for r in cs.check_small_fix(_files(2, 76)))
    tests = [("frontend/x.spec.ts", 500, 0, False), ("scripts/tests/test_a.py", 500, 0, False),
             ("backend/core/a.py", 100, 50, False)]
    assert cs.check_small_fix(tests) == []


def test_new_source_file_refused_new_test_file_allowed():
    assert any("new source file" in r for r in cs.check_small_fix([("backend/core/new.py", 5, 0, True)]))
    assert cs.check_small_fix([("backend/tests/test_new.py", 5, 0, True)]) == []


@pytest.mark.parametrize("path", [
    "backend/core/directus/schemas/chats.yml", "backend/migrations/001.py", "docs/plans/x/plan.yml",
    "specifications/a.yml"])
def test_protected_paths(path):
    assert any("protected area" in r for r in cs.check_small_fix([(path, 1, 0, False)]))


def test_route_decorator():
    assert cs.has_new_route_decorator(['@router.post("/v1/x")'])
    assert not cs.has_new_route_decorator(["x = 1"])
    assert any("API route" in r for r in cs.check_small_fix(_files(1), ["backend/a.py"]))
