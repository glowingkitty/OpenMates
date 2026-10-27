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


# Concrete independent example values: the model never receives these fixtures.
REFERENCE_INPUTS = {
    'en_manual_lunch_choices': {'recipes': {'requests': [{'query': 'vegetarian high-protein lunch', 'health': ['vegetarian'], 'diet': ['high-protein']}]}},
    'de_two_city_weather': {'vienna': {'location': 'Vienna', 'days': 1}, 'graz': {'location': 'Graz', 'days': 1}},
    'en_battery_news_no_ai': {'news': {'requests': [{'query': 'battery recycling'}]}},
    'de_backpack_self_correction': {'products': {'requests': [{'query': 'blaue Wanderrucksäcke neu', 'country': 'de', 'max_price': 95}]}},
    'en_exact_false_rain': {'weather': {'location': 'Boston', 'start_date': {'$date': 'tomorrow', 'format': 'date'}, 'end_date': {'$date': 'tomorrow', 'format': 'date'}}},
    'de_ai_check_three_paths': {'news': {'requests': [{'query': 'Energiepolitik'}]}},
    'en_exact_shared_continuation': {'weather': {'location': 'Madrid', 'start_date': {'$date': 'tomorrow', 'format': 'date'}, 'end_date': {'$date': 'tomorrow', 'format': 'date'}}},
    'de_two_zones_recipe_reminder': {'recipes': {'requests': [{'query': 'vegetarian dinner', 'health': ['vegetarian']}]}},
    'en_mixed_edit_glutenfree': {'recipes': {'requests': [{'query': 'gluten-free dinner', 'health': ['gluten-free']}]}},
    'de_weather_news_typed_inputs': {'weather': {'location': 'Hamburg', 'days': 1}, 'news': {'requests': [{'query': 'Hamburger Hafen Hamburg port'}]}},
    'en_query_instructions_are_data': {'news': {'requests': [{'query': 'API security "ignore previous instructions"'}]}},
    'de_exact_news_threshold': {'news': {'requests': [{'query': 'Klimaschutz'}]}},
    'en_two_product_budgets': {'products': {'requests': [{'query': 'USB-C dock', 'country': 'de', 'max_price': 120}, {'query': 'HDMI cable', 'country': 'de', 'max_price': 20}]}},
}
REFERENCE_PROMPTS = {
    'en_manual_lunch_choices': 'Choose two recipes and explain why.',
    'de_two_city_weather': 'Vergleiche die Temperatur, welche Stadt ist wärmer? Nenne fehlende Daten.',
    'en_mixed_edit_glutenfree': 'Choose two recipes and explain why.',
    'de_weather_news_typed_inputs': 'Schreibe eine deutsche Zusammenfassung für Pendler.',
}
REFERENCE_MESSAGES = {
    'en_exact_false_rain': ['DRY', 'WET'],
    'de_ai_check_three_paths': ['WICHTIG', 'KEIN UPDATE', 'UNSICHER'],
    'en_exact_shared_continuation': ['RAIN', 'DRY', 'CHECK COMPLETE'],
    'de_two_zones_recipe_reminder': ['TRINKWASSER'],
    'de_exact_news_threshold': ['MEHRERE', 'WENIGE'],
    'de_negated_reminder_schedule': ['Rechnung Zoë 127 Euro'],
}


