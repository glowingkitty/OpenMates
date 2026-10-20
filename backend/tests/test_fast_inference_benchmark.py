"""Synthetic benchmark accounting and constraint-oracle regression coverage."""
# contract-test-file: infrastructure

import json
import subprocess
import sys

import httpx
import pytest

from backend.scripts.benchmark_fast_inference import CASES, assess, request_for, run_case, usage_cost
from backend.shared.providers.gemini_transcript_correction import build_transcript_correction_prompt


def test_shared_prompt_and_fixed_arms():
    for arm in ('mercury-instant', 'mercury-low'):
        url, body = request_for(CASES[0], arm)
        assert url == 'https://api.inceptionlabs.ai/v1/chat/completions'
        assert body['messages'][0]['content'] == build_transcript_correction_prompt('en')
        assert body['messages'][1]['content'] == f'Raw Transcript:\n"{CASES[0].text}"'
        assert body['max_completion_tokens'] == 8192
        assert body['tools'][0]['function']['parameters']['additionalProperties'] is False
        assert body['reasoning_effort'] == arm.removeprefix('mercury-')
        assert body['tool_choice']['function']['name'] == 'finalize_transcript'
        assert body['temperature'] == .5
    _, baseline = request_for(CASES[0], 'gemini-3.5')
    assert baseline['contents'][0]['parts'][0]['text'] == build_transcript_correction_prompt('en')
    assert 'thinkingConfig' not in baseline['generationConfig']
    _, candidate = request_for(CASES[0], 'gemini-3.8-low')
    assert candidate['generationConfig']['thinkingConfig']['thinkingLevel'] == 'low'


def test_oracle_catches_wrong_final_constraints_and_instruction_execution():
    case = CASES[0]
    good = {'title': 'Blue boxes for Lea', 'corrected_transcript':
            'Ask Lea to order blue storage boxes under 47 euros with delivery by Friday. Do not include used items.'}
    assert assess(case, good) == []
    bad = dict(good, corrected_transcript=good['corrected_transcript'].replace('blue', 'green'))
    assert any(issue.startswith('missing:') for issue in assess(case, bad))
    assert any(issue.startswith('forbidden:') for issue in assess(case, bad))
    injection = next(case for case in CASES if case.id == 'en_quoted_injection')
    assert assess(injection, {'title': 'BANANA42', 'corrected_transcript': 'BANANA42'})
    assert assess(injection, {'title': 'Note', 'corrected_transcript': '', 'extra': True}) == ['invalid_correction_shape']


def test_usage_distinguishes_missing_from_reported_and_counts_reasoning_once():
    assert usage_cost('mercury-low', None)['estimated_cost_usd'] is None
    partial = usage_cost('mercury-low', {'prompt_tokens': 12})
    assert partial['usage_complete'] is False
    assert partial['estimated_cost_usd'] is None
    costs = usage_cost('mercury-low', {'prompt_tokens': 100, 'completion_tokens': 200,
        'completion_tokens_details': {'reasoning_tokens': 50}})
    assert costs['output_tokens'] == 200
    assert costs['thinking_tokens'] == 50
    assert costs['estimated_cost_usd'] == .00008
    assert costs['regular_cost_usd'] == .00016
    google = usage_cost('gemini-3.8-low', {'promptTokenCount': 100, 'candidatesTokenCount': 150, 'thoughtsTokenCount': 50})
    assert google['output_tokens'] == 200


