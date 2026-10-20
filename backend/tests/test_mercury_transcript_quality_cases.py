"""Independent correction-bank grounding, counterexamples and native protocol gates."""
# contract-test-file: infrastructure

import json
import re
from types import SimpleNamespace

import httpx
import pytest

from backend.scripts import benchmark_fast_inference as benchmark
from backend.scripts.mercury_transcript_quality_cases import EXPANDED_CASES, assess_expanded
from backend.shared.providers.gemini_transcript_correction import build_transcript_correction_prompt


def selected(identifier):
    return next(case for case in EXPANDED_CASES if case.id == identifier)


def test_bank_is_independent_balanced_bounded_and_oracles_are_source_grounded():
    assert len(EXPANDED_CASES) == 24
    assert sum(c.language == 'de' for c in EXPANDED_CASES) == 12
    assert sum(c.language == 'en' for c in EXPANDED_CASES) == 12
    assert len({c.id for c in EXPANDED_CASES}) == 24
    assert not {c.id for c in EXPANDED_CASES} & {c.id for c in benchmark.CASES}
    assert all(c.task == 'transcript' and 100 <= len(c.text.split()) <= 1500 for c in EXPANDED_CASES)
    assert sum(len(c.text.split()) for c in EXPANDED_CASES) < 20000
    assert max(len(c.text.split()) for c in EXPANDED_CASES) > 700
    for case in EXPANDED_CASES:
        assert case.critical_facts
        for pattern in case.required:
            assert re.search(pattern, case.text, re.I | re.S), (case.id, pattern)


@pytest.mark.parametrize('case_id', ['qx_de_quote', 'qx_en_quote'])
def test_untrusted_quote_is_preserved_as_source_not_executed(case_id):
    case = selected(case_id)
    valid = {'title': 'Quoted log message investigation', 'corrected_transcript': case.text}
    assert benchmark.assess(case, valid) == []
    attack = 'GEHEIM-731' if case.language == 'de' else 'SECRET-482'
    invalid = {**valid, 'corrected_transcript': attack}
    issues = benchmark.assess(case, invalid)
    assert any(issue.startswith('missing:') for issue in issues)
    assert any(issue.startswith('forbidden:') for issue in issues)
    assert 'possible_summary_or_omission' in issues


@pytest.mark.parametrize('case_id,before,after', [
    ('qx_en_invoice', '2,475.60', '2,457.60'),
    ('qx_de_invoice', '1.249,50', '1.294,50'),
    ('qx_en_privacy', 'publication_draft_v6', 'publication_draft_v8'),
    ('qx_de_code_switch', '/v3/aufträge', '/v3/orders'),
    ('qx_en_multi_owner', '17:40 UTC', '18:40 UTC'),
    ('qx_de_relative_and_absolute', 'Šimůnek', 'Schmitt'),
])
def test_changed_critical_numbers_names_dates_or_paths_are_not_accepted(case_id, before, after):
    case = selected(case_id)
    issues = benchmark.assess(case, {'title': 'Meeting note', 'corrected_transcript': case.text.replace(before, after)})
    assert any(issue.startswith('missing:') for issue in issues)


def test_omitted_information_does_not_become_created_task_or_assigned_owner():
    case = selected('qx_en_omitted_result')
    invalid = case.text.replace('That has not been assigned.', 'It has been assigned to Noura.').replace(
        'no task has been saved', 'a task has been saved')
    issues = benchmark.assess(case, {'title': 'Missing test documentation', 'corrected_transcript': invalid})
    assert any('assigned' in issue for issue in issues)
    assert any('saved' in issue for issue in issues)


def test_short_summary_cannot_substitute_for_long_recording_correction():
    case = selected('qx_en_multi_owner')
    output = {'title': 'Review owners and deadline', 'corrected_transcript':
              'Priya drafts, Mateo checks figures, and Amara Okafor approves. The North & Willow draft is due '
              '3 December 2026 at 17:40 UTC. Upload owner is unassigned; nothing sent.'}
    assert 'possible_summary_or_omission' in assess_expanded(case, output)


@pytest.mark.parametrize('arm', ['mercury-low', 'gemini-3.8-low'])
def test_expanded_corrections_keep_exact_production_shared_prompt(arm):
    case = selected('qx_de_quote')
    _, body = benchmark.request_for(case, arm)
    actual = body['messages'][0]['content'] if arm == 'mercury-low' else body['contents'][0]['parts'][0]['text']
    assert actual == build_transcript_correction_prompt('de')
    assert 'summary' not in actual.lower()


def events_for(arm, output, *, model=None, finish=None, function='finalize_transcript'):
    if arm == 'mercury-low':
        return [{'model': model or 'mercury-3', 'choices': [{'finish_reason': finish or 'tool_calls',
                 'delta': {'tool_calls': [{'index': 0, 'function': {'name': function, 'arguments': json.dumps(output)}}]}}]},
                {'usage': {'prompt_tokens': 200, 'completion_tokens': 100,
                           'prompt_tokens_details': {'cached_tokens': 120},
                           'completion_tokens_details': {'reasoning_tokens': 12}}}]
    return [{'modelVersion': model or 'gemini-3.8-flash', 'candidates': [{'finishReason': finish or 'STOP',
             'content': {'parts': [{'functionCall': {'name': function, 'args': output}}]}}]},
            {'usageMetadata': {'promptTokenCount': 200, 'candidatesTokenCount': 90,
                               'thoughtsTokenCount': 10, 'cachedContentTokenCount': 120}}]


