"""Published Memories and exact source/revision compatibility."""
import pytest
from backend.shared.python_utils.memory_loader import load_app_memories, parse_memory_md, memories_prompt

DOCUMENT = "---\ntitle: Mobile audience\ndescription: Most readers use phones.\nwhen_to_use: Designing this project.\n---\nMost readers use phones.\n"

# contract-test: supporting surface=rest_api assertions=app-memories.definition.context-documents,app-memories.catalog.no-typed-types
def test_shipped_memory_catalog_is_read_only_app_scoped_and_whole_documents():
    memories = load_app_memories(["code", "design"])
    assert len(memories) == 6
    assert {memory.title for memory in memories} >= {"Svelte best practices", "Mobile first design"}
    assert all(memory.source == "app" and memory.id.startswith(f"app:{memory.app_id}:") for memory in memories)
    assert len(load_app_memories(["code"])) == 4

# contract-test: supporting surface=rest_api assertions=app-memories.compatibility.legacy-documents
def test_canonical_memory_wins_same_legacy_identity_without_duplication(tmp_path):
    for directory in ("rules", "memories"):
        path = tmp_path / "code" / directory
        path.mkdir(parents=True)
        (path / "audience.md").write_text(DOCUMENT + ("Updated.\n" if directory == "memories" else ""))
    memories = load_app_memories(["code"], apps_root=tmp_path)
    assert len(memories) == 1
    assert memories[0].id == "app:code:audience"
    assert "Updated." in memories[0].body

# contract-test: supporting surface=rest_api assertions=app-memories.selection.source-scoped
@pytest.mark.parametrize("directory", ["rules", "memories"])
def test_published_memory_cannot_escape_its_app(directory, tmp_path):
    path = tmp_path / "code" / directory
    path.mkdir(parents=True)
    private = tmp_path / "private.md"
    private.write_text(DOCUMENT)
    (path / "audience.md").symlink_to(private)
    with pytest.raises(ValueError):
        load_app_memories(["code"], apps_root=tmp_path)

# contract-test: supporting surface=rest_api assertions=app-memories.precedence.obligations
def test_memory_prompt_preserves_user_specs_and_tool_authority():
    memory = parse_memory_md(DOCUMENT, memory_id="project:acme:audience", source="project", project_id="acme")
    prompt = memories_prompt([memory])
    assert memory.body in prompt and memory.revision in prompt
    assert "approved Specifications" in prompt and "grant no permission" in prompt


# contract-test: supporting surface=rest_api assertions=app-memories.selection.source-scoped
def test_startup_warm_serves_subsets_and_configuration_revision_invalidates(monkeypatch):
    from backend.shared.python_utils import memory_loader as loader
    reads = []
    monkeypatch.setattr(loader, "_read_app_memories", lambda ids, root: reads.append(tuple(ids)) or [])
    loader._shipped_app_memories.cache_clear()
    monkeypatch.setenv("OPENMATES_CONFIG_REVISION", "test-r1")
    try:
        loader.warm_app_memories(["code", "design"])
        loader.load_app_memories(["code"])
        loader.load_app_memories(["design", "code"])
        assert reads == [("code",), ("design",)]
        monkeypatch.setenv("OPENMATES_CONFIG_REVISION", "test-r2")
        loader.load_app_memories(["code"])
        assert reads == [("code",), ("design",), ("code",)]
    finally:
        loader._shipped_app_memories.cache_clear()


CANONICAL = """---
title: Trip
load_mode: ask_first
valid_from: "2026-01-01T00:00:00Z"
valid_until: "2026-02-01T00:00:00Z"
references:
  - kind: embed
    id: e1
  - kind: chat
    id: c1
---
Packing list.
"""

# contract-test: supporting surface=rest_api assertions=app-memories.document.canonical-shape,app-memories.load-modes,app-memories.references.embeds,app-memories.expiry.client-enforced
def test_canonical_shape_parses_new_fields_and_blank_when_to_use():
    memory = parse_memory_md(CANONICAL, memory_id="p:1", source="personal")
    assert memory.when_to_use == "" and memory.description == ""
    assert memory.load_mode == "ask_first"
    assert memory.valid_from == "2026-01-01T00:00:00Z" and memory.valid_until == "2026-02-01T00:00:00Z"
    assert [(r.kind, r.id) for r in memory.references] == [("embed", "e1")]  # legacy chat reference dropped

# contract-test: supporting surface=rest_api assertions=app-memories.compatibility.legacy-documents,app-memories.document.canonical-shape
def test_legacy_document_keeps_revision_and_defaults():
    import hashlib
    memory = parse_memory_md(DOCUMENT, memory_id="p:1", source="personal")
    assert memory.revision == hashlib.sha256(DOCUMENT.encode()).hexdigest()
    assert memory.load_mode == "auto_include" and memory.references == () and memory.valid_until is None
    assert memory.description and memory.when_to_use

# contract-test: supporting surface=rest_api assertions=app-memories.document.canonical-shape,app-memories.load-modes,app-memories.expiry.client-enforced
@pytest.mark.parametrize("old,new", [
    ("ask_first", "sometimes"), ("2026-02-01T00:00:00Z", "2025-01-01T00:00:00Z"),
    ('"2026-01-01T00:00:00Z"', "not-a-date"), ("kind: embed", "kind: note"),
    ("title: Trip\n", "title: Trip\nextra: 1\n"), ("title: Trip\n", ""),
])
def test_invalid_canonical_fields_are_rejected(old, new):
    with pytest.raises(ValueError):
        parse_memory_md(CANONICAL.replace(old, new), memory_id="p:1", source="personal")

# contract-test: supporting surface=rest_api assertions=app-memories.load-modes
def test_public_app_memory_rejects_private_only_fields():
    with pytest.raises(ValueError):
        parse_memory_md(CANONICAL, memory_id="app:code:x", source="app", app_id="code")

# contract-test: supporting surface=rest_api assertions=app-memories.document.canonical-shape,app-memories.compatibility.legacy-documents
def test_display_metadata_is_accepted_and_never_reaches_the_body_or_prompt():
    document = CANONICAL.replace("title: Trip\n", "title: Trip\ncreated_at: 1700000000\nupdated_at: 1700000500\napp_id: travel\n")
    memory = parse_memory_md(document, memory_id="p:1", source="personal")
    assert memory.app_id is None
    prompt = memories_prompt([memory])
    for leaked in ("created_at", "updated_at", "1700000500", "app_id"):
        assert leaked not in memory.body and leaked not in prompt


# contract-test: supporting surface=rest_api assertions=app-memories.document.canonical-shape
@pytest.mark.parametrize("extra", ["created_at: soon\n", "updated_at: -1\n", "created_at: true\n", "app_id: 12\n", "app_id: ''\n"])
def test_malformed_display_metadata_is_rejected(extra):
    with pytest.raises(ValueError):
        parse_memory_md(CANONICAL.replace("title: Trip\n", f"title: Trip\n{extra}"), memory_id="p:1", source="personal")
