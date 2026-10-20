"""Evaluation transport integrity; no paid inference or live credentials."""
# contract-test-file: infrastructure

import json
from unittest.mock import AsyncMock

import httpx
import pytest

from backend.scripts.benchmark_workflow_authoring_models import (
    BenchAuthor, GoogleRecordingTransport, selected_provider_keys,
    write_report,
)


@pytest.mark.asyncio
async def test_selected_keys_excludes_unrelated_and_google_parser_credentials():
    manager = type('Secrets', (), {'get_secret': AsyncMock(return_value='fake')})()
    assert await selected_provider_keys(manager, ['gemini', 'mercury-low', 'mercury-instant']) == {'inception_labs': 'fake'}
    manager.get_secret.assert_awaited_once_with(
        secret_path='kv/data/providers/inception_labs', secret_key='api_key')


@pytest.mark.asyncio
@pytest.mark.parametrize('arm,reasoning', [('mercury-instant', 'instant'), ('mercury-low', 'low')])
async def test_mercury_preserves_native_prompt_schema_and_auth(arm, reasoning):
    captured = []
    def handler(request):
        captured.append(request)
        return httpx.Response(200, content=(
            'data: {"choices":[{"delta":{"reasoning_content":"private thought"}}]}\n\n'
            'data: {"choices":[{"delta":{"content":"{}"},"finish_reason":"stop"}]}\n\n'
            'data: {"choices":[],"usage":{"prompt_tokens":12,"completion_tokens":8,"completion_tokens_details":{"reasoning_tokens":3}}}\n\n'
            'data: [DONE]\n\n'))
    schema = {'type': 'object', 'properties': {'workflows': {'type': 'array'}}}
    body = {'generationConfig': {'responseJsonSchema': schema},
            'systemInstruction': {'parts': [{'text': 'native system'}]},
            'contents': [{'parts': [{'text': 'native user'}]}]}
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as upstream:
        manager = type('Secrets', (), {'get_secret': AsyncMock(side_effect=AssertionError('unrelated secret lookup'))})()
        author = BenchAuthor(manager, upstream, arm, 'fake-key', reasoning='medium')
        assert await author.delegate.secrets_manager.get_secret(secret_path='unused')
        async with author.client.stream('POST', 'https://unused.test', json=body) as response:
            mapped = await response.aread()
        metrics = {}
        author.price(metrics)
        assert metrics['first_content_ms'] is not None
        assert metrics['input_tokens'] == 12
        assert metrics['output_tokens'] == 8
        assert metrics['thinking_tokens'] == 3
        assert metrics['regular_cost_usd'] == round((12*.20 + 8*.70)/1_000_000, 8)
        assert b'private thought' not in mapped
        await author.close()
    payload = json.loads(captured[0].content)
    assert str(captured[0].url) == 'https://api.inceptionlabs.ai/v1/chat/completions'
    assert captured[0].headers['Authorization'] == 'Bearer fake-key'
    assert payload['messages'] == [{'role': 'system', 'content': 'native system'}, {'role': 'user', 'content': 'native user'}]
    assert payload['response_format']['json_schema']['schema'] == schema
    assert payload['reasoning_effort'] == reasoning
    assert payload['temperature'] == .5
    assert payload['stream_options'] == {'include_usage': True}


@pytest.mark.asyncio
async def test_google_observer_preserves_request_and_excludes_thought_ttft():
    async def handler(request):
        assert request.headers['x-goog-api-key'] == 'fake'
        assert request.content == b'{"native":true}'
        return httpx.Response(200, content=(
            'data: {"candidates":[{"content":{"parts":[{"thought":true,"text":"reason"}]}}]}\n\n'
            'data: {"usageMetadata":{"promptTokenCount":4}}\n\n'))
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as upstream:
        transport = GoogleRecordingTransport(upstream)
        async with httpx.AsyncClient(transport=transport) as client:
            response = await client.post('https://google.test', headers={'x-goog-api-key': 'fake'}, content=b'{"native":true}')
            assert b'reason' in response.content
        assert transport.attempts[0]['first_content_ms'] is None
        assert transport.attempts[0]['usage'] == {'promptTokenCount': 4}


def test_report_is_private_and_no_usage_never_claims_zero_cost(tmp_path):
    path = tmp_path / 'report.json'
    path.write_text('old')
    path.chmod(0o644)
    write_report(path, {'results': []})
    assert path.stat().st_mode & 0o777 == 0o600
    author = BenchAuthor.__new__(BenchAuthor)
    author.transport = type('Transport', (), {'attempts': []})()
    metrics = {}
    author.price(metrics)
    assert metrics == {'usage_complete': False, 'estimated_cost_usd': None}