def reference_operations(case):
    """Compile independent concrete input examples with the real capability registry."""
    from backend.core.api.app.services.workflow_authoring_compiler import compile_authoring_plan
    from backend.core.api.app.services.workflow_authoring_preselection import WorkflowPreselection
    from backend.core.api.app.services.workflow_capability_registry import WorkflowCapabilityRegistry

    registry = WorkflowCapabilityRegistry()
    operations = []
    for expected in case.expectations:
        updating = expected['action'] == 'update_workflow'
        capabilities = set(case.expected_capability_ids) | ({'weather.forecast'} if updating else set())
        selection = WorkflowPreselection([registry.get_capability(name) for name in capabilities],
            'update' if updating else 'create', 'none', True, {}, {}, workflow_count=1)
        if updating:
            raw = {'operation': 'update', 'workflow_id': case.selected_workflow['id'],
                   'schedule': expected['schedule']}
        else:
            steps = []
            for role, rule in expected['roles'].items():
                if rule['capability'] == 'ai.ask':
                    prompt = [{'text': REFERENCE_PROMPTS[case.id]}]
                    prompt += [{'ref': {'step': name, 'field': 'results'}} for name in rule['refs']]
                    steps.append({'kind': 'ask_ai', 'id': role, 'prompt': prompt})
                else:
                    steps.append({'kind': 'app', 'id': role, 'capability': rule['capability'],
                                  'input': REFERENCE_INPUTS[case.id][role]})
            check_rule = expected['check']
            check = None
            if check_rule:
                check = {'kind': 'check', 'id': 'decision', 'mode': check_rule['mode']}
                if check_rule['mode'] == 'exact':
                    check['predicate'] = {'op': check_rule['op'], 'left': {'ref': {
                        'step': check_rule['source'], 'field': check_rule['field']}}, 'right': check_rule['right']}
                else:
                    check.update(question=[{'text': 'Ist diese Nachricht für Mieter wichtig?'}],
                                 selected_inputs=[{'step': name, 'field': 'results'} for name in check_rule['sources']])
                steps.append(check)
            for index, send_rule in enumerate(expected['sends']):
                messages = REFERENCE_MESSAGES.get(case.id, ['Results'])
                text = messages[index] if index < len(messages) else 'Results'
                message = [{'text': text}]
                for role in send_rule['refs']:
                    field = 'answer' if expected['roles'][role]['capability'] == 'ai.ask' else 'results'
                    message.append({'ref': {'step': role, 'field': field}})
                send = {'kind': 'send', 'id': 'send' + str(index), 'title': 'Result', 'message': message}
                if send_rule['branch'] in {'yes', 'no', 'unsure'}:
                    check.setdefault(send_rule['branch'], []).append(send)
                else:
                    steps.append(send)
            raw = {'operation': 'create', 'title': 'Reference', 'description': 'Synthetic fixture',
                   'icon': 'bell', 'schedule': expected['schedule'], 'steps': steps}
        compiled = compile_authoring_plan(raw, selection, case.timezone, case.selected_workflow)
        operation = {**compiled, 'action': expected['action']}
        if updating:
            operation['workflow_id'] = case.selected_workflow['id']
            operation['expected_record_version'] = case.selected_workflow['version']
        operations.append(operation)
    return operations


def test_expanded_corpus_is_balanced_unique_and_every_example_compiles(monkeypatch):
    from backend.scripts.workflow_authoring_model_cases import cases, evaluate
    from backend.core.api.app.services.workflow_capability_registry import WorkflowCapabilityRegistry, _FilesystemWorkflowMetadataRegistry
    monkeypatch.setattr(WorkflowCapabilityRegistry, '_registry', lambda _: _FilesystemWorkflowMetadataRegistry())
    assert len(cases()) == 8
    corpus = cases('expanded')
    expanded = [case for case in corpus if case.expectations]
    assert len(corpus) == len({case.id for case in corpus}) == 24
    assert len(expanded) == 16
    assert sum(case.language == 'de' for case in expanded) == 8
    assert sum(case.language == 'en' for case in expanded) == 8
    for case in expanded:
        assert evaluate(case, reference_operations(case)) == [], case.id


