"""CMS load shedding must recover safe reads without replaying mutations."""
# contract-test-file: infrastructure
from unittest.mock import AsyncMock

import httpx
import pytest

from backend.core.api.app.services.directus.api_methods import _make_api_request
from backend.core.api.app.services.workflow_service import DirectusWorkflowRepository


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [502, 503, 504])
@pytest.mark.parametrize('method', ['GET', 'SEARCH', 'search'])
async def test_async_read_retries_transient_response_but_preserves_credentials(monkeypatch, status, method):
    requests = []
    def handle(request):
        requests.append(request)
        return httpx.Response(status if len(requests) == 1 else 200, json={'data': []})
    service = type('Service', (), {})()
    service.max_retries = 3
    service.ensure_auth_token = AsyncMock()
    sleep = AsyncMock()
    monkeypatch.setattr('backend.core.api.app.services.directus.api_methods.asyncio.sleep', sleep)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        service._client = client
        response = await _make_api_request(service, method, 'http://cms/items/example',
                                           headers={'Authorization': 'Bearer explicit', 'Cache-Control': 'no-store'})
    assert response.status_code == 200
    assert len(requests) == 2
    assert all(r.headers['Authorization'] == 'Bearer explicit' for r in requests)
    assert all(r.headers['Cache-Control'] == 'no-store' for r in requests)
    sleep.assert_awaited_once_with(2)
    service.ensure_auth_token.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('method,attempts', [('GET', 5), ('SEARCH', 5), ('search', 5), ('POST', 1), ('PATCH', 1), ('DELETE', 1)])
async def test_async_transient_responses_have_bounded_read_only_retries(monkeypatch, method, attempts):
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(503, json={'errors': [{'extensions': {'code': 'SERVICE_UNAVAILABLE'}}]})
    service = type('Service', (), {})()
    service.max_retries = 3
    sleep = AsyncMock()
    monkeypatch.setattr('backend.core.api.app.services.directus.api_methods.asyncio.sleep', sleep)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        service._client = client
        response = await _make_api_request(service, method, 'http://cms/items/example',
                                           headers={'Authorization': 'Bearer explicit'})
    assert response.status_code == 503
    assert len(calls) == attempts
    assert [call.args[0] for call in sleep.await_args_list] == ([2, 4, 8, 16] if attempts == 5 else [])


@pytest.mark.parametrize('failure', [503, 502, 504, httpx.ReadTimeout('')])
def test_workflow_owner_read_recovers_then_observes_fresh_data(monkeypatch, failure):
    requests = []
    def handle(request):
        requests.append(request)
        if len(requests) == 1:
            if isinstance(failure, Exception):
                raise failure
            return httpx.Response(failure, json={'errors': [{'extensions': {'code': 'SERVICE_UNAVAILABLE'}}]})
        return httpx.Response(200, json={'data': {'vault_key_id': 'owner-key'}})
    sleeps = []
    monkeypatch.setattr('backend.core.api.app.services.workflow_service.time.sleep', sleeps.append)
    repository = DirectusWorkflowRepository(base_url='http://cms', token='test-token')
    repository._client.close()
    headers = {'X-Request-Tag': 'caller'}
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        repository._client = client
        assert repository._request('GET', '/users/owner', headers=headers).json()['data']['vault_key_id'] == 'owner-key'
    assert len(requests) == 2
    assert sleeps == [2]
    assert all(r.headers['Cache-Control'] == 'no-store' for r in requests)
    assert headers == {'X-Request-Tag': 'caller'}


