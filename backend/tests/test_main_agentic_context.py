"""Fresh context selection and accepted prompt delivery use bounded shared APIs."""
# contract-test-file: infrastructure
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.apps.ai.processing import main_processor as main
from backend.apps.ai.processing.chat_direction import DirectionAuthority


@pytest.mark.asyncio
async def test_related_chat_and_task_fetches_overlap_before_selection(monkeypatch):
    request = SimpleNamespace(user_id="owner", chat_id="chat", is_external=False, is_incognito=False,
                              current_project=None, current_user_content="Fix the API", related_task_candidates=[])
    chat_started, task_started = asyncio.Event(), asyncio.Event()
    release_chat, release_task = asyncio.Event(), asyncio.Event()
    chat_completed = asyncio.Event()

    async def chats(*args):
        chat_started.set()
        await release_chat.wait()
        chat_completed.set()
        return []

    async def tasks(*args, **kwargs):
        task_started.set()
        await release_task.wait()
        return []

    selection = AsyncMock(return_value=[])
    monkeypatch.setattr(main.agentic_context, "fresh_project", AsyncMock(return_value=None))
    monkeypatch.setattr(main.agentic_context, "select_rule_guides", AsyncMock(return_value=[]))
    monkeypatch.setattr(main.agentic_context, "select_existing_workflows", AsyncMock(return_value=[]))
    monkeypatch.setattr(main.agentic_context, "selected_project_documents", AsyncMock(return_value=[]))
    monkeypatch.setattr(main, "fetch_related_chat_summaries", chats)
    monkeypatch.setattr(main, "fetch_related_task_candidates", tasks)
    monkeypatch.setattr(main, "select_related_work", selection)

    loading = asyncio.create_task(main._load_main_agentic_context(
        request=request, task_id="task", preprocessing=SimpleNamespace(), directus=object(), cache=object(),
        secrets_manager=None, eligible_app_ids=[], vault_key_id=None, decision_model="jev",
        effective_instructions="", active_phase="", initial=False,
    ))
    try:
        await asyncio.wait_for(asyncio.gather(chat_started.wait(), task_started.wait()), timeout=1)
        assert selection.await_count == 0
        release_chat.set()
        await asyncio.wait_for(chat_completed.wait(), timeout=1)
        assert selection.await_count == 0
        release_task.set()
        await asyncio.wait_for(loading, timeout=1)
        selection.assert_awaited_once()
    finally:
        release_chat.set()
        release_task.set()
        if not loading.done():
            await loading


@pytest.mark.asyncio
async def test_related_fetch_failure_waits_for_sibling_and_discards_all_related_context(monkeypatch):
    request = SimpleNamespace(user_id="owner", chat_id="chat", is_external=False, is_incognito=False,
                              current_project=None, current_user_content="Fix the API", related_task_candidates=[])
    task_started, task_settled = asyncio.Event(), asyncio.Event()
    release_task = asyncio.Event()

    async def chats(*args):
        await task_started.wait()
        raise RuntimeError("chat discovery unavailable")

    async def tasks(*args, **kwargs):
        task_started.set()
        await release_task.wait()
        task_settled.set()
        return []

    selection = AsyncMock(return_value=[])
    monkeypatch.setattr(main.agentic_context, "fresh_project", AsyncMock(return_value=None))
    monkeypatch.setattr(main.agentic_context, "select_rule_guides", AsyncMock(return_value=[]))
    monkeypatch.setattr(main.agentic_context, "select_existing_workflows", AsyncMock(return_value=[]))
    monkeypatch.setattr(main.agentic_context, "selected_project_documents", AsyncMock(return_value=[]))
    monkeypatch.setattr(main, "fetch_related_chat_summaries", chats)
    monkeypatch.setattr(main, "fetch_related_task_candidates", tasks)
    monkeypatch.setattr(main, "select_related_work", selection)

    loading = asyncio.create_task(main._load_main_agentic_context(
        request=request, task_id="task", preprocessing=SimpleNamespace(), directus=object(), cache=object(),
        secrets_manager=None, eligible_app_ids=[], vault_key_id=None, decision_model="jev",
        effective_instructions="", active_phase="", initial=False,
    ))
    try:
        await asyncio.wait_for(task_started.wait(), timeout=1)
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(asyncio.shield(loading), timeout=0.05)
        assert not task_settled.is_set()
        assert selection.await_count == 0
        release_task.set()
        await asyncio.wait_for(loading, timeout=1)
        assert task_settled.is_set()
        assert selection.await_count == 0
    finally:
        release_task.set()
        if not loading.done():
            await loading


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

