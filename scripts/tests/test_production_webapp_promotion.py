"""Production gate ordering, identity fencing, and rollback contracts (no external writes)."""
# contract-test: tooling
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from promote_production_webapp import promote
from verify_production_webapp import validate_url


class FakeVercel:
    project = 'project'

    def __init__(self, automatic=False):
        self.automatic = automatic
        self.live = 'previous'
        self.writes = []

    def get(self, path):
        if path.startswith('/v9/projects/'):
            return {'autoAssignCustomDomains': self.automatic}
        return {'projectId': self.project, 'target': 'production', 'readyState': 'READY',
                'url': 'open-mates-webapp-reviewed.vercel.app'}

    def current(self):
        return self.live

    def alias(self, deployment):
        self.writes.append(deployment)
        self.live = deployment


# contract-test: tooling
def test_browser_checks_surround_the_only_promotion(tmp_path):
    api = FakeVercel()
    calls = []

    def check(url, output, version):
        calls.append((url, api.current(), version))
        return {'result': 'passed'}

    result = promote(api, 'candidate', 'version', tmp_path / 'proof', check)
    assert result['result'] == 'passed'
    assert api.writes == ['candidate']
    assert calls == [('https://open-mates-webapp-reviewed.vercel.app', 'previous', 'version'),
                     ('https://app.openmates.org', 'candidate', 'version')]


# contract-test: tooling
def test_failed_candidate_never_changes_production(tmp_path):
    api = FakeVercel()
    with pytest.raises(RuntimeError, match='Candidate failed'):
        promote(api, 'candidate', 'version', tmp_path / 'proof', lambda *args: {'result': 'failed'})
    assert api.writes == []


# contract-test: tooling
def test_post_promotion_failure_restores_previous_deployment(tmp_path):
    api = FakeVercel()
    checks = iter([{'result': 'passed'}, {'result': 'failed'}])
    with pytest.raises(RuntimeError, match='Live production'):
        promote(api, 'candidate', 'version', tmp_path / 'proof', lambda *args: next(checks))
    assert api.writes == ['candidate', 'previous']
    receipt = json.loads((tmp_path / 'proof/receipt.json').read_text())
    assert receipt['result'] == 'failed' and receipt['rollback'] == 'restored'


# contract-test: tooling
def test_lost_alias_response_is_reconciled_and_restored(tmp_path):
    class LostResponse(FakeVercel):
        def alias(self, deployment):
            super().alias(deployment)
            if deployment == 'candidate':
                raise TimeoutError('response lost after the alias changed')

    api = LostResponse()
    with pytest.raises(TimeoutError):
        promote(api, 'candidate', 'version', tmp_path / 'proof', lambda *args: {'result': 'passed'})
    assert api.writes == ['candidate', 'previous'] and api.current() == 'previous'


# contract-test: tooling
def test_automatic_alias_assignment_blocks_the_release(tmp_path):
    api = FakeVercel(automatic=True)
    with pytest.raises(RuntimeError, match='Disable automatic'):
        promote(api, 'candidate', 'version', tmp_path / 'proof', lambda *args: pytest.fail('must not check yet'))
    assert api.writes == []


# contract-test: tooling
def test_concurrent_release_is_never_overwritten(tmp_path):
    api = FakeVercel()

    def check(*args):
        api.live = 'another-release'
        return {'result': 'passed'}

    with pytest.raises(RuntimeError, match='Production changed'):
        promote(api, 'candidate', 'version', tmp_path / 'proof', check)
    assert api.writes == []


# contract-test: tooling
def test_failed_live_check_does_not_roll_back_another_operators_release(tmp_path):
    api = FakeVercel()

    def check(url, *args):
        if url == 'https://app.openmates.org':
            api.live = 'another-release'
            return {'result': 'failed'}
        return {'result': 'passed'}

    with pytest.raises(RuntimeError, match='Live production'):
        promote(api, 'candidate', 'version', tmp_path / 'proof', check)
    assert api.writes == ['candidate'] and api.current() == 'another-release'


# contract-test: tooling
@pytest.mark.parametrize('url', ['https://evil.example', 'http://app.openmates.org',
                                  'https://app.openmates.org/anything',
                                  'https://open-mates-webapp-abc.vercel.app.evil.example'])
def test_browser_gate_rejects_unrelated_origins(url):
    with pytest.raises(ValueError):
        validate_url(url)
