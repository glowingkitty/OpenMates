"""Provider attribution, global availability stop and finite-oracle safeguards."""
# contract-test-file: infrastructure

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from backend.scripts import benchmark_postprocessing_models as benchmark


TOOL = {'type': 'function', 'function': {
    'name': 'generate_suggestions_and_metadata', 'description': 'Full production instructions stay intact.',
    'parameters': {'type': 'object', 'properties': {'chat_summary': {'type': 'string'}}},
}}


def native_response(arm, arguments=None):
    arguments = arguments or {'chat_summary': 'Zoë sucht blaue Boxen unter 47 Euro.',
                              'updated_chat_title': 'Blaue Boxen für Zoë'}
    if arm == 'mercury-low':
        return {'model': 'mercury-3', 'usage': {'prompt_tokens': 100, 'completion_tokens': 50},
                'choices': [{'finish_reason': 'stop', 'message': {'tool_calls': [{'function': {
                    'name': TOOL['function']['name'], 'arguments': json.dumps(arguments),
                }}]}}]}
    return {'modelVersion': 'gemini-3.5-flash-lite',
            'usageMetadata': {'promptTokenCount': 100, 'candidatesTokenCount': 50},
            'candidates': [{'finishReason': 'STOP', 'content': {'parts': [{'functionCall': {
                'name': TOOL['function']['name'], 'args': arguments,
            }}]}}]}


@pytest.mark.parametrize('arm', benchmark.ARMS)
def test_observed_identity_and_completed_tool_required(arm):
    raw = native_response(arm)
    args, telemetry = benchmark.parse_response(raw, arm, TOOL['function']['name'])
    assert args['chat_summary'].startswith('Zoë')
    assert telemetry['observed_model'] == benchmark.ARMS[arm][1]
    assert not telemetry['usage_missing']
    identity_field = 'model' if arm == 'mercury-low' else 'modelVersion'
    raw[identity_field] = 'unrelated-fallback-model'
    with pytest.raises(ValueError, match='observed model'):
        benchmark.parse_response(raw, arm, TOOL['function']['name'])
    del raw[identity_field]
    with pytest.raises(ValueError, match='observed model'):
        benchmark.parse_response(raw, arm, TOOL['function']['name'])


@pytest.mark.parametrize('arm', benchmark.ARMS)
def test_truncated_or_wrong_tool_outputs_do_not_become_quality_passes(arm):
    raw = native_response(arm)
    if arm == 'mercury-low':
        raw['choices'][0]['finish_reason'] = 'length'
    else:
        raw['candidates'][0]['finishReason'] = 'MAX_TOKENS'
    with pytest.raises(ValueError, match='Incomplete'):
        benchmark.parse_response(raw, arm, TOOL['function']['name'])
    with pytest.raises(ValueError, match='sole postprocessing tool'):
        benchmark.parse_response(native_response(arm), arm, 'wrong-tool')


def test_oracle_rejects_wrong_facts_language_limits_and_invented_tasks():
    suggestions = ['Vergleiche neue blaue Boxen', 'Erkläre die verschiedenen Materialien'] * 3
    good = {'chat_summary': 'Zoë sucht neue blaue Boxen unter 47 Euro.', 'updated_chat_title': 'Blaue Boxen für Zoë',
            'follow_up_request_suggestions': suggestions, 'new_chat_request_suggestions': suggestions,
            'task_proposals': [], 'task_update_proposals': []}
    assert benchmark.assess(benchmark.CASES[0], good) == []
    bad = {**good, 'chat_summary': 'Zoë wants green boxes under 99 euros. ' * 4,
           'updated_chat_title': 'Too many words in this title are not acceptable here',
           'task_proposals': [{'title': 'Buy boxes without approval'}],
           'task_update_proposals': [{'task_id': 'nonexistent'}]}
    issues = benchmark.assess(benchmark.CASES[0], bad)
    assert {'summary_word_limit', 'title_word_limit', 'german_summary_unconfirmed',
            'fabricated_task', 'fabricated_task_update'} <= set(issues)
    assert any(issue.startswith('missing_summary_fact:') for issue in issues)


def fake_postprocessor():
    """Protocol stand-in only; production integration separately needs API dependencies."""
    module = SimpleNamespace(call_preprocessing_llm=None, _postprocessing_decisions_with_jev=None,
                             POSTPROCESSING_MODEL_ID='unchanged', datetime=None)

    async def handle(**kwargs):
        assert kwargs['allow_model_fallbacks'] is False
        assert kwargs['translate_ui_metadata'] is False
        assert kwargs['cache_service'] is None
        assert await module._postprocessing_decisions_with_jev() == benchmark.FROZEN_JEV
        result = await module.call_preprocessing_llm(
            message_history=[{'role': 'system', 'content': 'Production system context'},
                             {'role': 'user', 'content': kwargs['user_message']}],
            tool_definition=TOOL, fallback_models=[],
        )
        return SimpleNamespace(model_dump=lambda: result.arguments)

    module.handle_postprocessing = handle
    return module