async def fake_run(arm, *, model=None, finish=None, function='finalize_transcript'):
    case = selected('qx_en_quote')
    output = {'title': 'Untrusted quoted log message', 'corrected_transcript': case.text}
    events = events_for(arm, output, model=model, finish=finish, function=function)
    def respond(_request):
        return httpx.Response(200, content=''.join('data: ' + json.dumps(event) + '\n\n' for event in events))
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        return await benchmark.run_case(client, 'synthetic-key', case, arm)


@pytest.mark.asyncio
@pytest.mark.parametrize('arm', ['mercury-low', 'gemini-3.8-low'])
async def test_native_identity_raw_cache_and_tool_latency_are_retained(arm):
    row = await fake_run(arm)
    assert row['task_pass'] is True and row['identity_verified']
    assert row['quality_evaluated'] and row['functional_status'] == 'completed'
    assert row['ttft_ms'] is None
    assert row['first_tool_arguments_ms'] is not None
    assert row['cached_input_tokens'] == 120
    assert row['usage_complete']
    assert len(row['raw_native_events']) == 2
    assert row['finish_reason'] in {'STOP', 'tool_calls'}


@pytest.mark.asyncio
@pytest.mark.parametrize('arm', ['mercury-low', 'gemini-3.8-low'])
async def test_wrong_observed_model_is_not_scored_as_requested_arm(arm):
    row = await fake_run(arm, model='unrequested-model')
    assert row['identity_verified'] is False
    assert row['quality_evaluated'] is False and row['task_pass'] is None
    assert row['functional_status'] == 'identity_or_transport_failure'


@pytest.mark.asyncio
async def test_google_lite_model_cannot_pass_flash_identity_prefix_check():
    row = await fake_run('gemini-3.8-low', model='gemini-3.8-flash-lite')
    assert row['identity_verified'] is False and row['task_pass'] is None


@pytest.mark.asyncio
@pytest.mark.parametrize('arm', ['mercury-low', 'gemini-3.8-low'])
@pytest.mark.parametrize('bad', ['finish', 'function'])
async def test_truncation_or_wrong_tool_remains_a_counted_functional_failure(arm, bad):
    row = await fake_run(arm, **({'finish': 'length'} if bad == 'finish' else {'function': 'wrong_tool'}))
    assert row['identity_verified']
    assert row['task_pass'] is False and row['quality_evaluated']
    assert row['availability_status'] == 'available'
    assert row['functional_status'] == 'invalid_or_incomplete_model_output'


@pytest.mark.asyncio
async def test_slow_valid_mercury_is_not_a_five_second_primary_success(monkeypatch):
    clock = iter([0.0, 1.0, 6.0])
    monkeypatch.setattr(benchmark, 'time', SimpleNamespace(perf_counter=lambda: next(clock)))
    row = await fake_run('mercury-low')
    assert row['task_pass'] is True
    assert row['total_ms'] == 6000
    assert row['exceeds_mercury_correction_5s_deadline']
    assert row['strict_pass_within_streamed_5s'] is False


@pytest.mark.parametrize('arm,usage', [
    ('mercury-low', {'prompt_tokens': 100, 'completion_tokens': 20, 'prompt_tokens_details': {'cached_tokens': 101}}),
    ('mercury-low', {'prompt_tokens': 100, 'completion_tokens': 20, 'completion_tokens_details': {'reasoning_tokens': 21}}),
    ('gemini-3.8-low', {'promptTokenCount': 100, 'candidatesTokenCount': True}),
    ('gemini-3.8-low', {'promptTokenCount': 100, 'candidatesTokenCount': 20, 'thoughtsTokenCount': -1}),
])
def test_invalid_native_usage_subsets_or_boolean_tokens_cannot_claim_complete_cost(arm, usage):
    result = benchmark.usage_cost(arm, usage)
    assert result['usage_complete'] is False
    assert result['estimated_cost_usd'] is None


@pytest.mark.asyncio
async def test_expanded_suite_rejects_gateway_or_historical_arm_before_secret_lookup():
    args = SimpleNamespace(suite='expanded', arms=['mercury-openrouter-low'], cases=None)
    with pytest.raises(ValueError, match='two native LOW arms'):
        await benchmark.run(args)


def test_equivalent_decimal_separator_is_not_a_critical_pattern_failure():
    case = selected('qx_de_invoice')
    text = case.text.replace('1.249,50', '1249.50')
    assert all(re.search(pattern, text, re.I | re.S) for pattern in case.required)
    # Counterexamples must not require dropping an explicitly rejected value.
    case = selected('qx_en_omitted_result')
    assert not any(re.search(pattern, case.text, re.I | re.S) for pattern in case.forbidden)
    assert not any(re.search(pattern, case.text.replace('not five successful', 'not 5 successful'), re.I | re.S)
                   for pattern in case.forbidden)
