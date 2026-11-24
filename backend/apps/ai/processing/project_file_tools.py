"""LLM-facing Project file tools backed by an authorized client executor."""

from __future__ import annotations

import json
import re
from typing import Any


PROJECT_FILE_TOOL_TO_OPERATION = {
    "project_list_files": "list",
    "project_search_files": "search",
    "project_search_text": "search",
    "project_read_text": "read_text",
    "project_create_file": "create_file",
    "project_update_file": "update_file",
    "project_rename_file": "rename_file",
    "project_delete_file": "delete_file",
    "project_commit": "commit",
}

PROJECT_SOURCE_TYPES = {
    "local_folder",
    "local_git_repository",
    "remote_folder",
    "remote_git_repository",
}
PROJECT_SOURCE_CAPABILITIES = {"read", "search", "import", "write_request", "run_command"}
UNSCOPED_PROJECT_SEARCH_TOOL = "projects-search"
PROJECT_READ_INTENT = re.compile(r"\b(?:read|open|inspect|review|summari[sz]e)\b", re.IGNORECASE)
PROJECT_FILE_ACTION = re.compile(
    r"\b(?:show|list|search|find|edit|update|write|modify|change|fix|improve|add|remove|delete|create)\b",
    re.IGNORECASE,
)
PROJECT_FILE_NOUN = re.compile(
    r"\b(?:files?|readme|folders?|directories|directory|documents?|source|code|repositories|repository|paths?)\b",
    re.IGNORECASE,
)
PROJECT_FILE_REFUSAL = re.compile(
    r"\b(?:do\s+not|don['’]?t|never|avoid|without|no\s+need\s+to)\b"
    r"[^.!?;\n]{0,100}\b(?:read|open|inspect|review|summari[sz]e|show|list|search|find|"
    r"access|edit|update|write|modify|change|fix|improve|add|remove|delete|create)\b",
    re.IGNORECASE,
)
PROJECT_READ_OR_ACCESS_ACTION = re.compile(
    r"\b(?:read|open|inspect|review|summari[sz]e|show|list|search|find|access)\b",
    re.IGNORECASE,
)
PROJECT_ALL_FILE_WORK_REFUSAL = re.compile(
    r"\b(?:do\s+not|don['’]?t|never|avoid|without|no\s+need\s+to)\s+"
    r"(?:use|touch|work\s+(?:on|with))\b[^.!?;\n]{0,80}"
    r"\b(?:projects?|files?|readme|repositories|repository)\b",
    re.IGNORECASE,
)


def declines_project_file_work(text: str) -> bool:
    """Conservatively prevent implicit activation for explicit file-work refusals."""

    if PROJECT_ALL_FILE_WORK_REFUSAL.search(text):
        return True
    refusals = list(PROJECT_FILE_REFUSAL.finditer(text))
    if not refusals:
        return False
    for refusal in refusals:
        action = refusal.group().split()[-1]
        if PROJECT_READ_OR_ACCESS_ACTION.fullmatch(action):
            return True
        # A coordinated prohibition covers both actions: "do not edit or read".
        clause = text[refusal.end():].split(';', 1)[0].split('.', 1)[0]
        if re.match(r"\s+(?:or|nor)\s+", clause, re.IGNORECASE) and PROJECT_READ_OR_ACCESS_ACTION.search(clause):
            return True
    # A write-only prohibition must not hide a separate, positive read request.
    return not any(
        not any(refusal.start() <= read.start() < refusal.end() for refusal in refusals)
        for read in PROJECT_READ_INTENT.finditer(text)
    )


def requests_project_file_work(text: str) -> bool:
    """Recognize explicit file work; other named Project uses keep model selection."""

    return not declines_project_file_work(text) and bool(PROJECT_READ_INTENT.search(text) or
                PROJECT_FILE_ACTION.search(text) and PROJECT_FILE_NOUN.search(text))


