# contract-test-file: tooling
"""Guard installer admission and expression handling without starting a stack.

The original installer steps remain owned by the source workflow. The adapter
must reject unsupported Actions inputs and any non-GitHub execution before
reading installation state. Queue accounting is shared with ordinary E2E.
See docs/architecture/isolated-github-tests.md.
"""

import sys
from pathlib import Path

import pytest
from scripts import ci_environment


def module(monkeypatch):
    monkeypatch.setitem(sys.modules, "ci_environment", ci_environment)
    from scripts import ci_selfhost
    return ci_selfhost


def test_only_explicit_nonsecret_workflow_expressions_expand(monkeypatch):
    runner = module(monkeypatch)
    assert runner.expand('${{ github.workspace }}/${{ env.TAG }}', {'TAG': 'local'}, Path('/runner/subject'), 'a' * 40) == '/runner/subject/local'
    assert runner.expand('${{ github.sha }}', {}, Path('/runner'), 'a' * 40) == 'a' * 40
    with pytest.raises(ValueError, match='Unsupported'):
        runner.expand('${{ secrets.PROVIDER_KEY }}', {}, Path('/runner'), 'a' * 40)


def test_installer_refuses_local_execution_before_any_state_read(monkeypatch):
    runner = module(monkeypatch)
    monkeypatch.delenv('GITHUB_ACTIONS', raising=False)
    with pytest.raises(RuntimeError, match='GitHub-hosted'):
        runner.run(Path('/nonexistent'), [])


def test_installer_has_separate_queue_mode_and_exact_spec(tmp_path):
    from scripts.ci_coordinator import Queue
    from scripts.ci_coverage import execution_mode, partition
    queue = Queue(tmp_path / 'queue.sqlite3')
    spec = 'selfhost-smoke.spec.ts'
    assert partition([spec]) == ([spec], {})
    assert execution_mode(spec) == 'selfhost'
    queue.enqueue('fixture', 'a' * 40, [spec], 'selfhost')
    with pytest.raises(ValueError, match='exactly'):
        queue.enqueue('fixture', 'a' * 40, ['other.spec.ts'], 'selfhost')
