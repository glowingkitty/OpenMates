"""Focused comparison, recovery and safety tests with real Vault-shaped ciphertext."""
import json
from types import SimpleNamespace

import pytest

from backend.core.api.app.services.workflow_app_skill_adapter import WorkflowAppSkillAdapter
from backend.core.api.app.services import workflow_app_skill_adapter as adapter_module
from backend.core.api.app.services import workflow_runner as runner_module
from backend.core.api.app.services.workflow_ai_service import WorkflowCheckResult
from backend.core.api.app.services.workflow_runner import WorkflowRunner
from backend.core.api.app.services.workflow_website_changes import WorkflowWebsiteChanges, WebsiteChangesError, website_plan
from backend.shared.python_utils.website_text import normalize_page_text, website_read_status, website_text_diff
from backend.tests.workflow_test_utils import workflow_service


URL = 'https://events.ccc.de'
A = '# Congress\n\n[Older post](https://events.ccc.de/old)\n\nUnchanged article ' + 'background ' * 400
B = A + '\n\n[Congress tickets](https://events.ccc.de/tickets) are available.'


def graph(ai=False):
    return {'version': 2, 'trigger_node_id': 'trigger', 'nodes': [
        {'id': 'trigger', 'type': 'manual_trigger', 'config': {}},
        {'id': 'read', 'type': 'app_skill_action', 'config': {'app_id': 'web', 'skill_id': 'read', 'input': {'requests': [{'url': URL}]}}},
        {'id': 'check', 'type': 'check', 'config': {'mode': 'ai', 'question': 'Do these changes announce Congress news? {{steps.read.changes}}', 'selected_inputs': ['$nodes.read.output.changes']} if ai else {'mode': 'exact', 'predicate': {'op': 'eq', 'left': '$nodes.read.output.has_changed', 'right': True}}},
        {'id': 'send', 'type': 'send_chat_message', 'config': {'title': 'Congress', 'message': '{{steps.read.changes}}\n{{steps.read.source_url}}'}},
    ], 'edges': [{'from': 'trigger', 'to': 'read'}, {'from': 'read', 'to': 'check'}, {'from': 'check', 'to': 'send', 'branch': 'true' if ai else 'yes'}]}


def raw(text, **metadata):
    return {'results': [{'id': 'page', 'results': [{'url': URL, 'title': 'Congress news', 'markdown': text, **metadata}]}]}


def store_fixture():
    service = workflow_service()
    workflow = service.create_workflow('alice', 'Congress updates', graph(), enabled=False)
    # The runtime checkpoints this row before fetching the website.
    service.repository.save_run({'id': 'run-1', 'workflow_id': workflow.id, 'owner_hash': service.repository.get_workflow(workflow.id, 'alice')['owner_hash'], 'version_id': workflow.current_version_id, 'status': 'running'})
    store = WorkflowWebsiteChanges(service, workflow.id, 'alice', 'run-1', workflow.current_version_id)
    return service, workflow, store, website_plan(workflow.graph)['read']


