"""Whole-document delivery, discovery and revocation for internal Memory tools."""

# contract-test-file: infrastructure
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.apps.ai.processing.memory_tools import MemoryToolRuntime, authorized_memory_catalog
from backend.shared.python_utils.memory_loader import MemoryDefinition, load_app_memories


def runtime(documents, cache=None, **scope):
    async def catalog():
        return list(documents)
    return MemoryToolRuntime(catalog=catalog, cache=cache, **scope)


# contract-test: supporting surface=rest_api assertions=app-memories.selection.source-scoped,app-memories.transparency.loaded-set
@pytest.mark.asyncio
async def test_find_then_load_complete_diagram_with_dependencies_and_metadata_only_cache():
    documents = load_app_memories(["diagrams", "code", "design"])
    cache = SimpleNamespace(get=AsyncMock(return_value=None), set=AsyncMock(return_value=True))
    loader = runtime(documents, cache, owner_id="u", chat_id="c", turn_id="t")
    found = await loader.execute("find_memories", {"query": "architecture"})
    assert any(m["id"] == "app:diagrams:type-architecture" for m in found["memories"])
    assert all("body" not in m for m in found["memories"])
    assert loader.prompt == ""
    result = await loader.execute("load_memories", {
        "memory_ids": ["app:diagrams:type-architecture"], "diagram_variant": "minimal_dark"})
    from backend.apps.diagrams.diagram_guidance import diagram_guidance_prompt
    expected = diagram_guidance_prompt(["type-architecture"], variant="minimal_dark")
    assert loader.prompt == expected
    assert result["status"] == "loaded"
    assert loader.applied[0].id == "app:diagrams:type-architecture"
    assert "<svg" not in str(cache.set.call_args)
    assert "Diagram Design drawing context" not in str(cache.set.call_args)
    await loader.execute("load_memories", {"memory_ids": ["app:diagrams:type-architecture"]})
    assert loader.prompt == expected
    assert len(loader.applied) == 1


# contract-test: supporting surface=rest_api assertions=app-memories.selection.source-scoped
@pytest.mark.asyncio
async def test_generic_guide_full_body_and_continuation_restore_are_turn_scoped():
    documents = load_app_memories(["code"])
    stored = {}
    async def get(key):
        return stored.get(key)
    async def set_value(key, value, **_kwargs):
        stored[key] = value
        return True
    cache = SimpleNamespace(get=get, set=set_value)
    scope = dict(owner_id="u", chat_id="c", turn_id="t")
    first = runtime(documents, cache, **scope)
    await first.execute("load_memories", {"memory_ids": ["app:code:python"]})
    python = next(m for m in documents if m.id == "app:code:python")
    assert python.body in first.prompt
    continuation = runtime(documents, cache, **scope)
    await continuation.refresh()
    assert continuation.prompt == first.prompt
    other_turn = runtime(documents, cache, **{**scope, "turn_id": "other"})
    await other_turn.refresh()
    assert other_turn.prompt == ""
    assert python.body not in str(stored)


# contract-test: supporting surface=rest_api assertions=app-memories.selection.source-scoped,app-memories.precedence.obligations
@pytest.mark.asyncio
async def test_unknown_ids_private_sources_and_revoked_revisions_are_not_loaded():
    project = MemoryDefinition(id="project:p:guide", title="Conventions", description="Project guide",
        when_to_use="Project work", body="Sensitive project conventions", revision="a" * 64,
        source="project", project_id="p")
    docs = [project]
    loader = runtime(docs)
    for identifier in ["../../secrets", "personal:all", "app:unknown:guide"]:
        with pytest.raises(ValueError):
            await loader.execute("load_memories", {"memory_ids": [identifier]})
    await loader.execute("load_memories", {"memory_ids": [project.id]})
    assert project.body in loader.prompt
    docs[:] = [project.model_copy(update={"revision": "b" * 64, "body": "New unselected version"})]
    await loader.refresh()
    assert loader.prompt == "" and loader.applied == []


# contract-test: supporting surface=rest_api assertions=app-memories.selection.source-scoped
@pytest.mark.asyncio
async def test_project_authority_is_rechecked_after_document_lookup(monkeypatch):
    from backend.apps.ai.processing import agentic_context, rule_context
    monkeypatch.setattr(agentic_context, "fresh_project", AsyncMock(side_effect=[
        {"project_id": "p", "activation_id": "first"}, None]))
    monkeypatch.setattr(rule_context, "authorized_project_memory_documents", AsyncMock(return_value=[{
        "id": "guide", "source": "project", "project_id": "p", "document":
        "---\ntitle: Project\ndescription: Private\nwhen_to_use: Project work\n---\nPrivate body",
    }]))
    request = SimpleNamespace(user_id="u", is_external=False, is_incognito=False, is_anonymous=False,
                              custom_rule_documents=[])
    catalog = await authorized_memory_catalog(request, object(), object(), ["code"])
    assert catalog and all(m.source == "app" for m in catalog)


