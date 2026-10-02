#!/usr/bin/env python3
"""Test the isolated CI proof-source trust boundary without network access.

Synthetic runner receipts exercise source, profile, coverage, and artifact
binding failures. No test creates a visual approval or replaces a product
recording. Actual fetched receipt verification is recorded separately.
"""
# contract-test-file: tooling
import base64
import hashlib
import json
import shutil
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


def test_ci_source_infers_cli_terminal_from_bound_timeline_and_mp4(receipt):
    root = receipt.parent
    value = json.loads(receipt.read_text())
    value['report']['proof_profile'] = ''
    receipt.write_text(json.dumps(value))
    (root / 'test-results/ci-results.json').write_text(json.dumps(value['report']))
    video = root / 'raw-terminal.mp4'
    video.write_bytes(b'real terminal fixture pixels')
    digest = 'sha256:' + hashlib.sha256(video.read_bytes()).hexdigest()
    original = '/runner/subject/raw-terminal.mp4'
    plan = root / 'input-plan.json'
    plan.write_text(json.dumps({'steps': [
        {'name': 'initial-closed', 'wait_for': 'New chat', 'hold_ms': 350},
        {'name': 'welcome-hold', 'key': 'Right', 'wait_for': 'New chat', 'hold_ms': 1000},
        {'name': 'sidebar-open', 'key': 'ctrl+b', 'wait_for': 'Recent chats', 'hold_ms': 1500},
        {'name': 'example-open', 'key': 'Return', 'wait_for': 'General Knowledge', 'hold_ms': 1500},
    ]}))
    events = root / 'events.jsonl'
    events.write_text('0.340519 8\n0.200000 14\n')
    manifest = root / 'manifest.json'
    manifest.write_text(json.dumps({'capture_kind': 'real_terminal_screen', 'reconstructed': False,
                                    'exit_status': 0, 'width': 1280, 'height': 720,
                                    'video_path': original, 'video_sha256': digest,
                                    'input_plan_path': '/runner/subject/input-plan.json',
                                    'input_plan_sha256': 'sha256:' + hashlib.sha256(plan.read_bytes()).hexdigest(),
                                    'events_path': '/runner/subject/events.jsonl',
                                    'events_sha256': 'sha256:' + hashlib.sha256(events.read_bytes()).hexdigest(),
                                    'input_checkpoints': [
                                        {'name': 'initial-closed', 'at_ms': 2257, 'marker': 'New chat'},
                                        {'name': 'welcome-hold', 'at_ms': 3329, 'marker': 'New chat'},
                                        {'name': 'sidebar-open', 'at_ms': 4912, 'marker': 'Recent chats'},
                                        {'name': 'example-open', 'at_ms': 21112, 'marker': 'General Knowledge'},
                                    ]}))
    timeline = {'device': 'cli-terminal', 'contract': {'surface': 'cli', 'assertions': [
                    {'id': 'sidebar', 'checkpoint': 'sidebar-open'},
                    {'id': 'example', 'checkpoint': 'example-open'},
                ]},
                'source_video_path': original, 'source_video_sha256': digest,
                'events': [
                    {'id': 'initial-closed', 'kind': 'checkpoint', 'at_ms': 2257},
                    {'id': 'welcome-hold', 'kind': 'checkpoint', 'at_ms': 3329},
                    {'id': 'sidebar-open', 'kind': 'checkpoint', 'at_ms': 4912},
                    {'id': 'example-open', 'kind': 'checkpoint', 'at_ms': 21112},
                ],
                'assertion_results': [{'id': 'sidebar', 'status': 'passed', 'at_ms': 4912},
                                      {'id': 'example', 'status': 'passed', 'at_ms': 21112}]}
    attachments = [
        {'name': 'openmates-cli-real-terminal-video', 'path': original},
        {'name': 'openmates-cli-real-terminal-manifest', 'path': '/runner/subject/manifest.json'},
        {'name': 'openmates-proof-timeline', 'body': base64.b64encode(json.dumps(timeline).encode()).decode()},
    ]
    (root / 'test-results/ci-spec-0.json').write_text(json.dumps({'results': [{'status': 'passed', 'attachments': attachments}]}))
    records = receipt_sources(receipt)
    assert len(records) == 1
    assert records[0]['proof_video_profile'] == 'cli-terminal'
    assert records[0]['artifact_sha256'] == digest
    assert records[0]['state_change_timestamps_by_id'] == {'sidebar': 3.412, 'example': 19.612}
    assert records[0]['state_change_timestamps'] == [3.612, 19.812]
    assert records[0]['capture_ready_timestamp_seconds'] == 2.257
    assert records[0]['closed_screen_checkpoint_seconds'] == 3.329
    assert records[0]['source_end_timestamp_seconds'] == 21.112
    assert receipt_sources(receipt) == records


