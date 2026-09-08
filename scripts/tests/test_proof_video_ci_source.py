#!/usr/bin/env python3
"""Test the isolated CI proof-source trust boundary without network access.

Synthetic runner receipts exercise source, profile, coverage, and artifact
binding failures. No test creates a visual approval or replaces a product
recording. Actual fetched receipt verification is recorded separately.
"""
# contract-test-file: tooling
import base64
import json
from pathlib import Path

import pytest

from scripts.proof_video_ci_source import CIProofError, receipt_sources


@pytest.fixture
def receipt(tmp_path: Path):
    (tmp_path / 'test-results').mkdir()
    source = 'a' * 40
    harness = 'b' * 40
    identity = {'source_commit': source, 'harness_commit': harness, 'run_id': '123'}
    report = {**identity, 'success': True, 'proof_profile': 'web-phone', 'results': [
        {'spec': 'example.spec.ts', 'exit_code': 0, 'coverage_complete': True,
         'stats': {'expected': 1, 'skipped': 0, 'unexpected': 0, 'flaky': 0}}]}
    environment = {**identity, 'runner_environment': 'github-hosted', 'shared_dev_https': 'rejected',
                   'frontend': {'source_commit': source}}
    value = {**identity, 'state': 'success', 'report': report, 'environment': environment,
             'runner_jobs': [{'labels': ['ubuntu-latest'], 'runner_name': 'GitHub Actions fixture'}]}
    path = tmp_path / 'receipt.json'
    path.write_text(json.dumps(value))
    (tmp_path / 'test-results/ci-results.json').write_text(json.dumps(report))
    (tmp_path / 'test-results/ci-environment.json').write_text(json.dumps(environment))
    timeline = {'device': 'web-phone', 'assertion_results': [{'id': 'visible', 'status': 'passed'}]}
    attachments = [{'name': 'video', 'path': '/runner/subject/video.webm'},
                   {'name': 'openmates-proof-timeline', 'body': base64.b64encode(json.dumps(timeline).encode()).decode()}]
    (tmp_path / 'test-results/ci-spec-0.json').write_text(json.dumps({'results': [{'status': 'passed', 'attachments': attachments}]}))
    (tmp_path / 'video.webm').write_bytes(b'synthetic recording')
    return path


def test_ci_source_preserves_isolated_provenance_and_hashes(receipt):
    records = receipt_sources(receipt)
    assert len(records) == 1
    record = records[0]
    assert record['source'] == 'github_isolated'
    assert 'deployment_verified' not in record
    assert record['isolation_verified'] is True
    assert record['artifact_sha256'].startswith('sha256:')
    assert record['proof_video_profile'] == 'web-phone'
    assert receipt_sources(receipt) == records


def test_ci_source_rejects_changed_bound_video(receipt):
    receipt_sources(receipt)
    (receipt.parent / 'video.webm').write_bytes(b'changed recording')
    with pytest.raises(CIProofError, match='changed'):
        receipt_sources(receipt)


def test_ci_source_rejects_unbound_report_modification(receipt):
    report = receipt.parent / 'test-results/ci-results.json'
    report.write_text('{}')
    with pytest.raises(CIProofError, match='differs'):
        receipt_sources(receipt)


@pytest.mark.parametrize('case', ['source', 'harness', 'runner', 'frontend', 'skipped', 'profile', 'traversal'])
def test_ci_source_rejects_invalid_evidence(receipt, case):
    value = json.loads(receipt.read_text())
    if case in ('source', 'harness'):
        value['report'][case + '_commit'] = 'c' * 40
    elif case == 'runner':
        value['runner_jobs'][0]['runner_name'] = 'shared-dev'
    elif case == 'frontend':
        value['environment']['frontend']['source_commit'] = 'c' * 40
    elif case == 'skipped':
        value['report']['results'][0]['stats']['skipped'] = 1
    elif case == 'profile':
        value['report']['proof_profile'] = 'web-laptop'
    else:
        report = receipt.parent / 'test-results/ci-spec-0.json'
        data = json.loads(report.read_text())
        data['results'][0]['attachments'][0]['path'] = '/runner/subject/../../outside.webm'
        report.write_text(json.dumps(data))
    receipt.write_text(json.dumps(value))
    (receipt.parent / 'test-results/ci-results.json').write_text(json.dumps(value['report']))
    (receipt.parent / 'test-results/ci-environment.json').write_text(json.dumps(value['environment']))
    with pytest.raises(CIProofError):
        receipt_sources(receipt)
