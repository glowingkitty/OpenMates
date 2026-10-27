"""Direct workflow author contracts with synthetic streams and no inference."""
# contract-test-file: infrastructure

import asyncio
import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

from backend.core.api.app.services.workflow_gemini_authoring import (
    WorkflowAuthoringProviderError, WorkflowAuthoringStopped, authoring_prompt, provider_response_schema,
)
from backend.core.api.app.services.workflow_mercury_authoring import WorkflowMercuryAuthor, MERCURY_MODEL
from backend.core.api.app.services import workflow_registry_planner as planner
from backend.core.api.app.services.workflow_capability_registry import WorkflowCapabilityRegistry, _FilesystemWorkflowMetadataRegistry
from backend.shared.providers.inception import InceptionError, InceptionResult
from backend.tests.test_workflow_gemini_authoring import selection
from backend.tests.test_workflow_registry_planner import configure, flat_forecast, FlatAuthor
from backend.tests.test_workflow_authoring_billing import Catalog


@pytest.fixture(autouse=True)
def filesystem_registry(monkeypatch):
    monkeypatch.setattr(WorkflowCapabilityRegistry, '_registry', lambda _: _FilesystemWorkflowMetadataRegistry())


class Secrets:
    async def get_secret(self, **kwargs):
        assert kwargs['secret_path'] == 'kv/data/providers/inception_labs'
        return 'fake'


def content(text, *, finish=None, usage=None):
    return InceptionResult.model_validate({'choices': [{'delta': {'content': text}, 'finish_reason': finish}],
                                         **({'usage': usage} if usage else {})})


def usage():
    return {'prompt_tokens': 100, 'completion_tokens': 30, 'total_tokens': 130,
            'prompt_tokens_details': {'cached_tokens': 80},
            'completion_tokens_details': {'reasoning_tokens': 10}}


def native_factory(stream, captured=None):
    def factory(key, **kwargs):
        assert key == 'fake'
        assert kwargs['max_retries'] == 0
        async def events(request):
            if captured is not None:
                captured.append(request)
            async for event in stream():
                yield event
        return SimpleNamespace(stream=events)
    return factory


def make_author(stream, **kwargs):
    return WorkflowMercuryAuthor(Secrets(), client=object(), config_manager=Catalog(),
                                 native_client_factory=native_factory(stream), **kwargs)


@pytest.mark.asyncio
@pytest.mark.parametrize('profile', ['instant', 'low'])
async def test_native_profile_preserves_prompt_schema_callbacks_and_metering(profile):
    raw = flat_forecast()
    captured, accepted = [], []
    async def stream():
        yield content(json.dumps(raw), finish='stop', usage=usage())
    author = WorkflowMercuryAuthor(Secrets(), config_manager=Catalog(),
        native_client_factory=native_factory(stream, captured), reasoning_effort=profile)
    selected = selection('weather.forecast')
    result, metrics = await author.generate(text='Forecast', selection=selected, timezone='UTC',
                                            on_plan_component=accepted.append)
    assert [event['type'] for event in accepted] == ['header', 'node', 'node']
    assert len(result['steps']) == 2
    request = captured[0]
    assert request.model == 'mercury-3'
    assert request.reasoning_effort == profile
    assert request.temperature == .5
    assert request.max_completion_tokens == 8192
    assert request.messages[0]['content'] == authoring_prompt(selected, 'UTC')
    assert request.response_format['json_schema']['schema'] == provider_response_schema(selected)
    assert metrics['input_tokens'] == 100
    assert metrics['cache_read_input_tokens'] == 80
    assert metrics['output_tokens'] == 30  # Includes reasoning once.
    assert metrics['thinking_tokens'] == 10
    assert metrics['estimated_cost_usd'] == pytest.approx(.0000205)


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['first_output', 'idle', 'total'])
async def test_author_time_bounds_keep_known_usage_and_close_stream(mode):
    closed = []
    header = flat_forecast()['workflows'][0]['header']
    async def stream():
        try:
            if mode != 'first_output':
                yield content('{"workflows":[{"header":' + json.dumps(header) + ',"nodes":[')
            while True:
                yield content('', usage=usage())
                await asyncio.sleep(.003 if mode != 'idle' else 1)
        finally:
            closed.append(True)
    kwargs = {'first_output_timeout': .02, 'idle_timeout': .02, 'total_timeout': .2}
    if mode == 'total':
        kwargs.update(first_output_timeout=.2, idle_timeout=.2, total_timeout=.03)
    author = make_author(stream, **kwargs)
    with pytest.raises(WorkflowAuthoringProviderError) as caught:
        await author.generate(text='Forecast', selection=selection('weather.forecast'), timezone='UTC')
    assert caught.value.is_availability_failure
    assert caught.value.code == 'provider_timeout'
    assert caught.value.metrics['input_tokens'] == 100
    assert closed == [True]