def test_ci_source_rejects_changed_cli_input_plan(receipt):
    test_ci_source_infers_cli_terminal_from_bound_timeline_and_mp4(receipt)
    (receipt.parent / 'input-plan.json').write_text('{"steps": []}')
    with pytest.raises(CIProofError, match='plan or PTY timing events changed'):
        receipt_sources(receipt)


def test_ci_source_rejects_changed_cli_timing_events(receipt):
    test_ci_source_infers_cli_terminal_from_bound_timeline_and_mp4(receipt)
    (receipt.parent / 'events.jsonl').write_text('0.100000 8\n')
    with pytest.raises(CIProofError, match='plan or PTY timing events changed'):
        receipt_sources(receipt)


def test_ci_source_uses_final_asserted_checkpoint_without_welcome_marker(receipt):
    test_ci_source_infers_cli_terminal_from_bound_timeline_and_mp4(receipt)
    root = receipt.parent
    shutil.rmtree(root / 'proof-source-bindings')
    plan_path = root / 'input-plan.json'
    plan = json.loads(plan_path.read_text())
    plan['steps'] = [step for step in plan['steps'] if step['name'] != 'welcome-hold']
    plan['steps'][-1]['name'] = 'apps-home'
    plan_path.write_text(json.dumps(plan))
    manifest_path = root / 'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    manifest['input_checkpoints'] = [step for step in manifest['input_checkpoints'] if step['name'] != 'welcome-hold']
    manifest['input_checkpoints'][-1]['name'] = 'apps-home'
    manifest['input_plan_sha256'] = 'sha256:' + hashlib.sha256(plan_path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest))
    report_path = root / 'test-results/ci-spec-0.json'
    report = json.loads(report_path.read_text())
    attachment = next(a for a in report['results'][0]['attachments'] if a['name'] == 'openmates-proof-timeline')
    timeline = json.loads(base64.b64decode(attachment['body']))
    timeline['events'] = [event for event in timeline['events'] if event['id'] != 'welcome-hold']
    timeline['events'][-1]['id'] = 'apps-home'
    timeline['contract']['assertions'][-1]['checkpoint'] = 'apps-home'
    attachment['body'] = base64.b64encode(json.dumps(timeline).encode()).decode()
    report_path.write_text(json.dumps(report))
    record = receipt_sources(receipt)[0]
    assert record['source_end_timestamp_seconds'] == 21.112
    assert 'closed_screen_checkpoint_seconds' not in record
    assert record['state_change_timestamps_by_id']['example'] == 19.612


def test_ci_source_rejects_cli_capture_hash_mismatch(receipt):
    root = receipt.parent
    value = json.loads(receipt.read_text())
    value['report']['proof_profile'] = ''
    receipt.write_text(json.dumps(value))
    (root / 'test-results/ci-results.json').write_text(json.dumps(value['report']))
    (root / 'raw-terminal.mp4').write_bytes(b'pixels')
    (root / 'manifest.json').write_text(json.dumps({'capture_kind': 'real_terminal_screen', 'reconstructed': False,
        'exit_status': 0, 'width': 1280, 'height': 720, 'video_path': '/runner/subject/raw-terminal.mp4',
        'video_sha256': 'sha256:' + '0' * 64}))
    timeline = {'device': 'cli-terminal', 'contract': {'surface': 'cli'},
        'source_video_path': '/runner/subject/raw-terminal.mp4', 'source_video_sha256': 'sha256:' + '0' * 64,
        'assertion_results': [{'id': 'visible', 'status': 'passed'}]}
    attachments = [
        {'name': 'openmates-cli-real-terminal-video', 'path': '/runner/subject/raw-terminal.mp4'},
        {'name': 'openmates-cli-real-terminal-manifest', 'path': '/runner/subject/manifest.json'},
        {'name': 'openmates-proof-timeline', 'body': base64.b64encode(json.dumps(timeline).encode()).decode()},
    ]
    (root / 'test-results/ci-spec-0.json').write_text(json.dumps({'results': [{'status': 'passed', 'attachments': attachments}]}))
    with pytest.raises(CIProofError, match='do not bind'):
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
