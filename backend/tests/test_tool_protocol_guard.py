"""Regression coverage for JDPC5: short follow-ups must not fake app results."""

import asyncio
import importlib.util
from pathlib import Path

import pytest

from backend.apps.ai.llm_providers.types import StreamChunkType, UnifiedStreamChunk
from backend.apps.ai.utils.tool_protocol_guard import (
    ToolProtocolGuard,
    is_internal_tool_protocol,
    recovery_search_tools,
    required_fresh_search_tools,
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


# contract-test: supporting surface=gui.web assertions=app-skills.execution.registered-validated,web-search.surface-parity
def test_follow_up_recovery_requires_original_news_route_not_added_companions():
    tools = [{'type': 'function', 'function': {'name': name}} for name in [
        'news-search', 'web-search', 'images-search', 'mail-send', 'activate_focus_mode',
    ]]
    assert recovery_search_tools(tools, ['news-search']) == [tools[0]]
    assert recovery_search_tools(tools, ['mail-send']) == []
    assert recovery_search_tools(tools, []) == []
    assert recovery_search_tools(tools[1:], ['news-search']) == []


# contract-test: supporting surface=gui.web assertions=app-skills.execution.registered-validated,web-search.surface-parity
@pytest.mark.parametrize("fresh,calls,disabled,expected", [
    (True, 0, False, True),
    (False, 0, False, False),  # Summaries/comparisons may reuse existing results.
    ("true", 0, False, False),  # Only a validated boolean enables enforcement.
    (True, 1, False, False),  # Answer normally after retrieval.
    (True, 0, True, False),  # Never override disabled tools or exhausted budgets.
])
def test_fresh_search_requires_original_route_only_until_first_call(fresh, calls, disabled, expected):
    tools = [{"function": {"name": name}} for name in ["news-search", "web-search", "mail-send"]]
    assert required_fresh_search_tools(
        tools, ["news-search", "mail-send"], requires_fresh_search=fresh,
        total_skill_calls=calls, tools_disabled=disabled,
    ) == ([tools[0]] if expected else [])