# contract-test: supporting surface=rest_api assertions=workflows.website-change.baseline,workflows.website-change.diff-inputs
def test_baseline_diff_and_quality_preserve_last_good_snapshot():
    service, workflow, store, plan = store_fixture()
    request = {'requests': [{'url': URL, 'max_age': 0}]}
    first = store.project('read', request, plan, raw(A))
    assert first['change_status'] == 'initialized' and not first['has_changed']
    assert first['text'] == '' and 'results' not in first
    assert 'nonce' not in json.dumps(first)
    assert store._blob({'text': A})['checksum'] != store._blob({'text': A})['checksum']
    assert store.project('read', request, plan, raw(A + '\r\n'))['change_status'] == 'unchanged'
    assert store.project('read', {'requests': [{'url': URL, 'only_main_content': None, 'max_age': 123}]}, plan, raw(A))['change_status'] == 'unchanged'
    before = json.dumps(service.repository._website_state, sort_keys=True)
    for text, metadata, status in [('', {}, 'EMPTY'), ('Verify you are human', {}, 'BLOCKED'), ('', {'http_status': 403, 'error': 'Access denied'}, 'BLOCKED'), ('# unavailable', {'http_status': 503}, 'FAILED'), ('Some incomplete news', {'warnings': ['partial']}, 'PARTIAL')]:
        with pytest.raises(WebsiteChangesError, match=status):
            store.project('read', request, plan, raw(text, **metadata))
        assert json.dumps(service.repository._website_state, sort_keys=True) == before
    changed = store.project('read', request, plan, raw(B))
    assert changed['has_changed']
    assert '+[Congress tickets](https://events.ccc.de/tickets)' in changed['changes']
    # Two context lines preserve nearby evidence; distant unchanged article is absent.
    assert changed['changes'].count('background ') < 400
    assert A not in json.dumps(changed)
    persisted = json.dumps({'state': service.repository._website_state, 'blobs': service.repository.encrypted_blobs})
    assert URL not in persisted and 'Congress tickets' not in persisted
    retry = store.project('read', request, plan, raw(B))
    assert retry['_website_events']['check']['id'] == changed['_website_events']['check']['id']
    assert retry['changes'] == changed['changes']


# contract-test: supporting surface=rest_api assertions=workflows.website-change.retry,workflows.website-change.lifecycle
def test_rejection_occurrences_generation_and_run_deletion():
    service, workflow, store, plan = store_fixture()
    request = {'url': URL}
    store.project('read', request, plan, raw(A))
    changed = store.project('read', request, plan, raw(B))
    event = changed['_website_events']['check']
    store.save_event_output(event, 'check', {'matched': False}, discard=True)
    assert not store.project('read', request, plan, raw(B))['has_changed']
    reversed_event = store.project('read', request, plan, raw(A))['_website_events']['check']
    assert reversed_event['id'] != event['id']
    reset = store.project('read', {'url': URL + '/new'}, plan, raw(B))
    assert reset['change_status'] == 'initialized' and not reset['has_changed']
    service.delete_run(workflow.id, 'run-1', 'alice')
    assert service.repository._website_state == {}
    with pytest.raises(WebsiteChangesError, match='FENCED'):
        store.project('read', request, plan, raw(A))


# contract-test: supporting surface=rest_api assertions=workflows.website-change.diff-inputs
def test_diff_is_bounded_without_silent_truncation_and_short_pages_are_valid():
    assert website_read_status({'markdown': 'New opening hours: 10–12.'}) == 'usable'
    assert website_read_status({'title': 'Congress research about CAPTCHAs', 'markdown': 'We discussed CAPTCHA design.'}) == 'usable'
    assert website_read_status({'markdown': 'Accept all cookies to continue.'}) == 'blocked'
    assert normalize_page_text('A\r\nB  \r\n') == 'A\nB'
    with pytest.raises(ValueError, match='DIFF_TOO_LARGE'):
        website_text_diff('old', 'new ' * 6000)


# contract-test: supporting surface=rest_api assertions=workflows.website-change.retry,workflows.website-change.lifecycle
def test_older_fetches_do_not_replace_a_newer_baseline_and_evaluation_leases_recover():
    service, workflow, store, plan = store_fixture()
    store.project('read', {'url': URL}, plan, raw(A), observed_at=1000)
    event = store.project('read', {'url': URL}, plan, raw(B), observed_at=2000)['_website_events']['check']
    before = json.dumps(service.repository._website_state, sort_keys=True)
    with pytest.raises(WebsiteChangesError, match='STALE_READ'):
        store.project('read', {'url': URL}, plan, raw(A), observed_at=1500)
    assert json.dumps(service.repository._website_state, sort_keys=True) == before
    row = service.repository.get_run(workflow.id, 'run-1', 'alice')
    service.repository.save_run({**row, 'id': 'run-2', 'status': 'running'})
    other = WorkflowWebsiteChanges(service, workflow.id, 'alice', 'run-2', workflow.current_version_id)
    assert store.transaction('claim_event', event_id=event['id'])['claimed']
    assert not other.transaction('claim_event', event_id=event['id'])['claimed']
    service.repository._website_state[event['id']]['processing_expires_at'] = 0
    assert other.transaction('claim_event', event_id=event['id'])['claimed']
    with pytest.raises(WebsiteChangesError, match='EVENT_CONFLICT'):
        store.save_event_output(event, 'check', {'matched': True})