@pytest.mark.parametrize('method,status,attempts', [('GET', 503, 3), ('GET', 403, 1), ('GET', 500, 1), ('POST', 503, 1), ('PATCH', 503, 1), ('DELETE', 503, 1)])
def test_workflow_terminal_errors_remain_precise_and_mutations_not_replayed(monkeypatch, method, status, attempts):
    requests = []
    def handle(request):
        requests.append(request)
        return httpx.Response(status, json={'errors': [{'extensions': {'code': 'SERVICE_UNAVAILABLE'}}]})
    sleeps = []
    monkeypatch.setattr('backend.core.api.app.services.workflow_service.time.sleep', sleeps.append)
    repository = DirectusWorkflowRepository(base_url='http://cms', token='test-token')
    repository._client.close()
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        repository._client = client
        with pytest.raises(httpx.HTTPStatusError) as error:
            repository._request(method, '/workflow-runtime-transaction')
    assert error.value.response.status_code == status
    assert len(requests) == attempts
    assert sleeps == ([2, 4] if attempts == 3 else [])


@pytest.mark.parametrize('method', ['POST', 'PATCH', 'DELETE'])
def test_workflow_ambiguous_mutation_transport_error_is_never_replayed(monkeypatch, method):
    requests = []
    def handle(request):
        requests.append(request)
        raise httpx.ReadTimeout('')
    sleeps = []
    monkeypatch.setattr('backend.core.api.app.services.workflow_service.time.sleep', sleeps.append)
    repository = DirectusWorkflowRepository(base_url='http://cms', token='test-token')
    repository._client.close()
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        repository._client = client
        with pytest.raises(httpx.ReadTimeout):
            repository._request(method, '/workflow-runtime-transaction')
    assert len(requests) == 1
    assert sleeps == []


# contract-test: supporting surface=rest_api assertions=workflows.execution.lifecycle-visible,workflows.surface.semantic-parity
@pytest.mark.anyio
async def test_schedule_claim_survives_real_http_owner_read_load_shedding(monkeypatch):
    """Exercise httpx over TCP at the owner-read boundary after durable claim."""
    import json
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from backend.core.api.app.services.workflow_scheduler_service import WorkflowSchedulerService

    events = []
    class CMSHandler(BaseHTTPRequestHandler):
        reads = 0
        def do_GET(self):
            assert self.path == '/users/owner?fields=vault_key_id'
            assert self.headers['Cache-Control'] == 'no-store'
            type(self).reads += 1
            events.append('owner_read')
            status = 503 if type(self).reads == 1 else 200
            payload = ({'errors': [{'message': 'Service api is unavailable. Under pressure.',
                                   'extensions': {'code': 'SERVICE_UNAVAILABLE'}}]} if status == 503
                       else {'data': {'vault_key_id': 'owner-key'}})
            body = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        def log_message(self, *_args):
            pass
    class Runtime:
        async def execute(self, operation, data):
            events.append(operation)
            if operation == 'claim_due_trigger':
                return {'accepted': True, 'run_id': 'run', 'workflow_id': 'workflow', 'version_id': 'version',
                        'owner_user_id': 'owner', 'claim_token': 'fence', 'claim_generation': 1,
                        'encrypted_schedule_config_ref': 'schedule-blob'}
            if operation == 'start_claimed_run':
                assert data['claim_token'] == 'fence' and data['claim_generation'] == 1
                return {'started': True}
            assert operation == 'advance_claimed_trigger'
            assert data['claim_token'] == 'fence' and data['claim_generation'] == 1
            return {}
    sleeps = []
    monkeypatch.setattr('backend.core.api.app.services.workflow_service.time.sleep', sleeps.append)
    server = ThreadingHTTPServer(('127.0.0.1', 0), CMSHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    repository = DirectusWorkflowRepository(base_url=f'http://127.0.0.1:{server.server_port}', token='test-token')
    async def schedule(owner, blob):
        assert blob == 'schedule-blob'
        assert repository._request('GET', f'/users/{owner}', params={'fields': 'vault_key_id'}).json()['data']['vault_key_id'] == 'owner-key'
        return 1_800_000_000
    async def effect(*_args):
        events.append('effect')
    try:
        result = await WorkflowSchedulerService(Runtime()).execute_due_trigger('trigger', schedule, effect)
    finally:
        repository._client.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    assert result['accepted'] is True
    assert events == ['claim_due_trigger', 'owner_read', 'owner_read', 'start_claimed_run', 'advance_claimed_trigger', 'effect']
    assert sleeps == [2]
