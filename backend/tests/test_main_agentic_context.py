"""Fresh context selection and accepted prompt delivery use bounded shared APIs."""
# contract-test-file: infrastructure
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.apps.ai.processing import main_processor as main
from backend.apps.ai.processing.chat_direction import DirectionAuthority


@pytest.mark.asyncio
async def test_initial_preselection_reloads_exact_snapshots_and_never_invents_context(monkeypatch):
    from backend.apps.ai.processing import context_preselection as preselection
    request = SimpleNamespace(user_id='owner', chat_id='chat', is_external=False, is_incognito=False,
                              current_project=None, current_user_content='Fix the API', related_task_candidates=[])
    preprocessing = SimpleNamespace(relevant_rules=[{'id': 'rule', 'revision': 'r1'}], relevant_workflows=[])
    rules = AsyncMock(return_value=[])
    workflows = AsyncMock(return_value=[])
    monkeypatch.setattr(preselection, 'reload_preselected_rules', rules)
    monkeypatch.setattr(preselection, 'reload_preselected_workflows', workflows)
    monkeypatch.setattr(main.agentic_context, 'select_rule_guides', AsyncMock(side_effect=AssertionError('duplicate initial Jev')))
    monkeypatch.setattr(main.agentic_context, 'select_existing_workflows', AsyncMock(side_effect=AssertionError('duplicate initial Jev')))
    monkeypatch.setattr(main.agentic_context, 'selected_project_documents', AsyncMock(return_value=[]))
    monkeypatch.setattr(main, 'fetch_related_chat_summaries', AsyncMock(return_value=[]))
    monkeypatch.setattr(main, 'fetch_related_task_candidates', AsyncMock(return_value=[]))
    monkeypatch.setattr(main, 'select_related_work', AsyncMock(return_value=[]))
    section, guides = await main._load_main_agentic_context(
        request=request, task_id='task', preprocessing=preprocessing, directus=object(), cache=object(),
        secrets_manager=None, eligible_app_ids=['code'], vault_key_id='key', decision_model='jev',
        effective_instructions='focus phase', active_phase='phase', initial=True,
    )
    assert not guides
    assert 'rule' not in section
    assert rules.await_args.args[-1] == [{'id': 'rule', 'revision': 'r1'}]
    assert workflows.await_args.args[-1] == []


@pytest.mark.asyncio
async def test_authoritative_focus_change_reselects_against_effective_phase(monkeypatch):
    request = SimpleNamespace(user_id='owner', chat_id='chat', is_external=False, is_incognito=False,
                              current_project=None, current_user_content='Fix the API', related_task_candidates=[])
    rules = AsyncMock(return_value=[])
    monkeypatch.setattr(main.agentic_context, 'select_rule_guides', rules)
    monkeypatch.setattr(main.agentic_context, 'select_existing_workflows', AsyncMock(return_value=[]))
    monkeypatch.setattr(main.agentic_context, 'selected_project_documents', AsyncMock(return_value=[]))
    monkeypatch.setattr(main, 'fetch_related_chat_summaries', AsyncMock(return_value=[]))
    monkeypatch.setattr(main, 'fetch_related_task_candidates', AsyncMock(return_value=[]))
    monkeypatch.setattr(main, 'select_related_work', AsyncMock(return_value=[]))
    await main._load_main_agentic_context(
        request=request, task_id='task', preprocessing=SimpleNamespace(relevant_rules=[]), directus=object(), cache=object(),
        secrets_manager=None, eligible_app_ids=['code'], vault_key_id='key', decision_model='jev',
        effective_instructions='new authoritative phase', active_phase='test', initial=False,
    )
    assert rules.await_args.kwargs['effective_instructions'] == 'new authoritative phase'
    assert rules.await_args.kwargs['active_phase'] == 'test'
    assert rules.await_args.kwargs['eligible_app_ids'] == ['code']


@pytest.mark.asyncio
@pytest.mark.parametrize('cas_result', [0, 1])
async def test_direction_delivery_appends_only_after_atomic_current_turn_check(cas_result):
    request = SimpleNamespace(user_id='owner', chat_id='chat', message_id='turn',
                              message_history=[{'role': 'user', 'content': 'Fix the API'}])
    client = SimpleNamespace(eval=AsyncMock(return_value=cas_result))
    async def redis():
        return client
    cache = SimpleNamespace(client=redis(), _get_active_task_key=lambda chat: 'active-task:' + chat)
    authority = DirectionAuthority('owner', 'chat', 'turn', main.agentic_context.goal_revision(request.message_history))
    appended = []
    receipt = await main._deliver_direction_instruction(
        request=request, task_id='task', authority=authority, cache=cache, instruction='Return to API diagnosis',
        fingerprint='assessment', append=appended.append,
    )
    assert receipt.accepted == bool(cas_result)
    assert appended == (['Return to API diagnosis'] if cas_result else [])
    args = client.eval.await_args.args
    assert 'turn' in args and 'task' in args
    assert 'Return to API diagnosis' not in repr(args)


@pytest.mark.asyncio
async def test_goal_change_or_wrong_chat_cannot_deliver_correction():
    request = SimpleNamespace(user_id='owner', chat_id='chat', message_id='turn', message_history=[])
    receipt = await main._deliver_direction_instruction(
        request=request, task_id='task', authority=DirectionAuthority('owner', 'other', 'turn', 'goal'),
        cache=None, instruction='private', fingerprint='assessment', append=lambda value: pytest.fail('delivered stale'))
    assert not receipt.accepted