@pytest.mark.asyncio
async def test_stop_pending_stream_preserves_prefix_without_availability_fallback():
    closed, accepted = [], []
    stop = False
    async def accept(event):
        nonlocal stop
        accepted.append(event)
        stop = True
    async def stream():
        try:
            header = flat_forecast()['workflows'][0]['header']
            yield content('{"workflows":[{"header":' + json.dumps(header) + ',"nodes":[')
            await asyncio.sleep(10)
        finally:
            closed.append(True)
    with pytest.raises(WorkflowAuthoringStopped) as caught:
        await make_author(stream).generate(text='Forecast', selection=selection('weather.forecast'),
            timezone='UTC', on_plan_component=accept, should_stop=lambda: stop)
    assert not caught.value.is_availability_failure
    assert [event['type'] for event in accepted] == ['header']
    assert closed == [True]


@pytest.mark.asyncio
@pytest.mark.parametrize('status,availability', [(400, False), (401, False), (429, True), (503, True)])
async def test_http_failure_classification(status, availability):
    async def stream():
        raise InceptionError('safe', kind='http', status_code=status)
        yield  # Async generator.
    with pytest.raises(WorkflowAuthoringProviderError) as caught:
        await make_author(stream).generate(text='Forecast', selection=selection('weather.forecast'), timezone='UTC')
    assert caught.value.is_availability_failure is availability
    assert caught.value.http_status == status


@pytest.mark.asyncio
async def test_invalid_model_json_is_not_an_outage():
    async def stream():
        yield content('{bad json', finish='stop')
    with pytest.raises(WorkflowAuthoringProviderError) as caught:
        await make_author(stream).generate(text='Forecast', selection=selection('weather.forecast'), timezone='UTC')
    assert not caught.value.is_availability_failure
    assert caught.value.code == 'invalid_json'


@pytest.mark.asyncio
async def test_outage_fallback_uses_planner_prefix_no_duplicate_nodes_or_repair_budget(monkeypatch):
    configure(monkeypatch)
    raw = flat_forecast()
    mercury_calls, checkpoints = [], []
    class Mercury:
        model_id = MERCURY_MODEL
        async def generate(self, **kwargs):
            mercury_calls.append(kwargs)
            first = raw['workflows'][0]
            await kwargs['on_plan_component']({'type': 'header', 'workflow_index': 0, 'header': first['header']})
            await kwargs['on_plan_component']({'type': 'node', 'workflow_index': 0, 'index': 0, 'node': first['nodes'][0]})
            # A provider-local snapshot is deliberately not authoritative.
            contaminated = deepcopy(first)
            contaminated['nodes'].append({'id': 'never_accepted', 'kind': 'end'})
            raise WorkflowAuthoringProviderError('Workflow provider transport failed',
                {'input_tokens': 100, 'output_tokens': 20}, [contaminated], is_availability_failure=True)
    broken = deepcopy(raw)
    broken['workflows'][0]['nodes'][1]['message_json'] = '[{"ref":{"step":"invented","field":"summary"}}]'
    fallback = FlatAuthor([broken, raw])
    instance = planner.WorkflowRegistryPlanner(secrets_manager=None, fallback_author=fallback)
    result = await instance._plan('Forecast', {'timezone': 'UTC', '_on_checkpoint': checkpoints.append}, object(), Mercury())
    assert result['action'] == 'create_workflow'
    assert len(mercury_calls) == 1
    assert len(fallback.requests) == 2  # Outage did not consume the failing node's correction.
    assert len(fallback.requests[0]['accepted_prefixes'][0]['nodes']) == 1
    assert 'never_accepted' not in str(fallback.requests)
    assert [event['accepted_node_count'] for event in checkpoints] == [0, 1, 2]
    assert [entry['model_used'] for entry in result['_authoring_metrics']['generation_attempts']] == [
        MERCURY_MODEL, 'google/gemini-3.8-flash', 'google/gemini-3.8-flash']