@pytest.mark.asyncio
@pytest.mark.parametrize('effort', ['none', 'low'])
async def test_gateway_uses_native_schema_and_explicit_inception_route(effort):
    captured = []
    schema = {'type': 'object', 'properties': {'workflows': {'type': 'array'}}}
    def handler(request):
        captured.append(request)
        event = {'provider': 'Inception', 'model': 'inception/mercury-3',
                 'choices': [{'delta': {'content': '{}'}, 'finish_reason': 'stop'}],
                 'usage': {'prompt_tokens': 10, 'completion_tokens': 20, 'cost': .000006}}
        return httpx.Response(200, content='data: ' + json.dumps(event) + '\n\n')
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as upstream:
        author = BenchAuthor(None, upstream, 'mercury-openrouter-' + effort, 'fake')
        response = await author.client.post('https://parser-envelope.test', json={
            'generationConfig': {'responseJsonSchema': schema},
            'systemInstruction': {'parts': [{'text': 'native system'}]},
            'contents': [{'parts': [{'text': 'native user'}]}]})
        assert response.status_code == 200
        metrics = {}
        author.price(metrics)
        assert metrics['provider_reported_cost_usd'] == .000006
        assert metrics['observed_provider'] == 'Inception'
        assert metrics['observed_model'] == 'inception/mercury-3'
        assert metrics['transport'] == 'openrouter'
        await author.close()
    request = captured[0]
    body = json.loads(request.content)
    assert str(request.url) == 'https://openrouter.ai/api/v1/chat/completions'
    assert body['model'] == 'inception/mercury-3'
    assert body['reasoning'] == {'effort': effort}
    assert body['max_tokens'] == 8192
    assert 'max_completion_tokens' not in body and 'reasoning_effort' not in body
    assert body['provider'] == {'only': ['inception'], 'allow_fallbacks': False,
                                'require_parameters': True, 'data_collection': 'deny'}
    assert body['response_format']['json_schema']['schema'] == schema
    assert body['messages'][0]['content'] == 'native system'
    assert body['messages'][1]['content'] == 'native user'
    assert body['temperature'] == .5


@pytest.mark.asyncio
async def test_gateway_loads_only_selected_transport_credentials():
    manager = type('Secrets', (), {'get_secret': AsyncMock(return_value='fake')})()
    assert await selected_provider_keys(manager, ['gemini', 'mercury-openrouter-none',
                                                 'mercury-openrouter-low']) == {'openrouter': 'fake'}
    manager.get_secret.assert_awaited_once_with(
        secret_path='kv/data/providers/openrouter', secret_key='api_key')


@pytest.mark.asyncio
async def test_workflow_run_stops_before_planner_retry_and_saves_partial(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from backend.scripts import benchmark_workflow_authoring_models as benchmark
    from backend.core.api.app.services.workflow_authoring_preselection import WorkflowPreselection
    from backend.core.api.app.services.workflow_capability_registry import WorkflowCapabilityRegistry

    class Secrets:
        closed = False
        async def initialize(self):
            pass
        async def get_secret(self, **kwargs):
            return 'fake'
        async def aclose(self):
            self.closed = True

    registry = WorkflowCapabilityRegistry()
    selection = WorkflowPreselection(
        capabilities=[registry.get_capability('shopping.search_products')], operation='create',
        check_mode='none', chat_delivery=True, scores={}, metrics={}, workflow_count=1)
    class Selector:
        def __init__(self, **kwargs):
            self.registry = registry
        async def select(self, *args, **kwargs):
            return selection

    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(429, json={'error': {'message': 'capacity'}})
    real_client = httpx.AsyncClient
    secrets = Secrets()
    monkeypatch.setattr(benchmark, 'SecretsManager', lambda: secrets)
    monkeypatch.setattr(benchmark, 'WorkflowAuthoringPreselector', Selector)
    monkeypatch.setattr(benchmark.planner_module, 'WorkflowAuthoringPreselector', Selector)
    monkeypatch.setattr(benchmark.httpx, 'AsyncClient', lambda **kwargs: real_client(
        **kwargs, **({'transport': httpx.MockTransport(handler)} if 'transport' not in kwargs else {})))
    args = SimpleNamespace(revision='mock', cases=['headphones_filter', 'corrected_rain'], repeats=2,
        arms=['mercury-openrouter-none', 'mercury-openrouter-low'], selection_report=None,
        reasoning='low', profile='native', output=tmp_path / 'partial.json')
    await benchmark.run(args)
    report = json.loads(args.output.read_text())
    assert len(requests) == 1  # No production planner correction redispatch after 429.
    assert secrets.closed
    assert benchmark.planner_module.WorkflowAuthoringPreselector is Selector
    assert report['partial'] is True
    assert report['stop_reason'] == 'http_429'
    assert report['planned_results'] == 8
    assert len(report['results']) == 1
    assert report['skipped_results'] == 7
    row = report['results'][0]
    assert row['graph_valid'] is None and row['intent_match'] is None
    assert row['quality_evaluated'] is False
    assert len(row['provider_attempts']) == 1
    assert row['provider_attempts'][0]['http_status'] == 429
    assert report['availability_stop']['transport'] == 'openrouter'
    assert args.output.stat().st_mode & 0o777 == 0o600