def without_unscoped_project_search(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The legacy Projects search has no client result consumer or active-focus scope."""

    return [
        tool for tool in tools
        if str(tool.get("function", {}).get("name") or "").replace(":", "-").replace("_", "-").replace("|", "-")
        != UNSCOPED_PROJECT_SEARCH_TOOL
    ]


def uniquely_named_project_focus_id(
    text: str,
    candidates: list[dict[str, Any]],
    offered_focus_ids: list[str],
) -> str | None:
    """Choose only one eligible, offered plain-name match for a consent request."""

    from backend.core.api.app.services.project_focus_request_service import (
        explicitly_named_project_focus_ids,
    )

    matches = list(dict.fromkeys(explicitly_named_project_focus_ids(text, candidates)))
    return matches[0] if len(matches) == 1 and matches[0] in offered_focus_ids else None


def build_project_source_routing_context(
    sources: list[dict[str, Any]],
    *,
    connected_source_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Return deterministic, non-secret source metadata suitable for the model."""

    connected_source_ids = connected_source_ids or set()
    routing_sources: list[dict[str, Any]] = []
    for source in sources:
        source_id = source.get("source_id")
        source_type = source.get("source_type")
        if (
            source.get("status") == "revoked"
            or not isinstance(source_id, str)
            or not source_id
            or source_type not in PROJECT_SOURCE_TYPES
        ):
            continue
        capabilities = sorted(
            {
                capability
                for capability in source.get("capabilities") or []
                if isinstance(capability, str) and capability in PROJECT_SOURCE_CAPABILITIES
            }
        )
        routing_sources.append(
            {
                "source_id": source_id,
                "source_type": source_type,
                "status": "connected" if source_id in connected_source_ids else "offline",
                "capabilities": capabilities,
            }
        )
    return sorted(routing_sources, key=lambda source: source["source_id"])


def default_operation_source_id(
    sources: list[dict[str, Any]],
    required_capability: str,
) -> str | None:
    """The source a Project file operation goes to when the model names none.

    Tool contract (``source_id`` description below): omitting it selects hosted
    storage, or the Project's only configured remote source. A Project created on
    the user's machine has exactly that one source, so its files land in the
    machine folder instead of hosted storage. With no or several remote sources,
    or when the only one lacks the capability, the operation stays hosted.
    ``sources`` is the routing context from ``build_project_source_routing_context``.
    """
    if len(sources) != 1:
        return None
    source = sources[0]
    if required_capability not in set(source.get("capabilities") or []):
        return None
    return str(source["source_id"])


FENCE_WRITTEN_TOOLS = frozenset({"project_create_file", "project_update_file"})


def build_project_file_tools(*, code_fences: bool = False) -> list[dict[str, Any]]:
    """The Project file tools; with ``code_fences`` files are written as reply code fences instead."""
    tools = _project_file_tools()
    if code_fences:
        return [tool for tool in tools if tool["function"]["name"] not in FENCE_WRITTEN_TOOLS]
    return tools


def _project_file_tools() -> list[dict[str, Any]]:
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
                "description": (
                    "Search file names and paths in the active Project. Set include_content=true to return "
                    "complete text for matching small UTF-8 files in this same operation, within fixed file and "
                    "total byte limits. Use this when asked to read or review a named README or document. "
                    "The response states why any matched file content was omitted."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "minLength": 1},
                        "mode": {"type": "string", "enum": ["literal", "regex"], "default": "literal"},
                        "path": path_property,
                        "glob": {
                            "type": "string",
                            "description": (
                                "Optional Project-relative glob limiting matched paths. Supports only *, **, and ?; "
                                "character classes and brace expansion are unsupported."
                            ),
                        },
                        "max_results": {"type": "integer", "minimum": 1, "maximum": 100},
                        "include_content": {
                            "type": "boolean",
                            "description": "Return complete text and base hashes for up to eight matching small files; false by default.",
                        },
                        "source_id": source_property,
                    },
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "project_search_text",
                "description": "Search text inside readable files in the active Project.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "minLength": 1},
                        "mode": {"type": "string", "enum": ["literal", "regex"], "default": "literal"},
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
                "description": (
                    "Read complete UTF-8 text files from the active Project and return each current base hash. "
                    "Give `path` for one file or `paths` for several. "
                    "To read several files, pass them together in `paths` (at most 10) in ONE call "
                    "instead of calling this tool once per file."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": path_property,
                        "paths": {
                            "type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 10,
                            "description": "Project-relative paths to read in one call (hosted workspace).",
                        },
                        "source_id": source_property,
                    },
                    # Give `path` or `paths`. No anyOf of required-only branches here: Gemini's
                    # function schema rejects them (400 "required: only allowed for OBJECT type").
                    # A call with neither is refused by the executor.
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
                            "description": (
                                "Unified diff against exactly expected_base. Start with --- and +++ file headers "
                                "using the exact Project-relative path from project_read_text. Each hunk starts with "
                                "@@ coordinates. Preserve the original lines and their indentation exactly. "
                                "Use a no-newline marker for a final line that has no newline. "
                                "Send the diff directly without a Markdown fence or git metadata."
                            ),
                        },
                        "source_id": source_property,
                    },
                    "required": ["path", "expected_base", "patch"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "project_rename_file",
                "description": (
                    "Rename or move one file to a new Project-relative path. The file keeps its identity and "
                    "revision history. Fails if the new path already exists."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": path_property,
                        "new_path": {**path_property, "description": "New Project-relative path for the file."},
                        "source_id": source_property,
                    },
                    "required": ["path", "new_path"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "project_delete_file",
                "description": (
                    "Remove one file from the Project folder. Its revision history is kept, so a Project commit "
                    "restore can bring it back."
                ),
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
                "name": "project_commit",
                "description": (
                    "Record a Project commit of the Project's current changed files. Call it only after the "
                    "tests are green, with one short line describing the change. The commit is executed by the "
                    "client; its result names the commit id, its 7-character short_id and the number of files. "
                    "When you mention the commit to the user, quote only the short_id."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "message": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 200,
                            "description": "One-line commit message, at most 200 characters.",
                        },
                    },
                    "required": ["message"],
                },
            },
        },
    ]