@pytest.mark.asyncio
async def test_first_429_stops_all_cases_arms_repeats_and_saves_private_partial(tmp_path):
    requests = []

    async def rate_limited(request):
        requests.append(request)
        return httpx.Response(429, json={'error': 'synthetic rate limit'})

    output = tmp_path / 'partial.json'
    manager = SimpleNamespace(get_secret=AsyncMock(return_value='private-test-key'))
    async with httpx.AsyncClient(transport=httpx.MockTransport(rate_limited)) as client:
        async def runner(case, arm):
            return await benchmark.run_case(case, arm, manager=manager, client=client,
                                            base={}, postprocessor=fake_postprocessor())
        report = await benchmark.execute(arms=list(benchmark.ARMS), cases=list(benchmark.CASES), repeats=2,
                                         output=output, revision='synthetic', runner=runner, base_hash='sha')
    assert len(requests) == 1
    assert report['planned_results'] == 40
    assert report['skipped_results'] == 39
    assert report['partial'] and report['stop_reason'] == 'http_429'
    assert report['results'][0]['quality_evaluated'] is False
    assert 'issues' not in report['results'][0]
    assert report['results'][0]['complete_latency_seconds'] >= 0
    assert json.loads(output.read_text()) == json.loads(json.dumps(report))
    assert output.stat().st_mode & 0o777 == 0o600
    assert 'private-test-key' not in output.read_text()


@pytest.mark.asyncio
@pytest.mark.parametrize('arm', benchmark.ARMS)
async def test_native_boundary_retains_full_tool_raw_output_usage_and_observed_model(arm):
    captured = []
    async def respond(request):
        captured.append(request)
        return httpx.Response(200, json=native_response(arm))
    module = fake_postprocessor()
    manager = SimpleNamespace(get_secret=AsyncMock(return_value='private-test-key'))
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        row = await benchmark.run_case(benchmark.CASES[0], arm, manager=manager, client=client,
                                       base={}, postprocessor=module)
    assert len(captured) == 1
    assert row['raw_response'] == native_response(arm)
    assert row['usage_telemetry']['observed_model'] == benchmark.ARMS[arm][1]
    assert row['usage_telemetry']['raw_usage']
    assert module.POSTPROCESSING_MODEL_ID == 'unchanged'
    body = json.loads(captured[0].content)
    function = body['tools'][0]['function'] if arm == 'mercury-low' else body['tools'][0]['functionDeclarations'][0]
    assert function == TOOL['function']
    assert 'private-test-key' not in json.dumps(row)
    if arm == 'mercury-low':
        assert captured[0].url.host == 'api.inceptionlabs.ai'
        assert body['reasoning_effort'] == 'low'
    else:
        assert captured[0].url.host == 'generativelanguage.googleapis.com'


@pytest.mark.asyncio
async def test_real_production_prompt_and_normalizer_with_synthetic_native_response():
    # Do not install/stub missing backend modules merely to make this integration pass.
    pytest.importorskip('dotenv', reason='Real postprocessor requires API container dependencies')
    pytest.importorskip('redis.asyncio', reason='Real postprocessor requires API container dependencies')
    from pathlib import Path
    import yaml
    from backend.apps.ai.processing import postprocessor

    raw_args = {'chat_summary': 'Zoë sucht blaue Boxen unter 47 Euro.',
                'updated_chat_title': 'Blaue Boxen für Zoë',
                'chat_tags': ['Boxen', 'Boxen'], 'share_cta_text': 'Finde blaue Boxen für Zoë',
                'follow_up_app_skill_suggestions': ['Suche blaue Boxen für Zoë'] * 3,
                'follow_up_general_suggestions': ['Erkläre die Vorteile neuer Boxen'] * 3,
                'new_chat_app_skill_suggestions': ['Suche neue Boxen für Zoë'] * 3,
                'new_chat_general_suggestions': ['Vergleiche die Vorteile neuer Boxen'] * 3,
                'daily_inspiration_topic_suggestions': ['Storage', 'Materials', 'Shopping']}
    base_path = Path(benchmark.__file__).resolve().parents[1] / 'apps/ai/base_instructions.yml'
    base = yaml.safe_load(base_path.read_text())
    async def respond(_request):
        return httpx.Response(200, json=native_response('mercury-low', raw_args))
    manager = SimpleNamespace(get_secret=AsyncMock(return_value='private-test-key'))
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        row = await benchmark.run_case(benchmark.CASES[0], 'mercury-low', manager=manager, client=client,
                                       base=base, postprocessor=postprocessor)
    tool = row['request']['body']['tools'][0]['function']
    assert tool['description'] == base['postprocess_response_tool']['function']['description']
    assert 'harmful_response' not in tool['parameters']['properties']
    assert 'top_recommended_apps_for_user' not in tool['parameters']['properties']
    assert row['output']['chat_tags'] == ['Boxen']
    assert row['output']['top_recommended_apps_for_user'] == ['web']
