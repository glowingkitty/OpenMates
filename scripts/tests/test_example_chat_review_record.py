#!/usr/bin/env python3
"""Tooling tests for rendered example admission record validation.

Protect against stale transcript evidence and incomplete browser/audio checks.
These are tooling-only checks, not product or browser behavior proof.
Run locally with pytest; no network, accounts, or media generation required.
Records reference temporary synthetic files rather than real user transcripts.
"""
# contract-test-file: tooling
import copy
import hashlib

from test_example_chat_usage_coverage import load_example_audit


def receipt(tmp_path):
    files = {}
    for relative in (
        'frontend/packages/ui/src/demo_chats/data/example_chats/test.ts',
        'frontend/packages/ui/src/i18n/sources/example_chats/test.yml',
    ):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('synthetic content')
        files[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return dict(slug='test', source_chat_id='source-test', deployed_commit='a' * 40,
                reviewed_at='2026-09-08T12:00:00Z', files=files, verdict='keep', open_defects=[],
                checks={name: dict(status='passed', evidence='run and observation')
                        for name in ('cli_content', 'phone', 'laptop', 'guest_speech')})


def test_complete_and_stale_content(tmp_path):
    audit = load_example_audit()
    record = receipt(tmp_path)
    assert audit.audit_review_record(record, 'a' * 40, tmp_path) == []
    (tmp_path / next(iter(record['files']))).write_text('changed content')
    assert any('stale' in issue for issue in audit.audit_review_record(record, 'a' * 40, tmp_path))


def test_pending_speech_mismatched_commit_and_open_defects(tmp_path):
    audit = load_example_audit()
    record = receipt(tmp_path)
    for mutation in ('speech', 'commit', 'defect', 'evidence'):
        candidate = copy.deepcopy(record)
        if mutation == 'speech':
            candidate['checks']['guest_speech']['status'] = 'pending'
        elif mutation == 'commit':
            candidate['deployed_commit'] = 'b' * 40
        elif mutation == 'defect':
            candidate['open_defects'] = ['broken link']
        else:
            candidate['checks']['phone']['evidence'] = ''
        assert audit.audit_review_record(candidate, 'a' * 40, tmp_path)


def test_malformed_and_outside_files(tmp_path):
    audit = load_example_audit()
    assert audit.audit_review_record({}, 'a' * 40, tmp_path)
    record = receipt(tmp_path)
    record['files']['../outside'] = 'x'
    record['checks'] = []
    assert any('outside' in issue for issue in audit.audit_review_record(record, 'a' * 40, tmp_path))
