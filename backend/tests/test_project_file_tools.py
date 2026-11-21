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
    # A new web app is written file by file with the file tools, never as one inline block.
    assert "do not emit an application_preview block" in prompt and "web-app/" in prompt


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


# contract-test: supporting surface=rest_api assertions=projects.creation.machine-folder
def test_a_new_app_is_written_with_the_file_tools_in_every_project() -> None:
    machine = {"source_id": "machine-folder", "source_type": "local_git_repository", "status": "connected",
               "capabilities": ["read", "run_command", "write_request"]}
    focus = {"instruction": "Work in this Project."}

    # Only source is the machine folder: an application block would land in hosted storage.
    prompt = build_project_focus_prompt(focus, [machine])
    assert "do not emit an application_preview block" in prompt
    assert "folder on the user's machine" in prompt
    # Hosted Projects also write a new app with the file tools, so its files are Project files.
    hosted = build_project_focus_prompt(focus, [])
    assert "do not emit an application_preview block" in hosted
    assert "create each of its files with the Project file tools" in hosted
    assert "folder on the user's machine" not in hosted
    # The Project rule explicitly overrides the base "runnable web apps" fence rule in both
    # kinds of Project, since the model otherwise writes the files and adds the fence too.
    for text in (prompt, hosted):
        assert "replaces the general runnable-web-app rule" in text
        assert "not even after the files are written" in text