@pytest.mark.asyncio
async def test_schema_failure_repairs_mercury_without_switching_provider(monkeypatch):
    configure(monkeypatch)
    good = flat_forecast()
    bad = deepcopy(good)
    bad['workflows'][0]['nodes'][1]['message_json'] = '[{"ref":{"step":"invented","field":"summary"}}]'
    primary = FlatAuthor([bad])
    primary.model_id = MERCURY_MODEL
    recovery = FlatAuthor([good])
    recovery.model_id, recovery.reasoning_effort = MERCURY_MODEL, 'low'
    fallback = FlatAuthor([good])
    result = await planner.WorkflowRegistryPlanner(secrets_manager=None, recovery_author=recovery,
        fallback_author=fallback)._plan(
        'Forecast', {'timezone': 'UTC'}, object(), primary)
    assert result['action'] == 'create_workflow'
    assert len(primary.requests) == len(recovery.requests) == 1 and fallback.requests == []
    assert [item['reasoning_effort'] for item in result['_authoring_metrics']['generation_attempts']] == ['instant', 'low']
    assert 'provider_fallback' not in result['_authoring_metrics']


@pytest.mark.asyncio
async def test_credential_lookup_uses_first_output_deadline_and_cancels_cleanly():
    closed = []
    class SlowSecrets:
        async def get_secret(self, **kwargs):
            try:
                await asyncio.sleep(10)
            finally:
                closed.append(True)
    author = WorkflowMercuryAuthor(SlowSecrets(), client=object(), config_manager=Catalog(),
                                  first_output_timeout=.02, total_timeout=.2)
    with pytest.raises(WorkflowAuthoringProviderError) as caught:
        await author.generate(text='Forecast', selection=selection('weather.forecast'), timezone='UTC')
    assert caught.value.is_availability_failure
    assert caught.value.code == 'provider_timeout'
    assert closed == [True]
    assert caught.value.metrics == {}  # No invented provider usage before dispatch.


@pytest.mark.asyncio
async def test_planner_stop_never_switches_to_fallback(monkeypatch):
    configure(monkeypatch)
    class Stopped:
        model_id = MERCURY_MODEL
        async def generate(self, **kwargs):
            raise WorkflowAuthoringStopped('Workflow authoring was stopped')
    fallback = FlatAuthor([flat_forecast()])
    result = await planner.WorkflowRegistryPlanner(secrets_manager=None, fallback_author=fallback)._plan(
        'Forecast', {'timezone': 'UTC'}, object(), Stopped())
    assert fallback.requests == []
    assert 'provider_fallback' not in result['_authoring_metrics']


class ProfileAuthor(FlatAuthor):
    """Deterministic boundary double; the production planner/compiler still run."""
    def __init__(self, response, profile='instant', model=MERCURY_MODEL):
        super().__init__([response])
        self.reasoning_effort, self.model_id = profile, model

    async def generate(self, **kwargs):
        if isinstance(self.responses[0], BaseException):
            self.requests.append(kwargs)
            raise self.responses[0]
        return await super().generate(**kwargs)


def invalid_delivery():
    bad = flat_forecast()
    bad['workflows'][0]['nodes'][1]['message_json'] = '[{"ref":{"step":"invented","field":"summary"}}]'
    return bad


