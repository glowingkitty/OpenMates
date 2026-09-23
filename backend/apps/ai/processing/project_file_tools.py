"""LLM-facing Project file tools backed by an authorized client executor."""

from __future__ import annotations

from typing import Any


PROJECT_FILE_TOOL_TO_OPERATION = {
    "project_list_files": "list",
    "project_search_files": "search",
    "project_read_text": "read_text",
    "project_create_file": "create_file",
    "project_update_file": "update_file",
}


def build_project_file_tools() -> list[dict[str, Any]]:
    path_property = {
        "type": "string",
        "description": "Project-relative path. Never use an absolute path or parent traversal.",
    }
    source_property = {
        "type": "string",
        "description": (
            "Optional source routing id within the active Project. Omit it to let the client select hosted "
            "storage or the Project's only configured remote source. Never use a source from another Project."
        ),
    }
    return [
        {
            "type": "function",
            "function": {
                "name": "project_list_files",
                "description": "List files and directories in the active Project.",
                "parameters": {
                    "type": "object",
                    "properties": {"path": path_property, "source_id": source_property},
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "project_search_files",
                "description": "Search text across readable files in the active Project.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "minLength": 1},
                        "target": {
                            "type": "string",
                            "enum": ["files", "content"],
                            "default": "content",
                            "description": "Search file paths or readable file contents.",
                        },
                        "mode": {
                            "type": "string",
                            "enum": ["literal", "regex"],
                            "default": "literal",
                        },
                        "path": path_property,
                        "glob": {
                            "type": "string",
                            "description": (
                                "Optional Project-relative glob limiting matched paths. Supports only *, **, and ?; "
                                "character classes and brace expansion are unsupported."
                            ),
                        },
                        "max_results": {"type": "integer", "minimum": 1, "maximum": 100},
                        "source_id": source_property,
                    },
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "project_read_text",
                "description": "Read one complete UTF-8 text file from the active Project and return its current base hash.",
                "parameters": {
                    "type": "object",
                    "properties": {"path": path_property, "source_id": source_property},
                    "required": ["path"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "project_create_file",
                "description": "Create a new UTF-8 text file. Fails if the target already exists.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": path_property,
                        "expected_base": {
                            "type": "null",
                            "description": "Must be null for create_file.",
                        },
                        "content": {"type": "string"},
                        "source_id": source_property,
                    },
                    "required": ["path", "expected_base", "content"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "project_update_file",
                "description": "Apply a unified diff to a file only if its base SHA-256 still matches the prior read.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": path_property,
                        "expected_base": {
                            "type": "string",
                            "pattern": "^[0-9a-f]{64}$",
                            "description": "Lowercase SHA-256 returned by project_read_text.",
                        },
                        "patch": {
                            "type": "string",
                            "description": "Unified diff against exactly expected_base.",
                        },
                        "source_id": source_property,
                    },
                    "required": ["path", "expected_base", "patch"],
                },
            },
        },
    ]


def build_project_focus_prompt(focus: dict[str, Any]) -> str:
    instruction = str(focus.get("instruction") or "").strip()
    return (
        "An authorized Project focus is active for this chat. Use the Project file tools when the "
        "request requires inspecting or changing Project files. Read a file before updating it and "
        "use the exact expected_base returned by the read. Never invent, weaken, or change Project "
        "authority, write policy, approval, or source readiness. A pending client operation means "
        "wait for its continuation; do not poll or claim that a file changed until its result arrives.\n\n"
        "After a successful create or update, summarize the applied_diff and the actual changes. On a base "
        "conflict, reread the file and regenerate a compatible edit that preserves intervening changes when "
        "that still matches the user's original intent. Do not regenerate when intervening changes create a "
        "material intent conflict or when the conflict budget is exhausted; explain the blocked edit and any "
        "partial work honestly.\n\n"
        "Full active Project focus instruction:\n"
        f"{instruction}"
    )
