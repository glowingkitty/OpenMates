"""Pure closed diagnostic tests; never execute an adapter, SDK or child.

Synthetic private canaries must not enter the normalized public receipt.
Attribution requires a failed known vector and the exact npm capability.
Existing Rust diagnostics and all acceptance gates remain unchanged.
This is source evidence, never runtime/conformance acceptance proof.
"""
# contract-test-file: tooling
import json
import pytest
from scripts import ci_sdk_conformance as sdk


def expected():
    return {'capability': 'session.chat-first-page-continuation.v1', 'language': 'npm',
            'fixtureSha256': 'a' * 64, 'vectors': ['cold-uuid']}


def diagnostic():
    return {'vectorId': 'cold-uuid', 'phase': 'callback', 'errorCode': 'assertion',
            'sourceCoordinate': 'runner.callback'}


def test_exact_failed_npm_vector_diagnostic_is_retained():
    assert sdk.project_vector_diagnostic(diagnostic(), expected(), ['cold-uuid']) == diagnostic()


@pytest.mark.parametrize('field,value', [
    ('vectorId', 'unknown-private-id'), ('phase', 'PRIVATE_COOKIE'),
    ('errorCode', 'PRIVATE_CONTENT'), ('sourceCoordinate', 'PRIVATE_STACK'),
    ('sourceCoordinate', 'runner.peer_start'), ('sourceCoordinate', 'runner:123:45'),
    ('private', 'PRIVATE_SECRET'),
])
def test_unknown_values_and_fields_are_refused(field, value):
    assert sdk.project_vector_diagnostic({**diagnostic(), field: value}, expected(), ['cold-uuid']) is None


@pytest.mark.parametrize('language', ['rust', 'python', 'npm-private'])
def test_diagnostic_does_not_broaden_language_scope(language):
    assert sdk.project_vector_diagnostic(diagnostic(), {**expected(), 'language': language}, ['cold-uuid']) is None


def test_success_or_unknown_capability_cannot_authorize_attribution():
    assert sdk.project_vector_diagnostic(diagnostic(), expected(), []) is None
    assert sdk.project_vector_diagnostic(diagnostic(), {**expected(), 'capability': 'unrelated'}, ['cold-uuid']) is None


def test_actual_failure_normalizer_preserves_closed_diagnostic(tmp_path):
    private = tmp_path / 'private'
    private.mkdir()
    failure = {'code': 'driver_failed', 'adapter': expected(), 'returncode': 1,
               'failedVectorIds': ['cold-uuid'], 'diagnostic': diagnostic()}
    (private / 'driver-failure.json').write_text(json.dumps(failure))
    result = sdk.failure_diagnostics(private, tmp_path, 'real-conformance', {}, [expected()])
    assert result['failedVectorIds'] == ['cold-uuid']
    assert result['vectorAttribution'] == 'exact-known-ids'
    assert result['diagnostic'] == diagnostic()
    assert result['rawUpload'] is False and result['driverReturncode'] == 1
    assert 'status' not in result and 'PRIVATE_' not in json.dumps(result)


def test_existing_rust_monitor_diagnostic_stays_unchanged():
    item = {'vectorId': 'cold-uuid', 'phase': 'open', 'errorCode': 'assertion'}
    identity = {**expected(), 'language': 'rust', 'capability': 'session.chat-change-monitor.v1'}
    assert sdk.project_vector_diagnostic(item, identity, ['cold-uuid']) == item