# contract-test: supporting surface=rest_api assertions=app-memories.selection.source-scoped,app-memories.transparency.loaded-set
@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["valid", "revoked", "invalid", "duplicate", "full"])
async def test_project_memories_use_exact_bodies_only_with_current_activation(monkeypatch, case):
    request = SimpleNamespace(user_id="owner", chat_id="chat", is_external=False, is_incognito=False,
                              current_project={"project_id":"project"}, current_user_content="Build the API", related_task_candidates=[])
    binding = {"project_id":"project", "activation_id":"activation"}
    monkeypatch.setattr(main.agentic_context, "fresh_project", AsyncMock(side_effect=[binding, None if case == "revoked" else binding]))
    from backend.shared.python_utils.memory_loader import MemoryDefinition
    selected = [MemoryDefinition(id="memory", title="API address", description="Staging address", when_to_use="API work",
        body="The staging API uses port 8001.", revision="a" * 64, source="project", project_id="project")] if case == "duplicate" else []
    if case == "full":
        selected = [MemoryDefinition(id=f"app:code:memory-{i}", title="Existing guidance", description="Practice", when_to_use="API work",
            body="Existing guidance", revision="a" * 64, source="app", app_id="code") for i in range(24)]
    monkeypatch.setattr(main.agentic_context, "select_rule_guides", AsyncMock(return_value=selected))
    monkeypatch.setattr(main.agentic_context, "select_existing_workflows", AsyncMock(return_value=[]))
    document = {"kind":"memory", "item_id":"memory", "title":"API address", "document":"The staging API uses port 8001."}
    if case == "invalid":
        document["title"] = None
    monkeypatch.setattr(main.agentic_context, "selected_project_documents", AsyncMock(return_value=[document]))
    monkeypatch.setattr(main, "fetch_related_chat_summaries", AsyncMock(return_value=[]))
    monkeypatch.setattr(main, "fetch_related_task_candidates", AsyncMock(return_value=[]))
    monkeypatch.setattr(main, "select_related_work", AsyncMock(return_value=[]))
    section, memories = await main._load_main_agentic_context(request=request, task_id="task",
        preprocessing=SimpleNamespace(relevant_rules=[]), directus=object(), cache=object(), secrets_manager=None,
        eligible_app_ids=[], vault_key_id="key", decision_model="jev", effective_instructions="Work on the API", active_phase="", initial=False)
    if case in {"valid", "duplicate"}:
        assert len(memories) == 1 and memories[0].source == "project"
        assert memories[0].id == "project:project:memory"
        assert memories[0].body == document["document"]
        assert section.count(document["document"]) == 1
    elif case == "full":
        assert len(memories) == 24 and all(memory.source == "app" for memory in memories)
        assert document["document"] not in section
    else:
        assert memories == [] and document["document"] not in section


# contract-test: supporting surface=gui.web assertions=ai-model-routing.preprocessing.early-resolution
@pytest.mark.asyncio
@pytest.mark.parametrize("selected_revision", [None, "r1", "stale"])
async def test_stage_two_related_selection_revalidates_without_third_inference(monkeypatch, selected_revision):
    from backend.apps.ai.processing.related_work import RelatedWorkCandidate
    request = SimpleNamespace(user_id="owner", chat_id="chat", is_external=False, is_incognito=False,
                              current_project=None, current_user_content="Fix it", related_task_candidates=[])
    candidate = RelatedWorkCandidate(id="source", kind="task", owner_id="owner", project_id=None,
                                     text="Applicable fix", revision="r1", source="test", authorized=True,
                                     status="in_progress")
    snapshots = [] if selected_revision is None else [{"id": "source", "kind": "task", "revision": selected_revision}]
    for name in ("fresh_project", "select_rule_guides", "select_existing_workflows", "selected_project_documents"):
        monkeypatch.setattr(main.agentic_context, name, AsyncMock(return_value=[]))
    chats, tasks, selector = AsyncMock(return_value=[]), AsyncMock(return_value=[candidate]), AsyncMock()
    monkeypatch.setattr(main, "fetch_related_chat_summaries", chats)
    monkeypatch.setattr(main, "fetch_related_task_candidates", tasks)
    monkeypatch.setattr(main, "select_related_work", selector)
    section, _ = await main._load_main_agentic_context(
        request=request, task_id="task", preprocessing=SimpleNamespace(relevant_related_work=snapshots),
        directus=object(), cache=object(), secrets_manager=None, eligible_app_ids=[], vault_key_id=None,
        decision_model="jev", effective_instructions="", active_phase="", initial=True,
    )
    selector.assert_not_awaited()
    assert ("Applicable fix" in section) is (selected_revision == "r1")
    if selected_revision is None:
        chats.assert_not_awaited()
        tasks.assert_not_awaited()