class Registry:
    def __init__(self, text=A):
        self.text, self.calls = text, []

    def get_metadata(self, _app):
        return None

    async def dispatch_skill(self, app, skill, request):
        self.calls.append(request)
        return raw(self.text)


# contract-test: supporting surface=rest_api assertions=workflows.website-change.diff-inputs
@pytest.mark.asyncio
async def test_adapter_scans_projection_and_bills_original_read(monkeypatch):
    scanned, billed = [], []
    async def scan(payload, _context):
        scanned.append(payload)
        return payload
    async def precheck(**_kwargs):
        pass
    async def charge(**kwargs):
        billed.append(kwargs['result'])
        return 2
    monkeypatch.setattr(adapter_module, 'sanitize_app_skill_output', scan)
    monkeypatch.setattr(adapter_module, '_precheck_workflow_skill_billing', precheck)
    monkeypatch.setattr(adapter_module, '_charge_workflow_skill_result', charge)
    adapter = WorkflowAppSkillAdapter(registry=Registry(B))
    async def projection(_raw):
        return {'changes': '+Congress tickets', 'has_changed': True, 'read_status': 'usable', 'source_url': URL,
                '_website_events': {'check': {'changes': '+Congress tickets', 'cached_outputs': {'check': {'matched': True}}}}}
    output = await adapter.execute('web', 'read', {'url': URL}, user_id='alice', billing_context={'workflow_id':'w','run_id':'r','node_id':'read','source':'workflow'}, website_projection=projection)
    assert scanned[0]['changes'] == '+Congress tickets'
    assert billed[0]["results"][0]["results"][0]["markdown"] == B
    assert B not in json.dumps(output)
    assert output['changes'] == '+Congress tickets' and output['_workflow_credit_cost'] == 2
    assert output['_website_events']['check']['cached_outputs']['check']['matched'] is True
    assert '_website_events' not in output['raw']


# contract-test: supporting surface=rest_api assertions=workflows.website-change.baseline,workflows.website-change.retry
@pytest.mark.asyncio
async def test_runner_skips_baseline_and_unchanged_ai_and_retries_unsure(monkeypatch):
    async def scan(payload, _context):
        return payload
    async def billing(**_kwargs):
        return 0
    async def precheck(*_args, **_kwargs):
        pass
    monkeypatch.setattr(adapter_module, 'sanitize_app_skill_output', scan)
    monkeypatch.setattr(adapter_module, '_precheck_workflow_skill_billing', precheck)
    monkeypatch.setattr(adapter_module, '_charge_workflow_skill_result', billing)
    monkeypatch.setattr(runner_module, '_precheck_workflow_ai_check', precheck)
    monkeypatch.setattr(runner_module, '_charge_workflow_ai_check', billing)
    class Ai:
        def __init__(self):
            self.calls = []
            self.outcome = 'unsure'
        async def preflight_check_evaluation(self, *_args):
            return True
        async def evaluate_check(self, **kwargs):
            self.calls.append(kwargs)
            return WorkflowCheckResult(self.outcome, 'insufficient_evidence' if self.outcome == 'unsure' else 'matching', 'jev_boolean_decision', 'unknown' if self.outcome == 'unsure' else 'decision', True)
    class Actions:
        async def send_chat_message(self, *_args):
            raise RuntimeError('delivery unavailable')
    registry, ai, service = Registry(), Ai(), workflow_service()
    workflow = service.create_workflow('alice', 'Congress updates', graph(ai=True), enabled=False)
    runner = WorkflowRunner(service, WorkflowAppSkillAdapter(registry=registry), Actions(), ai)
    async def run():
        return await runner.run_workflow(workflow, 'alice', trigger_type='schedule')
    first = await run()
    assert first.status.value == 'completed', [(n.node_id, n.error_code, n.error_summary) for n in first.node_runs]
    assert not ai.calls
    await run()
    assert not ai.calls
    registry.text = B
    unsure = await run()
    assert unsure.status.value == 'completed' and len(ai.calls) == 1
    assert ai.calls[0]['selected_inputs'][0]['value'].startswith('--- previous page')
    assert A not in json.dumps(ai.calls)
    ai.outcome = 'true'
    failed = await run()
    assert failed.status.value == 'failed' and len(ai.calls) == 2
    await run()
    assert len(ai.calls) == 2  # Completed decision survives a failed send.
    assert all(call['requests'][0]['max_age'] == 0 for call in registry.calls)
    saved = json.dumps(service.repository._website_state)
    test_run = await runner.run_step_test(workflow, 'alice', 'read')
    assert test_run.status.value == 'completed'
    assert json.dumps(service.repository._website_state) == saved

