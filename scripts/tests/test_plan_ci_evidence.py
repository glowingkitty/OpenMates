"""Keep Plan evidence aligned with isolated GitHub CI.

Validate execution provenance without requiring a shared dev deployment.
An older tested ancestor cannot prove a newer implementation correct.
These tests use local Git fixtures and never dispatch product tests.
See docs/architecture/codex-orchestration.md for delivery ownership.
"""
from pathlib import Path
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import plan_validate
import plan_verify


def test_isolated_playwright_contract():
    plan_validate._validate_tests({'tests': [{
        'id': 'T-SYNC', 'type': 'playwright', 'file': 'project-task-sync.spec.ts',
        'command': 'python3 scripts/ci_coordinator.py submit --session example --source candidate --spec project-task-sync.spec.ts --mode e2e',
        'execution_environment': 'isolated_github_ci', 'target': 'isolated_github_ci',
        'assertions': ['synchronizes a committed update'], 'covers': ['AC-1'],
        'red_phase': {'required': True, 'expected': 'fail', 'evidence': {'status': 'pending'}},
        'green_phase': {'required': True, 'expected': 'pass', 'evidence': {'status': 'pending'}},
    }]}, {'AC-1'}, 2)


def evidence(**changes):
    return dict(status='passed', timestamp='2026-09-09T00:00:00Z', command='ci_coordinator.py submit',
                run_id='123', subject_commit='a'*40, execution_environment='isolated_github_ci',
                harness_commit='b'*40, profile='e2e', artifacts=['report.json'], **changes)


def failures(proof):
    return plan_verify._evidence_contract_failures(
        {'schema_version': 2, 'implementation_state': {'subject_commit': 'a'*40}},
        record_id='T-SYNC', phase='green_phase', evidence=proof, automated=True, playwright=True)


def test_ci_proof_does_not_require_shared_deployment():
    assert failures(evidence()) == []


@pytest.mark.parametrize('field', ['harness_commit', 'profile', 'artifacts'])
def test_ci_proof_requires_provenance(field):
    proof = evidence()
    proof.pop(field)
    assert any(field in item for item in failures(proof))


def test_ancestor_proof_is_stale(tmp_path, monkeypatch):
    def git(*args):
        return subprocess.check_output(['git', *args], cwd=tmp_path, text=True).strip()
    git('init', '-q')
    git('-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '--allow-empty', '-qm', 'base')
    base = git('rev-parse', 'HEAD')
    (tmp_path/'implementation.py').write_text('changed = True\n')
    git('add', 'implementation.py')
    git('-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '-qm', 'change')
    head = git('rev-parse', 'HEAD')
    monkeypatch.setattr(plan_verify, 'REPO_ROOT', tmp_path)
    assert not plan_verify._evidence_commit_covers_implementation(base, head)
    assert plan_verify._evidence_commit_covers_implementation(head, head)