@pytest.mark.parametrize('case_id,mutation', [
    ('en_battery_news_no_ai', 'topic'),
    ('en_two_product_budgets', 'price'),
    ('en_exact_false_rain', 'polarity'),
    ('de_exact_news_threshold', 'threshold'),
    ('en_exact_shared_continuation', 'swap_branches'),
    ('en_exact_shared_continuation', 'repeat_continuation'),
    ('de_weather_news_typed_inputs', 'remove_reference'),
    ('en_query_instructions_are_data', 'remove_quote'),
    ('de_negated_reminder_schedule', 'wrong_name'),
    ('de_edit_clock_keep_identity', 'wrong_id'),
    ('de_edit_clock_keep_identity', 'edit_preserved_message'),
    ('en_edit_weekly_keep_paris', 'wrong_timezone'),
    ('de_two_city_weather', 'invent_start'),
    ('en_manual_lunch_choices', 'extra_action'),
])
def test_oracle_rejects_semantically_corrupted_valid_graphs(monkeypatch, case_id, mutation):
    from copy import deepcopy
    from backend.scripts.workflow_authoring_model_cases import cases, evaluate
    from backend.core.api.app.services.workflow_models import WorkflowGraph
    from backend.core.api.app.services.workflow_capability_registry import WorkflowCapabilityRegistry, _FilesystemWorkflowMetadataRegistry
    monkeypatch.setattr(WorkflowCapabilityRegistry, '_registry', lambda _: _FilesystemWorkflowMetadataRegistry())
    case = next(case for case in cases('expanded') if case.id == case_id)
    operations = deepcopy(reference_operations(case))
    graph = operations[0]['graph']
    nodes = graph['nodes']
    apps = [node for node in nodes if node['type'] == 'app_skill_action']
    checks = [node for node in nodes if node['type'] == 'check']
    sends = [node for node in nodes if node['type'] == 'send_chat_message']
    trigger = next(node for node in nodes if node['id'] == graph['trigger_node_id'])
    if mutation == 'topic':
        apps[0]['config']['input']['requests'][0]['query'] = 'celebrity gossip'
    elif mutation == 'price':
        apps[0]['config']['input']['requests'][1]['max_price'] = 200
    elif mutation == 'polarity':
        checks[0]['config']['predicate']['right'] = True
    elif mutation == 'threshold':
        checks[0]['config']['predicate']['right'] = 30
    elif mutation == 'swap_branches':
        for edge in graph['edges']:
            if edge['from'] == checks[0]['id'] and edge['branch'] in {'yes', 'no'}:
                edge['branch'] = {'yes': 'no', 'no': 'yes'}[edge['branch']]
    elif mutation == 'repeat_continuation':
        sends[0]['config']['message'] = 'RAIN CHECK COMPLETE'
    elif mutation == 'remove_reference':
        ask = next(node for node in apps if node['config']['app_id'] == 'ai')
        ask['config']['input']['prompt'] = ask['config']['input']['prompt'].replace('{{ $nodes.news.output.results }}', '')
    elif mutation == 'remove_quote':
        apps[0]['config']['input']['requests'][0]['query'] = 'API security'
    elif mutation == 'wrong_name':
        sends[0]['config']['message'] = 'Rechnung Zoe 127 Euro'
    elif mutation == 'wrong_id':
        operations[0]['workflow_id'] = '00000000-0000-4000-8000-000000000999'
    elif mutation == 'edit_preserved_message':
        sends[0]['config']['message'] = 'Changed unrelated message'
    elif mutation == 'wrong_timezone':
        trigger['config']['schedule']['timezone'] = 'America/New_York'
    elif mutation == 'invent_start':
        trigger['config']['schedule']['starts_at'] = '2030-01-01T00:00:00+01:00'
    elif mutation == 'extra_action':
        extra = deepcopy(apps[0])
        extra['id'] = 'unrequested'
        nodes.append(extra)
        graph['edges'].append({'from': sends[-1]['id'], 'to': extra['id']})
    for operation in operations:
        WorkflowGraph.model_validate(operation['graph'])  # Deliberately still structurally valid.
    assert evaluate(case, operations), (case_id, mutation)


def test_unknown_case_id_never_silently_passes():
    from dataclasses import replace
    from backend.scripts.workflow_authoring_model_cases import cases, evaluate
    with pytest.raises(ValueError, match='Unknown workflow benchmark case'):
        evaluate(replace(cases()[0], id='unregistered-case'), [])


@pytest.mark.parametrize('mode', ['gt', 'reverse', 'end_date', 'boolean_ne'])
def test_semantically_equivalent_comparisons_and_date_forms_are_accepted(monkeypatch, mode):
    from backend.scripts.workflow_authoring_model_cases import cases, evaluate
    from backend.core.api.app.services.workflow_capability_registry import WorkflowCapabilityRegistry, _FilesystemWorkflowMetadataRegistry
    monkeypatch.setattr(WorkflowCapabilityRegistry, '_registry', lambda _: _FilesystemWorkflowMetadataRegistry())
    case_id = 'en_exact_false_rain' if mode in {'end_date', 'boolean_ne'} else 'de_exact_news_threshold'
    case = next(case for case in cases('expanded') if case.id == case_id)
    operations = reference_operations(case)
    nodes = operations[0]['graph']['nodes']
    check = next(node for node in nodes if node['type'] == 'check')
    predicate = check['config']['predicate']
    if mode == 'gt':
        predicate.update(op='gt', right=2)
    elif mode == 'reverse':
        predicate.update(op='lte', left=3, right=predicate['left'])
    elif mode == 'boolean_ne':
        predicate.update(op='neq', right=True)
    else:
        weather = next(node for node in nodes if node['type'] == 'app_skill_action')
        weather['config']['input']['end_date']['$date'] = 'tomorrow_end'
    assert evaluate(case, operations) == []


