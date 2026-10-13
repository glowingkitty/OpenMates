"""Regression coverage for JDPC5: short follow-ups must not fake app results."""

import asyncio
import importlib.util
from pathlib import Path

import pytest

from backend.apps.ai.llm_providers.types import StreamChunkType, UnifiedStreamChunk
from backend.apps.ai.processing.suggested_followup_stream import SuggestedFollowupStream
from backend.apps.ai.utils.main_processing_failure import (
    main_processing_failure,
    main_processing_failure_reason,
)
from backend.apps.ai.utils.tool_protocol_guard import (
    ToolProtocolGuard,
    ToolProtocolRecoveryState,
    build_tool_protocol_recovery_messages,
    is_internal_tool_protocol,
)

@pytest.fixture(autouse=True)
def real_paragraph_aggregation(monkeypatch):
    """Use real streaming code even beside legacy main-processor import stubs."""
    from backend.apps.ai.utils import tool_protocol_guard

    path = Path(__file__).parents[1] / "apps/ai/utils/stream_utils.py"
    spec = importlib.util.spec_from_file_location("_protocol_test_stream_utils", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(tool_protocol_guard, "aggregate_paragraphs", module.aggregate_paragraphs)
    types_path = Path(__file__).parents[1] / "apps/ai/llm_providers/types.py"
    types_spec = importlib.util.spec_from_file_location("_protocol_test_types", types_path)
    real_types = importlib.util.module_from_spec(types_spec)
    types_spec.loader.exec_module(real_types)
    for name in ("StreamChunkType", "UnifiedStreamChunk"):
        monkeypatch.setattr(tool_protocol_guard, name, getattr(real_types, name))
        monkeypatch.setitem(globals(), name, getattr(real_types, name))



PROTOCOL = '```toon\napp_id: news\nskill_id: search\nstatus: finished\nresult_count: 1\n```'


def run_guard(chunks):
    guard = ToolProtocolGuard()

    async def run():
        async def source():
            for chunk in chunks:
                yield chunk
        return [chunk async for chunk in guard.filter(source())]

    return guard, asyncio.run(run())


# contract-test: supporting surface=cli assertions=chats.streaming.progressive-presentation
def test_first_plain_text_reaches_consumer_before_paragraph_or_source_end():
    guard = ToolProtocolGuard()
    seen = []

    async def source():
        yield 'Here is the answer'
        assert seen == ['Here is the answer']
        yield ' in one paragraph.'

    async def run():
        async for chunk in guard.filter(source()):
            seen.append(chunk)

    asyncio.run(run())
    assert ''.join(seen) == 'Here is the answer in one paragraph.'
    assert not guard.detected


# contract-test: supporting surface=cli assertions=chats.streaming.progressive-presentation
def test_tiny_provider_tokens_are_coalesced_before_first_visible_text():
    seen = []

    async def source():
        yield 'Hi'
        assert seen == []
        yield ' there!'
        assert seen == ['Hi there!']
        yield ' More text.'

    async def run():
        async for chunk in ToolProtocolGuard().filter(source()):
            seen.append(chunk)

    asyncio.run(run())
    assert seen == ['Hi there!', ' More text.']


# contract-test: supporting surface=gui.web assertions=chats.streaming.progressive-presentation
def test_only_first_plain_fragment_is_released_before_line_parsers():
    guard, output = run_guard(['First text', ' continues', '\n| Name | Value |', '\n| A | B |'])
    assert output == ['First text', ' continues\n| Name | Value |\n| A | B |']
    assert not guard.detected

    table = '| Name | Value |\n| --- | --- |\n| A | B |'
    guard, output = run_guard([table[i:i + 2] for i in range(0, len(table), 2)])
    assert output == [table]
    assert not guard.detected


# contract-test: supporting surface=gui.web assertions=app-skills.execution.registered-validated,chats.streaming.progressive-presentation
@pytest.mark.parametrize('width', [1, 2, 5, 31, 9000])
def test_early_prose_does_not_leak_later_split_protocol_or_xml(width):
    prefix = 'Verified introduction before protocol. '
    suffix = 'This claim came from an invented result.'
    source = prefix + PROTOCOL + '\n' + suffix
    guard, output = run_guard([source[i:i + width] for i in range(0, len(source), width)])
    assert guard.detected
    assert ''.join(output) == prefix

    xml = prefix + '<ToOl_CaLl>{"tool":"search","input":"private"}</TOOL_CALL>' + ' Safe ending.'
    guard, output = run_guard([xml[i:i + width] for i in range(0, len(xml), width)])
    assert not guard.detected
    assert ''.join(output) == prefix + ' Safe ending.'


# contract-test: supporting surface=gui.web assertions=app-skills.execution.registered-validated
def test_incomplete_xml_and_fence_are_suppressed_after_safe_prefix():
    prefix = 'Safe text. '
    guard, output = run_guard([prefix + '<tool_', 'call>{"tool":"search"}'])
    assert not guard.detected
    assert ''.join(output) == prefix

    guard, output = run_guard([prefix + '```to', 'ol_code\n{"tool":"search"}'])
    assert guard.detected
    assert ''.join(output) == prefix


# contract-test: supporting surface=gui.web assertions=app-skills.execution.registered-validated
def test_real_json_code_citation_and_embed_reference_survive_split_stream():
    answer = (
        'The source says [example](embed:source-abc).\n'
        '> [Quoted title](embed:source-abc)\n'
        '```json\n{"type":"app_skill_use","embed_ref":"source-abc"}\n```'
    )
    guard, output = run_guard([answer[i:i + 3] for i in range(0, len(answer), 3)])
    assert not guard.detected
    assert ''.join(output) == answer


# contract-test: supporting surface=gui.web assertions=chats.streaming.ordered-final
def test_error_thought_and_metadata_tokens_keep_downstream_boundaries():
    for marker in ('[ERROR: private detail]', '{thought}private reasoning'):
        guard, output = run_guard([marker[:2], marker[2:7], marker[7:]])
        assert not guard.detected
        assert output == [marker]

    text = (
        'Public answer [PERSON_1] with [source](embed:source-abc).\n'
        '<<suggested_followup_message>>Ask next<</suggested_followup_message>>'
    )
    guard, output = run_guard([text[i:i + 2] for i in range(0, len(text), 2)])
    assert not guard.detected
    assert ''.join(output) == text
    downstream = SuggestedFollowupStream()
    assert ''.join(downstream.feed(chunk) for chunk in output) == (
        'Public answer [PERSON_1] with [source](embed:source-abc).\n'
    )
    assert downstream.finish() == ''
    assert downstream.suggestion == 'Ask next'


# contract-test: supporting surface=gui.web assertions=app-skills.execution.registered-validated
def test_long_xml_tool_call_never_reaches_consumer():
    xml = '<tool_call>' + ('private' * 10000) + '</tool_call>'
    guard, output = run_guard([xml[i:i + 997] for i in range(0, len(xml), 997)])
    assert not guard.detected
    assert output == []


# contract-test: supporting surface=cli assertions=chats.streaming.progressive-presentation
def test_safe_prose_is_yielded_before_source_error_without_final_flush():
    guard = ToolProtocolGuard()
    seen = []

    async def source():
        yield 'Safe answer'
        raise RuntimeError('provider failed')

    async def run():
        async for chunk in guard.filter(source()):
            seen.append(chunk)

    with pytest.raises(RuntimeError, match='provider failed'):
        asyncio.run(run())
    assert seen == ['Safe answer']


# contract-test: supporting surface=cli assertions=chats.streaming.progressive-presentation
def test_cancelling_after_first_safe_chunk_does_not_flush_pending_protocol():
    guard = ToolProtocolGuard()
    seen = []

    async def source():
        yield 'Safe answer'
        yield '```to'
        yield 'ol_code\n{"tool":"search"}'

    async def run():
        stream = guard.filter(source())
        seen.append(await anext(stream))
        await stream.aclose()

    asyncio.run(run())
    assert seen == ['Safe answer']
    assert not guard.detected


# contract-test: supporting surface=gui.web assertions=app-skills.execution.registered-validated,web-search.surface-parity
@pytest.mark.parametrize('width', [1, 2, 7, 32, 4096])
def test_internal_results_never_stream_or_become_code(width):
    source = PROTOCOL + '\n\nUnverified claims copied from prior results.'
    usage = object()
    guard, output = run_guard([source[i:i + width] for i in range(0, len(source), width)] + [usage])
    assert guard.detected
    assert output == [usage]


# contract-test: supporting surface=gui.web assertions=app-skills.execution.registered-validated
@pytest.mark.parametrize('ending', ['```', ''])
def test_long_or_interrupted_protocol_is_not_published(ending):
    content = '```toon\napp_id: news\nskill_id: search\nresults: ' + 'x' * 70000 + '\n' + ending
    guard, output = run_guard([content])
    assert guard.detected
    assert output == []


# contract-test: supporting surface=gui.web assertions=app-skills.execution.registered-validated
def test_typed_provider_text_is_filtered_but_native_calls_and_usage_survive():
    native_call = object()
    usage = object()
    guard, output = run_guard([
        UnifiedStreamChunk(type=StreamChunkType.TEXT, content=PROTOCOL), native_call, usage,
    ])
    assert guard.detected
    assert output == [native_call, usage]


# contract-test: supporting surface=gui.web assertions=app-skills.execution.registered-validated
def test_safe_text_before_native_call_is_retained_when_protocol_tail_is_suppressed():
    safe_text = 'I will use the verified result below.\n\n'
    native_call = object()
    guard, output = run_guard([safe_text, native_call, PROTOCOL])
    recovery = ToolProtocolRecoveryState()

    assert guard.detected
    assert output == [safe_text, native_call]
    assert recovery.action(
        detected=guard.detected,
        native_call_count=1,
        safe_text=safe_text,
        has_retry_iteration=True,
    ) == 'ignore'


# contract-test: supporting surface=gui.web assertions=app-skills.execution.registered-validated
@pytest.mark.parametrize('text', [
    'A summary of the previous results.\n\nNo new search is needed.',
    '```python\nprint("app_id: news")\n```',
    '```toon\nname: Example\nitems[2]: one,two\n```',
    '```json\n{"type":"app_skill_use","embed_id":"real-reference"}\n```',
])
def test_ordinary_answers_code_and_references_are_preserved(text):
    guard, output = run_guard([text[i:i + 2] for i in range(0, len(text), 2)])
    assert not guard.detected
    assert ''.join(output) == text


# contract-test: supporting surface=gui.web assertions=app-skills.execution.registered-validated
def test_internal_protocol_signature_covers_result_envelopes_without_tool_field():
    assert is_internal_tool_protocol('toon', 'app_id: news\nskill_id: search\nquery: latest')
    assert is_internal_tool_protocol('toon', 'tool: news-search\ninput: example')
    assert is_internal_tool_protocol('tool_code', '{}')
    assert not is_internal_tool_protocol('toon', 'app_id: demo\nname: Example')


# contract-test: supporting surface=gui.web assertions=app-skills.execution.registered-validated
def test_protocol_recovery_state_is_bounded_and_keeps_safe_text():
    recovery = ToolProtocolRecoveryState()

    first_action = recovery.action(
        detected=True,
        native_call_count=0,
        safe_text='A complete safe paragraph.\n\n',
        has_retry_iteration=True,
    )
    second_action = recovery.action(
        detected=True,
        native_call_count=0,
        safe_text='',
        has_retry_iteration=True,
    )

    assert first_action == 'retry'
    assert second_action == 'failure'
    assert recovery.attempted is True
    assert recovery.preserved_safe_text is True
    assert main_processing_failure_reason(
        main_processing_failure('protocol_guard')
    ) == 'protocol_guard'

# contract-test: supporting surface=gui.web assertions=app-skills.execution.registered-validated
def test_protocol_without_any_safe_text_gets_one_bounded_restart():
    recovery = ToolProtocolRecoveryState()

    first_action = recovery.action(
        detected=True,
        native_call_count=0,
        safe_text='\n',
        has_retry_iteration=True,
    )
    second_action = recovery.action(
        detected=True,
        native_call_count=0,
        safe_text='',
        has_retry_iteration=True,
    )

    assert first_action == 'retry'
    assert second_action == 'error'
    restart_messages = build_tool_protocol_recovery_messages('')
    assert len(restart_messages) == 1
    assert restart_messages[0]['role'] == 'user'
    restart_prompt = restart_messages[0]['content']
    assert 'previous assistant output was suppressed' in restart_prompt
    assert 'If a needed tool result is unavailable' in restart_prompt
    assert main_processing_failure_reason(
        main_processing_failure('protocol_guard')
    ) == 'protocol_guard'