def build_project_focus_prompt(
    focus: dict[str, Any],
    sources: list[dict[str, Any]] | None = None,
    *,
    code_fences: bool = False,
) -> str:
    instruction = str(focus.get("instruction") or "").strip()
    if code_fences:
        return _code_fence_project_prompt(instruction, sources)
    if default_operation_source_id(sources or [], "write_request") is not None:
        # projects.creation.machine-folder: the Project's files live only in a
        # machine folder, and an application_preview block would store them as
        # hosted Project files instead, so new apps go through the file tools.
        new_application = (
            "This Project's files live in a folder on the user's machine. When the user asks for a new "
            "runnable web application, do not emit an application_preview block; create each of its files "
            "with the Project file tools in the application's folder (web-app/ unless Project creation "
            "named another subfolder), so they land in that folder. "
        )
    else:
        # projects.files.application-via-file-tools: an application_preview block
        # stays a chat-only bundle (no client links its files into the Project),
        # so the workspace commands of later turns would find no files.
        new_application = (
            "When the user asks for a new runnable web application, do not emit an application_preview block "
            "or paste its files as code blocks in the reply; create each of its files with the Project file "
            "tools in the application's folder (web-app/ unless Project creation named another subfolder), so "
            "they are stored as Project files, then summarize what you created. "
            "Run installs, builds, tests, linters and dev servers as code-run commands (target e2b with argv) in "
            "this Project's cloud workspace; files a command changes are synced back as normal file changes. "
        )
    # The stable base prompt (code-block rules, software mate) asks for an
    # application_preview fence for every new web app. Real Project runs showed
    # the model writing the files with the tools and then adding that fence as
    # well, a second chat-only copy of the app, so the override is explicit.
    new_application += (
        "This replaces the general runnable-web-app rule for this chat: never add an application_preview "
        "fence, not even after the files are written; the file cards in the chat already show them. "
    )
    prompt = (
        "An authorized Project focus is active for this chat. Use the Project file tools when the "
        "request requires inspecting or changing Project files. Read a file before updating it and "
        "use the exact expected_base returned by the read. Change, rename or delete Project files only with "
        "the Project file tools; a raw diff block in the reply that targets a Project file is not applied. "
        "Terminal commands are only for work that needs execution; never use them to read or edit files "
        "(no cat, head, sed, tee or echo > file). "
        f"{new_application}"
        "Never invent, weaken, or change Project "
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
    if sources is not None:
        prompt += (
            "\n\nAuthorized Project source routing metadata (server-derived; labels and content are omitted):\n"
            f"{json.dumps(sources, separators=(',', ':'), sort_keys=True)}\n"
            "Use an exact source_id when selecting one of these sources. Treat status and capabilities as "
            "advisory discovery metadata; every operation is authorized again at dispatch time."
        )
    return prompt


def _code_fence_project_prompt(instruction: str, sources: list[dict[str, Any]] | None) -> str:
    """Cloud Project chats write files the way a normal chat writes code (plan project-files-as-chat-code-embeds)."""
    prompt = (
        "An authorized Project focus is active for this chat and its files live in this Project's cloud workspace. "
        "Write files exactly as you write code in a normal chat: each new file is one code block whose header is "
        "its language and Project path, for example ```tsx:web-app/src/App.tsx. The block is saved as that "
        "Project file when it closes, and commands only see files whose blocks you already wrote: write the "
        "blocks of every file a command needs before you call code-run, in that same response. A block you "
        "write only after your last command or in your final answer is never run or tested. To change an existing file, read it, then write a ```diff:<its Project path> block with a unified "
        "diff of the change (for example ```diff:web-app/src/App.tsx); replace a file completely only when most "
        "of it changes. Put each file in its own block, never repeat a file you already wrote, and never wrap "
        "several files in one block. New runnable web applications go in web-app/ unless Project creation named "
        "another subfolder; never emit an application_preview block, the code blocks are the application. "
        "Use the Project file tools only to list, search and read files, and to rename or delete them. "
        "Run installs, builds, tests, linters and dev servers as code-run commands (target e2b with argv) in this "
        "Project's cloud workspace; never use a command to read or write files (no cat, head, sed, tee or "
        "echo > file). "
        "In your text, mention a file you wrote with an inline link to its Project path, for example "
        "[App.tsx](embed:web-app/src/App.tsx), instead of listing folder or file names as plain text. "
        "Never invent, weaken, or change Project authority, write policy, approval, or source readiness.\n\n"
        "Full active Project focus instruction:\n"
        f"{instruction}"
    )
    if sources is not None:
        prompt += (
            "\n\nAuthorized Project source routing metadata (server-derived; labels and content are omitted):\n"
            f"{json.dumps(sources, separators=(',', ':'), sort_keys=True)}"
        )
    return prompt