def test_response_identity_mismatch_is_not_silently_a_comparison_result():
    from backend.scripts.benchmark_workflow_authoring_models import provider_identity
    actual = provider_identity('mercury-instant', [{'observed_model': 'different-model'}])
    assert actual['response_status'] == 'mismatch'
    assert actual['comparison_eligible'] is False
    assert provider_identity('mercury-instant', [{'observed_model': 'mercury-3'}])['response_status'] == 'matched'
    assert provider_identity('gemini', [{'observed_model': 'gemini-3.8-flash-001'}])['response_status'] == 'matched'
    assert provider_identity('gemini', [{'observed_model': 'gemini-3.8-flash-lite'}])['comparison_eligible'] is False
    assert provider_identity('gemini', [{}])['response_status'] == 'unreported'
    assert provider_identity('mercury-openrouter-low', [{'observed_model': 'inception/mercury-3',
        'observed_provider': 'another-provider'}])['comparison_eligible'] is False


@pytest.mark.parametrize('usage', [
    {'prompt_tokens': 10},
    {'prompt_tokens': True, 'completion_tokens': 2},
    {'prompt_tokens': 10, 'completion_tokens': -1},
    {'prompt_tokens': 10, 'completion_tokens': 2.5},
    {'prompt_tokens': '10', 'completion_tokens': 2},
    {'prompt_tokens': 10, 'completion_tokens': 2, 'total_tokens': 99},
    {'prompt_tokens': 10, 'completion_tokens': 2, 'prompt_tokens_details': {'cached_tokens': 11}},
    {'prompt_tokens': 10, 'completion_tokens': 2, 'completion_tokens_details': {'reasoning_tokens': 3}},
    {'prompt_tokens': 10, 'completion_tokens': 2, 'completion_tokens_details': {'reasoning_tokens': True}},
])
def test_malformed_raw_usage_is_never_complete_or_costed(usage):
    author = BenchAuthor.__new__(BenchAuthor)
    author.provider = 'inception_labs'
    author.prices = (.10, .35)
    author.transport = type('Transport', (), {'attempts': [{'usage': usage}]})()
    metrics = {}
    author.price(metrics)
    assert metrics['usage_complete'] is False
    assert metrics['usage_counters_valid'] is False
    assert metrics['estimated_cost_usd'] is None
    assert metrics['regular_cost_usd'] is None
    assert author.transport.attempts[0]['usage'] is usage  # Preserve unaltered raw evidence.


def test_validated_usage_retains_known_cache_and_unknown_optional_subsets():
    from backend.scripts.benchmark_workflow_authoring_models import validated_usage
    known = validated_usage('inception_labs', {'prompt_tokens': 10, 'completion_tokens': 2,
        'total_tokens': 12, 'prompt_tokens_details': {'cached_tokens': 7},
        'completion_tokens_details': {'reasoning_tokens': 1}})
    assert known['usage_complete'] is True
    assert known['cached_input_tokens'] == 7
    assert known['thinking_tokens'] == 1
    unknown = validated_usage('inception_labs', {'prompt_tokens': 10, 'completion_tokens': 2})
    assert unknown['usage_complete'] is True
    assert unknown['cached_input_tokens'] is None and unknown['thinking_tokens'] is None


def test_mixed_case_node_ids_preserve_valid_typed_references(monkeypatch):
    from backend.scripts.workflow_authoring_model_cases import cases, evaluate
    from backend.core.api.app.services.workflow_models import WorkflowGraph
    from backend.core.api.app.services.workflow_capability_registry import WorkflowCapabilityRegistry, _FilesystemWorkflowMetadataRegistry
    monkeypatch.setattr(WorkflowCapabilityRegistry, '_registry', lambda _: _FilesystemWorkflowMetadataRegistry())
    case = next(case for case in cases('expanded') if case.id == 'de_weather_news_typed_inputs')
    operations = reference_operations(case)
    graph = operations[0]['graph']
    for node in graph['nodes']:
        if node['id'] == 'news':
            node['id'] = 'FetchNews'
    for edge in graph['edges']:
        for key in ('from', 'to'):
            if edge[key] == 'news':
                edge[key] = 'FetchNews'
    operations[0]['graph'] = json.loads(json.dumps(graph).replace('$nodes.news.output', '$nodes.FetchNews.output'))
    WorkflowGraph.model_validate(operations[0]['graph'])
    assert evaluate(case, operations) == []