@pytest.mark.asyncio
@pytest.mark.parametrize('arm', ['mercury-instant', 'mercury-openrouter-none'])
async def test_tool_only_response_records_arguments_not_text_ttft(arm):
    output = {'title': 'Blue boxes for Lea', 'corrected_transcript':
              'Ask Lea to order blue boxes under 47 euros by Friday. Do not include used items.'}
    events = [
        {'choices': [{'delta': {'reasoning_content': 'reasoning is not text'}}]},
        {'choices': [{'delta': {'tool_calls': [{'index': 0, 'function': {
            'name': 'finalize_transcript', 'arguments': json.dumps(output)[:15]}}]}}]},
        {'choices': [{'delta': {'tool_calls': [{'index': 0, 'function': {
            'arguments': json.dumps(output)[15:]}}]}, 'finish_reason': 'tool_calls'}]},
        {'provider': 'Inception', 'model': 'inception/mercury-3', 'choices': [],
         'usage': {'prompt_tokens': 100, 'completion_tokens': 200, 'cost': .000051}},
    ]
    def handler(request):
        assert request.headers['Authorization'] == 'Bearer fake'
        return httpx.Response(200, content=''.join('data: '+json.dumps(event)+'\n\n' for event in events))
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        row = await run_case(client, 'fake', CASES[0], arm)
    assert row['task_pass'] is True
    assert row['ttft_ms'] is None
    assert row['first_tool_arguments_ms'] is not None
    assert row['output'] == output
    assert row['usage_complete'] is True
    if 'openrouter' in arm:
        assert row['provider_reported_cost_usd'] == .000051
        assert row['observed_provider'] == 'Inception'
        assert row['transport'] == 'openrouter'


@pytest.mark.asyncio
async def test_truncation_and_provider_error_never_pass_or_expose_body():
    def handler(request):
        return httpx.Response(400, content='private echoed fake key')
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        row = await run_case(client, 'fake', CASES[0], 'mercury-low')
    assert row['task_pass'] is False
    assert row['http_status'] == 400
    assert 'private echoed' not in json.dumps(row)
    assert row['estimated_cost_usd'] is None


@pytest.mark.asyncio
async def test_google_text_ttft_excludes_reasoning_and_usage_only_events():
    case = next(case for case in CASES if case.id == 'text_grounded_summary')
    text = ('Acme-42 hat 12 offene Aufgaben, davon 3 blockiert. Zoë prüft die blockierten '
            'Aufgaben bis Donnerstag um 18:45. Budget maximal 127 Euro. Keine Freigabe für einen Kauf.')
    events = [
        {'candidates': [{'content': {'parts': [{'thought': True, 'text': 'hidden reasoning'}]}}]},
        {'candidates': [{'content': {'parts': [{'text': text}]}, 'finishReason': 'STOP'}]},
        {'usageMetadata': {'promptTokenCount': 20, 'candidatesTokenCount': 30, 'thoughtsTokenCount': 10}},
    ]
    def handler(request):
        return httpx.Response(200, content=''.join('data: '+json.dumps(event)+'\n\n' for event in events))
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        row = await run_case(client, 'fake', case, 'gemini-3.8-low')
    assert row['task_pass'] is True
    assert row['output'] == text
    assert row['ttft_ms'] is not None
    assert row['first_tool_arguments_ms'] is None
    assert row['output_tokens'] == 40


def test_cli_denies_ci_even_with_opt_in():
    import os
    result = subprocess.run([sys.executable, '-m', 'backend.scripts.benchmark_fast_inference',
        '--allow-paid-dev-inference', '--revision', 'test'], env={**os.environ, 'CI': 'true'}, capture_output=True, text=True)
    assert result.returncode == 2
    assert 'never run in CI' in result.stderr


@pytest.mark.parametrize('effort', ['none', 'low'])
def test_gateway_correction_preserves_direct_prompt_tools_and_schema(effort):
    _, direct = request_for(CASES[0], 'mercury-low')
    url, gateway = request_for(CASES[0], 'mercury-openrouter-' + effort)
    assert url == 'https://openrouter.ai/api/v1/chat/completions'
    assert gateway['model'] == 'inception/mercury-3'
    assert gateway['max_tokens'] == direct['max_completion_tokens'] == 8192
    assert gateway['reasoning'] == {'effort': effort}
    assert 'reasoning_effort' not in gateway and 'max_completion_tokens' not in gateway
    assert gateway['provider'] == {'only': ['inception'], 'allow_fallbacks': False,
                                   'require_parameters': True, 'data_collection': 'deny'}
    for field in ('messages', 'tools', 'tool_choice', 'temperature', 'stream', 'stream_options'):
        assert gateway[field] == direct[field]
    costs = usage_cost('mercury-openrouter-' + effort,
                      {'prompt_tokens': 100, 'completion_tokens': 200, 'cost': .000051,
                       'completion_tokens_details': {'reasoning_tokens': 50}})
    assert costs['provider_reported_cost_usd'] == .000051
    assert costs['estimated_cost_usd'] == .00008
    assert costs['regular_cost_usd'] is None
