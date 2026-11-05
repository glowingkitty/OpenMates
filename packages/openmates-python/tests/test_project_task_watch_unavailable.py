"""PRIVATE UNRUN DRAFT; run against installed integrated public package."""
import pytest
from openmates import OpenMates,OpenMatesProjectTaskWatchUnavailableError
# contract-test: supporting surface=sdks.pip assertions=sdk.surface.semantic-parity
def test_api_key_watch_unavailable_before_transport(monkeypatch):
    calls=[]
    def reject(*args,**kwargs):
        calls.append(True)
        raise AssertionError('unexpected transport')
    for method in ('get','post','patch','put','delete','request'):
        monkeypatch.setattr('requests.'+method,reject)
    client=OpenMates(api_key='synthetic-bearer.synthetic-secret',api_url='https://example.invalid',device_id='synthetic-device')
    with pytest.raises(OpenMatesProjectTaskWatchUnavailableError) as caught:
        client.projects.watch_tasks('project',source_id='source',filters={'personal':True})
    assert caught.value.code=='project_task_watch_unavailable'
    assert caught.value.reason=='PROJECT_TASK_WATCH_REQUIRES_COOKIE_SESSION'
    assert not calls