@pytest.mark.asyncio
@pytest.mark.parametrize('terminal_valid', [True, False])
# contract-test: supporting surface=rest_api assertions=workflows.authoring.compact-plan,workflows.authoring.provisional-validation
async def test_request_recovery_chain_is_bounded_and_never_republishes_prefix(monkeypatch, terminal_valid):
    configure(monkeypatch)
    primary = ProfileAuthor(invalid_delivery())
    recovery = ProfileAuthor(invalid_delivery(), 'low')
    fallback = ProfileAuthor(flat_forecast() if terminal_valid else invalid_delivery(),
                             'low', 'google/gemini-3.8-flash')
    checkpoints, progress = [], []
    result = await planner.WorkflowRegistryPlanner(secrets_manager=None, recovery_author=recovery,
        fallback_author=fallback)._plan('Forecast', {'timezone': 'UTC',
        '_on_checkpoint': checkpoints.append, '_on_component': progress.append}, object(), primary)
    assert [len(a.requests) for a in (primary, recovery, fallback)] == [1, 1, 1]
    assert [e['accepted_node_count'] for e in checkpoints] == ([0, 1, 2] if terminal_valid else [0, 1])
    for author in (recovery, fallback):
        assert author.requests[0]['accepted_prefixes'][0]['nodes'] == flat_forecast()['workflows'][0]['nodes'][:1]
        assert 'correction' in author.requests[0]
    metrics = result['_authoring_metrics']
    assert [(a['model_used'], a['reasoning_effort']) for a in metrics['generation_attempts']] == [
        (MERCURY_MODEL, 'instant'), (MERCURY_MODEL, 'low'), ('google/gemini-3.8-flash', 'low')]
    assert [e['correction_attempt'] for e in progress if e.get('phase') == 'retrying_node'] == [1, 2]
    if terminal_valid:
        assert result['action'] == 'create_workflow'
    else:
        assert result['action'] == 'partial'
        assert result['notice'] == planner.PARTIAL_FAILURE
        assert 'Some parts could not be created' in result['notice']
        assert len(result['operations'][0]['graph']['nodes']) == 2
        assert result['operations'][0]['enabled'] is False


@pytest.mark.asyncio
async def test_malformed_primary_uses_low_recovery_and_missing_usage_stays_unknown(monkeypatch):
    configure(monkeypatch)
    primary = ProfileAuthor(WorkflowAuthoringProviderError('Workflow provider returned invalid JSON'))
    recovery = ProfileAuthor(flat_forecast(), 'low')
    fallback = ProfileAuthor(flat_forecast(), 'low', 'google/gemini-3.8-flash')
    result = await planner.WorkflowRegistryPlanner(secrets_manager=None, recovery_author=recovery,
        fallback_author=fallback)._plan('Forecast', {'timezone': 'UTC'}, object(), primary)
    assert result['action'] == 'create_workflow' and not fallback.requests
    attempt = result['_authoring_metrics']['generation_attempts'][0]
    assert attempt['model_used'] == MERCURY_MODEL and attempt['reasoning_effort'] == 'instant'
    assert 'input_tokens' not in attempt and 'output_tokens' not in attempt
    assert result['_authoring_metrics']['cost_estimate_complete'] is False


@pytest.mark.asyncio
@pytest.mark.parametrize('during', ['instant', 'low'])
async def test_availability_skips_known_unavailable_mercury_with_global_three_call_cap(monkeypatch, during):
    configure(monkeypatch)
    outage = WorkflowAuthoringProviderError('Workflow provider transport failed',
        {'input_tokens': 100, 'output_tokens': 20}, code='provider_timeout', is_availability_failure=True)
    primary = ProfileAuthor(outage if during == 'instant' else invalid_delivery())
    recovery = ProfileAuthor(outage, 'low')
    fallback = FlatAuthor([invalid_delivery(), flat_forecast()])
    fallback.model_id, fallback.reasoning_effort = 'google/gemini-3.8-flash', 'low'
    result = await planner.WorkflowRegistryPlanner(secrets_manager=None, recovery_author=recovery,
        fallback_author=fallback)._plan('Forecast', {'timezone': 'UTC'}, object(), primary)
    assert sum(len(a.requests) for a in (primary, recovery, fallback)) == 3
    assert len(recovery.requests) == (0 if during == 'instant' else 1)
    assert len(fallback.requests) == (2 if during == 'instant' else 1)
    assert result['action'] == ('create_workflow' if during == 'instant' else 'partial')
    assert len(result['_authoring_metrics']['author_recovery']) == 2


