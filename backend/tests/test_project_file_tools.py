"""Focused tests for Project file-tool source discovery metadata."""

from backend.apps.ai.processing.project_file_tools import (
    build_project_focus_prompt,
    build_project_source_routing_context,
)


# contract-test: supporting surface=rest_api assertions=projects.access.explicit-context,projects.files.chat-focus-required
def test_project_source_routing_context_is_safe_current_and_deterministic() -> None:
    sources = [
        {
            "source_id": "source-b",
            "source_type": "remote_git_repository",
            "status": "connected",
            "capabilities": ["run_command", "read", "run_command", "unknown"],
            "encrypted_display_name": "ciphertext-name",
            "encrypted_metadata": "ciphertext-metadata",
        },
        {
            "source_id": "source-revoked",
            "source_type": "remote_folder",
            "status": "revoked",
            "capabilities": ["read"],
        },
        {
            "source_id": "source-a",
            "source_type": "remote_folder",
            "status": "offline",
            "capabilities": ["search", "read"],
        },
    ]

    routing = build_project_source_routing_context(
        sources,
        connected_source_ids={"source-b"},
    )

    assert routing == [
        {
            "source_id": "source-a",
            "source_type": "remote_folder",
            "status": "offline",
            "capabilities": ["read", "search"],
        },
        {
            "source_id": "source-b",
            "source_type": "remote_git_repository",
            "status": "connected",
            "capabilities": ["read", "run_command"],
        },
    ]
    prompt = build_project_focus_prompt({"instruction": "Work in this Project."}, routing)
    assert '"source_id":"source-a"' in prompt
    assert "ciphertext-name" not in prompt
    assert "source-revoked" not in prompt
    assert "authorized again at dispatch time" in prompt