# contract-test: supporting surface=rest_api assertions=chats.rendering.assistant-document-convergence,app-memories.selection.source-scoped
@pytest.mark.asyncio
async def test_native_diagram_guard_withholds_missing_context_and_preserves_prose():
    from pathlib import Path
    from backend.apps.ai.processing.memory_tools import NativeDiagramContextGuard
    source = (Path(__file__).parents[1] / "apps/ai/testing/fixtures/diagram_html_web.html").read_text()
    async def stream():
        yield "Already published explanation.\n\n"
        yield "```openmates_diagram\n" + source[:100]
        yield source[100:] + "\n```"
    missing = NativeDiagramContextGuard([])
    assert [chunk async for chunk in missing.filter(stream())] == ["Already published explanation.\n\n"]
    assert missing.required_type == "type-architecture"
    prepared = NativeDiagramContextGuard(["type-architecture"])
    output = "".join([chunk async for chunk in prepared.filter(stream())])
    assert source in output and prepared.required_type is None


# contract-test: supporting surface=rest_api assertions=app-memories.selection.source-scoped,app-memories.privacy.client-encrypted
def test_legacy_native_segments_cannot_reintroduce_preselected_or_on_demand_memories():
    from backend.apps.ai.processing.memory_tools import native_memory_context_matches
    for body in ("--- On-demand Memory context ---\nPrivate text", "--- Memory: project:p:guide | Private text"):
        assert not native_memory_context_matches({"events": [{"system_suffix": body}]}, "")
    assert native_memory_context_matches({"events": [{"system_suffix": "Ordinary public context"}]}, "")


# contract-test: supporting surface=rest_api assertions=app-memories.precedence.obligations,chats.rendering.assistant-document-convergence
@pytest.mark.asyncio
@pytest.mark.parametrize("fence", [
    "```text\nUser Query\n    ▼\n[Assistant] ──(code)──► [Python Runtime]\n```",
    "```\n[Question]\n    |\n    v\n[Assistant] --> [Result]\n```",
    "```mermaid\nflowchart TD\nAssistant --> Runtime\n```",
])
async def test_unsolicited_fenced_diagrams_require_native_repair_but_explicit_source_survives(fence):
    from backend.apps.ai.processing.memory_tools import NativeDiagramContextGuard
    async def stream():
        yield "Published explanation.\n\n"
        yield fence[:35]
        yield fence[35:]
    guard = NativeDiagramContextGuard([])
    assert [chunk async for chunk in guard.filter(stream())] == ["Published explanation.\n\n"]
    assert guard.required_type == "type-flowchart" and guard.reason == "non_native_diagram"
    preloaded = NativeDiagramContextGuard(["type-architecture"])
    assert [chunk async for chunk in preloaded.filter(stream())] == ["Published explanation.\n\n"]
    assert preloaded.required_type == "type-architecture"
    explicit = NativeDiagramContextGuard([], user_request="Give me source code for this flow.")
    assert "".join([chunk async for chunk in explicit.filter(stream())]) == "Published explanation.\n\n" + fence
    unavailable = NativeDiagramContextGuard([], native_available=False)
    assert "".join([chunk async for chunk in unavailable.filter(stream())]) == "Published explanation.\n\n" + fence


# contract-test: supporting surface=rest_api assertions=chats.rendering.assistant-document-convergence
@pytest.mark.asyncio
@pytest.mark.parametrize("fence", ["```python\nnodes = ['a', 'b']\nprint(nodes)\n```", "```text\nsrc/\n├── app.py\n└── tests/\n```"])
async def test_native_admission_preserves_programming_and_file_trees(fence):
    from backend.apps.ai.processing.memory_tools import NativeDiagramContextGuard
    async def stream():
        yield fence
    guard = NativeDiagramContextGuard([])
    assert [chunk async for chunk in guard.filter(stream())] == [fence]
    assert guard.required_type is None


# contract-test: supporting surface=rest_api assertions=app-memories.precedence.obligations
@pytest.mark.parametrize("user_request,allowed", [
    ("Draw this in Mermaid", True), ("Return PlantUML", True),
    ("Give me source code for this flow", True),
    ("Do not include source code", False), ("No Mermaid; use a native diagram", False),
    ("What open source libraries can do this?", False),
    ("Avoid ASCII, but return Mermaid source", True),
])
def test_diagram_source_intent_preserves_affirmative_requests_and_negation(user_request, allowed):
    from backend.apps.ai.processing.memory_tools import diagram_source_requested
    assert diagram_source_requested(user_request) is allowed


# contract-test: supporting surface=rest_api assertions=chats.rendering.assistant-document-convergence
def test_text_diagram_admission_handles_long_plain_text_separators():
    from backend.apps.ai.processing.memory_tools import _text_diagram_type
    assert _text_diagram_type("text", "[First]\n" + "-" * 50_000 + "\n[Second]") is None
    assert _text_diagram_type("text", "[First] > ---- [Second]\nPlain text\nMore text") is None


# contract-test: supporting surface=rest_api assertions=app-memories.precedence.obligations,chats.rendering.assistant-document-convergence
@pytest.mark.asyncio
async def test_prose_only_output_never_recovers_to_a_native_diagram():
    from backend.apps.ai.processing.memory_tools import NativeDiagramContextGuard
    source = (Path(__file__).parents[1] / "apps/ai/testing/fixtures/diagram_html_web.html").read_text()
    for fence in ("```text\n[Assistant]\n    ▼\n[Runtime] --> [Answer]\n```",
                  "```openmates_diagram\n" + source + "\n```", "```openmates_diagram\n" + source):
        async def stream():
            yield "Published prose.\n\n"
            yield fence
        guard = NativeDiagramContextGuard(["type-architecture"], user_request="Answer in prose only, without any diagram.")
        assert [chunk async for chunk in guard.filter(stream())] == ["Published prose.\n\n"]
        assert guard.reason == "unrequested_diagram"