# contract-test: supporting surface=rest_api assertions=workflows.website-change.diff-inputs
def test_complete_diff_reaches_check_and_summary_without_generic_string_truncation():
    from backend.core.api.app.services.workflow_ai_service import _bounded_runtime_inputs, render_bounded_ask_ai_prompt
    diff = '+Congress detail\n' * 500 + '+FINAL LINK https://events.ccc.de/new'
    inputs = [{'reference':'$nodes.read.output.changes','value':diff,'_complete_website_diff':True}]
    assert _bounded_runtime_inputs(inputs)[0]['value'] == diff
    context = {'nodes':{'read':{'app_id':'web','skill_id':'read','output':{'changes':diff}}}}
    prompt = render_bounded_ask_ai_prompt('Summarize {{steps.read.changes}}', context)
    assert 'FINAL LINK https://events.ccc.de/new' in prompt
    with pytest.raises(ValueError, match='DIFF_TOO_LARGE'):
        _bounded_runtime_inputs(inputs * 4)

# contract-test: supporting surface=rest_api assertions=workflows.website-change.retry
@pytest.mark.asyncio
async def test_exact_then_ai_check_shares_one_event_and_pending_delivery_suppresses_repeats(monkeypatch):
    from backend.core.api.app.services.workflow_action_adapter import WorkflowActionAdapter
    from backend.core.api.app.services.workflow_chat_delivery_service import WorkflowChatDeliveryService
    from backend.tests.test_workflow_delivery_history import Cipher
    async def scan(payload, _context): return payload
    async def billing(**_kwargs): return 0
    async def precheck(*_args, **_kwargs): pass
    monkeypatch.setattr(adapter_module, 'sanitize_app_skill_output', scan)
    monkeypatch.setattr(adapter_module, '_precheck_workflow_skill_billing', precheck)
    monkeypatch.setattr(adapter_module, '_charge_workflow_skill_result', billing)
    monkeypatch.setattr(runner_module, '_precheck_workflow_ai_check', precheck)
    monkeypatch.setattr(runner_module, '_charge_workflow_ai_check', billing)
    class Ai:
        calls = 0
        async def preflight_check_evaluation(self, *_args): return True
        async def evaluate_check(self, **_kwargs):
            self.calls += 1
            return WorkflowCheckResult('true', 'matching', 'jev_boolean_decision', 'decision', True)
    definition = graph(ai=True)
    definition['nodes'].insert(2, {'id':'changed','type':'check','config':{'mode':'exact','predicate':{'op':'eq','left':'$nodes.read.output.has_changed','right':True}}})
    definition['edges'][1] = {'from':'read','to':'changed'}
    definition['edges'].append({'from':'changed','to':'check','branch':'yes'})
    service, registry, ai, cipher = workflow_service(), Registry(), Ai(), Cipher()
    workflow = service.create_workflow('alice', 'Congress changes', definition)
    assert len(website_plan(workflow.graph)['read']['consumers']) == 1
    deliveries = WorkflowChatDeliveryService(cipher=cipher)
    actions = WorkflowActionAdapter(workflow_service=service,chat_delivery_service=deliveries)
    runner = WorkflowRunner(service,WorkflowAppSkillAdapter(registry=registry),actions,ai)
    await runner.run_workflow(workflow,'alice',trigger_type='schedule')
    registry.text = B
    changed = await runner.run_workflow(workflow,'alice',trigger_type='schedule')
    assert changed.status.value == 'completed', [(n.node_id,n.error_summary) for n in changed.node_runs]
    read_output = next(n.output_summary for n in changed.node_runs if n.node_id == 'read')
    assert '_website_events' not in read_output and '_website_events' not in read_output['raw']
    assert ai.calls == 1 and len(deliveries._repository._deliveries) == 1
    assert cipher.payloads[0].get('embeds', []) == []
    assert 'https://events.ccc.de/tickets' in cipher.payloads[0]['message']
    from backend.core.api.app.services.workflow_action_adapter import WorkflowActionExecutionError
    with pytest.raises(WorkflowActionExecutionError, match='text and links'):
        await actions.send_chat_message({'title': 'Mixed results', 'message': '{{steps.news.results}}'}, {
            'workflow': {'workflow_id': workflow.id, 'run_id': changed.id, 'node_id': 'send',
                         'website_active': {'id': 'change', 'targets': ['send']}},
            'nodes': {'news': {'app_id': 'news', 'output': {'results': [{'url': 'https://example.com/news', 'title': 'Related news'}]}}},
        }, 'alice')
    await runner.run_workflow(workflow,'alice',trigger_type='schedule')
    assert ai.calls == 1 and len(deliveries._repository._deliveries) == 1
    # A newer change must proceed while the older message is waiting offline.
    registry.text = B + '\n[Congress venue](https://events.ccc.de/venue) announced.'
    newer = await runner.run_workflow(workflow,'alice',trigger_type='schedule')
    assert newer.status.value == 'completed'
    assert ai.calls == 2 and len(deliveries._repository._deliveries) == 2
    await runner.run_workflow(workflow,'alice',trigger_type='schedule')
    assert ai.calls == 2
    for delivery_id in deliveries._repository._deliveries:
        claim = deliveries.claim_new_chat_delivery(delivery_id=delivery_id,owner_id='alice',device_id='web')
        deliveries.persist_client_ciphertext(delivery_id=delivery_id,owner_id='alice',claim=claim,device_id='web',encrypted_chat_metadata='chat-cipher',encrypted_message='message-cipher')
        deliveries.acknowledge_delivery(delivery_id=delivery_id,owner_id='alice',claim=claim,device_id='web')
    await runner.run_workflow(workflow,'alice',trigger_type='schedule')
    assert ai.calls == 2 and not any(r['kind']=='event' for r in service.repository._website_state.values())


