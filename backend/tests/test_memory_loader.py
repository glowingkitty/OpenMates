"""Published Memories and exact source/revision compatibility."""
import pytest
from backend.shared.python_utils.memory_loader import load_app_memories, parse_memory_md, memories_prompt

DOCUMENT = "---\ntitle: Mobile audience\ndescription: Most readers use phones.\nwhen_to_use: Designing this project.\n---\nMost readers use phones.\n"

# contract-test: supporting surface=rest_api assertions=app-memories.definition.context-documents,app-memories.catalog.declared-types-only
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