@pytest.mark.asyncio
async def test_a_new_failing_node_does_not_restart_the_request_recovery_budget(monkeypatch):
    configure(monkeypatch)
    later_bad = flat_forecast()
    later_bad['workflows'][0]['nodes'].append({
        'kind': 'send', 'id': 'extra', 'title': 'Extra',
        'message_json': '[{"ref":{"step":"unknown","field":"summary"}}]'})
    authors = [ProfileAuthor(invalid_delivery()), ProfileAuthor(later_bad, 'low'),
               ProfileAuthor(later_bad, 'low', 'google/gemini-3.8-flash')]
    result = await planner.WorkflowRegistryPlanner(secrets_manager=None, recovery_author=authors[1],
        fallback_author=authors[2])._plan('Forecast', {'timezone': 'UTC'}, object(), authors[0])
    assert [len(a.requests) for a in authors] == [1, 1, 1]
    assert len(authors[2].requests[0]['accepted_prefixes'][0]['nodes']) == 2
    assert result['action'] == 'partial'
    assert len(result['operations'][0]['graph']['nodes']) == 3  # Trigger+two accepted nodes.


@pytest.mark.asyncio
async def test_stop_during_low_recovery_does_not_invoke_gemini(monkeypatch):
    configure(monkeypatch)
    primary = ProfileAuthor(invalid_delivery())
    recovery = ProfileAuthor(WorkflowAuthoringStopped('Workflow authoring was stopped'), 'low')
    fallback = ProfileAuthor(flat_forecast(), 'low', 'google/gemini-3.8-flash')
    result = await planner.WorkflowRegistryPlanner(secrets_manager=None, recovery_author=recovery,
        fallback_author=fallback)._plan('Forecast', {'timezone': 'UTC'}, object(), primary)
    assert result['action'] == 'partial' and result['reason'] == 'stopped'
    assert not fallback.requests and len(recovery.requests) == 1
    assert [a['reasoning_effort'] for a in result['_authoring_metrics']['generation_attempts']] == ['instant', 'low']


@pytest.mark.asyncio
async def test_withdrawn_monday_cannot_rewrite_accepted_prefix_and_remains_disabled_partial(monkeypatch):
    configure(monkeypatch, count=1)
    wrong = flat_forecast()
    wrong['workflows'][0]['header']['schedule'] = {
        'type': 'weekly', 'time': '07:00', 'timezone': 'Europe/Berlin', 'weekdays': ['monday']}
    intended = deepcopy(wrong['workflows'][0])
    intended['header']['schedule'] = {
        'type': 'weekly', 'time': '18:35', 'timezone': 'Europe/Berlin', 'weekdays': ['wednesday', 'friday']}
    wrong['workflows'].append(intended)
    correct = {'workflows': [intended]}
    authors = [ProfileAuthor(wrong), ProfileAuthor(correct, 'low'),
               ProfileAuthor(correct, 'low', 'google/gemini-3.8-flash')]
    checkpoints = []
    result = await planner.WorkflowRegistryPlanner(secrets_manager=None, recovery_author=authors[1],
        fallback_author=authors[2])._plan('Monday, no, Wednesday and Friday',
        {'timezone': 'Europe/Berlin', '_on_checkpoint': checkpoints.append}, object(), authors[0])
    assert [len(a.requests) for a in authors] == [1, 1, 1]
    assert result['action'] == 'partial' and len(result['operations']) == 2
    assert all(o['enabled'] is False for o in result['operations'])
    assert result['_authoring_metrics']['last_failure_reason_code'] == 'retry_header_changed'
    assert len(checkpoints) == 6  # Two initial headers+four nodes; no recovery replay.