# contract-test: supporting surface=rest_api assertions=workflows.website-change.diff-inputs
def test_independent_pending_diffs_all_reach_the_semantic_scan_collector():
    from backend.apps.ai.processing.external_result_sanitizer import _collect_string_fields_with_overrides
    from backend.shared.python_utils.app_skill_output_safety import ALWAYS_SEMANTIC_FIELD_NAMES
    collected = []
    projection = {'changes': '+Congress tickets', '_website_events': {
        'first': {'changes': '+Congress tickets'}, 'second': {'changes': '-Congress venue cancelled'},
    }}
    _collect_string_fields_with_overrides(projection, '', 120, collected, ALWAYS_SEMANTIC_FIELD_NAMES)
    assert dict(collected)['_website_events.second.changes'] == '-Congress venue cancelled'
    assert dict(collected)['_website_events.first.changes'] == '+Congress tickets'


# contract-test: supporting surface=rest_api assertions=workflows.website-change.retry
@pytest.mark.asyncio
async def test_true_leaf_check_without_a_message_destination_finishes_the_occurrence(monkeypatch):
    async def scan(payload, _context): return payload
    async def billing(**_kwargs): return 0
    async def precheck(*_args, **_kwargs): pass
    monkeypatch.setattr(adapter_module, 'sanitize_app_skill_output', scan)
    monkeypatch.setattr(adapter_module, '_precheck_workflow_skill_billing', precheck)
    monkeypatch.setattr(adapter_module, '_charge_workflow_skill_result', billing)
    definition = graph()
    # A valid graph can have a Send only on the condition's false branch.
    definition['edges'][-1]['branch'] = 'no'
    class Actions:
        async def send_chat_message(self, *_args): return {'status': 'completed'}
    service, registry = workflow_service(), Registry()
    workflow = service.create_workflow('alice', 'Draft change condition', definition)
    runner = WorkflowRunner(service, WorkflowAppSkillAdapter(registry=registry), Actions(), SimpleNamespace())
    await runner.run_workflow(workflow, 'alice', trigger_type='schedule')
    registry.text = B
    changed = await runner.run_workflow(workflow, 'alice', trigger_type='schedule')
    assert changed.status.value == 'completed'
    assert changed.node_runs[-1].output_summary['matched'] is True
    assert not any(r['kind'] == 'event' for r in service.repository._website_state.values())
    unchanged = await runner.run_workflow(workflow, 'alice', trigger_type='schedule')
    assert next(n for n in unchanged.node_runs if n.node_id == 'check').output_summary['matched'] is False


