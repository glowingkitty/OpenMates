"""Focused tests for Project file-tool source discovery metadata."""

from backend.apps.ai.processing.project_file_tools import (
    build_project_focus_prompt,
    build_project_source_routing_context,
    default_operation_source_id,
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
    # A new web app goes through one application block, not parallel file-tool writes.
    assert "application_preview" in prompt and "web-app/" in prompt


# contract-test: supporting surface=rest_api assertions=projects.creation.machine-folder
def test_operation_without_source_goes_to_the_only_remote_source() -> None:
    machine = {"source_id": "machine-folder", "source_type": "local_folder", "status": "offline",
               "capabilities": ["read", "search", "write_request"]}
    read_only = {"source_id": "reading-list", "source_type": "local_folder", "status": "connected",
                 "capabilities": ["read", "search"]}

    # A Project created on a machine: every omitted-source operation goes to its folder.
    assert default_operation_source_id([machine], "write_request") == "machine-folder"
    assert default_operation_source_id([machine], "read") == "machine-folder"
    # Hosted Projects, several sources, or a source without the capability stay hosted.
    assert default_operation_source_id([], "write_request") is None
    assert default_operation_source_id([machine, read_only], "read") is None
    assert default_operation_source_id([read_only], "write_request") is None
