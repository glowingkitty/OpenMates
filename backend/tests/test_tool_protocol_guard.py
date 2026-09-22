"""Regression coverage for JDPC5: short follow-ups must not fake app results."""

import asyncio
import importlib.util
from pathlib import Path

import pytest

from backend.apps.ai.llm_providers.types import StreamChunkType, UnifiedStreamChunk
from backend.apps.ai.utils.main_processing_failure import (
    main_processing_failure,
    main_processing_failure_reason,
)
from backend.apps.ai.utils.tool_protocol_guard import (
    ToolProtocolGuard,
    ToolProtocolRecoveryState,
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
def test_protocol_without_any_safe_text_remains_a_model_error():
    recovery = ToolProtocolRecoveryState()

    action = recovery.action(
        detected=True,
        native_call_count=0,
        safe_text='\n',
        has_retry_iteration=True,
    )

    assert action == 'error'
    assert main_processing_failure_reason(
        main_processing_failure('protocol_guard')
    ) == 'protocol_guard'


# contract-test: supporting surface=gui.web assertions=app-skills.execution.registered-validated
def test_main_processor_wires_guard_failures_to_structured_terminal_marker():
    source = (
        Path(__file__).parents[1] / 'apps/ai/processing/main_processor.py'
    ).read_text()

    assert 'protocol_recovery_action == "failure"' in source
    assert source.count('yield main_processing_failure("protocol_guard")') == 3
    assert "refusing an orphaned continuation" in source