# contract-test: supporting surface=rest_api assertions=workflows.website-change.retry,workflows.website-change.lifecycle
def test_independent_conditions_own_only_their_destinations_and_pending_generations():
    definition = graph()
    definition['nodes'].extend([
        {'id': 'second', 'type': 'check', 'config': {'mode': 'exact', 'predicate': {'op': 'eq', 'left': '$nodes.read.output.has_changed', 'right': True}}},
        {'id': 'second_send', 'type': 'send_chat_message', 'config': {'title': 'Second condition', 'message': '{{steps.read.changes}}'}},
    ])
    definition['edges'].extend([{'from': 'send', 'to': 'second'}, {'from': 'second', 'to': 'second_send', 'branch': 'yes'}])
    service = workflow_service()
    workflow = service.create_workflow('alice', 'Independent conditions', definition)
    service.repository.save_run({'id': 'run-1', 'workflow_id': workflow.id, 'owner_hash': service.repository.get_workflow(workflow.id, 'alice')['owner_hash'], 'version_id': workflow.current_version_id, 'status': 'running'})
    store = WorkflowWebsiteChanges(service, workflow.id, 'alice', 'run-1', workflow.current_version_id)
    plan = website_plan(workflow.graph)['read']
    assert {c['node_id']: c['targets'] for c in plan['consumers']} == {'check': ['send'], 'second': ['second_send']}
    store.project('read', {'url': URL}, plan, raw(A))
    changed = store.project('read', {'url': URL}, plan, raw(B))
    first, second = changed['_website_events']['check'], changed['_website_events']['second']
    store.save_event_output(first, 'check', {'matched': False}, discard=True)
    retry = store.project('read', {'url': URL}, plan, raw(B))
    assert set(retry['_website_events']) == {'second'}
    workflow.graph.nodes[2].config['predicate']['right'] = False
    changed_plan = website_plan(workflow.graph)['read']
    retry = store.project('read', {'url': URL}, changed_plan, raw(B))
    assert retry['_website_events']['second']['id'] == second['id']
