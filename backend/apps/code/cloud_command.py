# backend/apps/code/cloud_command.py
#
# Rules shared by terminal commands in cloud Projects (E2B workspace) and on a
# connected machine: files are read and edited only through the Project file
# tools, so commands that only read or edit files are refused before they run;
# plus the cloud command limits and the workspace cache identity.
# Spec: feature.app-skill.code-run code-run.commands.files-through-file-tools,
# code-run.cloud.commands, code-run.cloud.workspace.

from __future__ import annotations

import hashlib
import re
from typing import Any

FILE_TOOLS_HINT = (
    "Terminal commands are only for work that needs execution (installs, builds, tests, linters, "
    "the preview or a dev server). Search, read and edit Project files with the Project file tools "
    "(project_search_text, project_read_text, project_create_file, project_update_file)."
)

MAX_CLOUD_COMMANDS_PER_TURN = 20
CLOUD_FOREGROUND_DEFAULT_SECONDS = 300
CLOUD_FOREGROUND_MAX_SECONDS = 1800
WORKSPACE_STATE_TTL_SECONDS = 2 * 60 * 60

# Programs whose only purpose is showing or editing file contents.
_FILE_READERS = {"cat", "head", "tail", "less", "more", "bat", "nl", "tac", "xxd", "od", "strings", "tee"}
_FILE_EDITORS = {"vi", "vim", "nvim", "nano", "emacs", "ed", "ex"}
_SHELLS = {"bash", "sh", "zsh", "dash"}
# A shell line that writes into a file with > or >> (not 2>&1, not >/dev/null).
_REDIRECT_TO_FILE = re.compile(r"(?<![0-9&])>>?\s*(?!&|/dev/null)[^\s|;&]+")
_INPLACE_FLAG = re.compile(r"^-(?:[A-Za-z]*i[A-Za-z]*|-in-place)(?:=.*)?$")


def _program(argv: list[str]) -> str:
    return argv[0].rsplit("/", 1)[-1] if argv else ""


def _refuses_simple(argv: list[str]) -> bool:
    program = _program(argv)
    if program in _FILE_READERS or program in _FILE_EDITORS:
        return True
    if program in {"sed", "perl"} and any(_INPLACE_FLAG.match(arg) for arg in argv[1:]):
        return True
    if program in {"awk", "gawk"} and "inplace" in argv[1:]:
        return True
    return False


def _shell_segments(line: str) -> list[list[str]]:
    segments = re.split(r"&&|\|\||;|\|", line)
    return [segment.split() for segment in segments if segment.strip()]


def file_command_refusal(argv: list[str]) -> str | None:
    """Return a refusal message when the command only reads or edits files.

    Deterministic and deliberately narrow: it catches the obvious forms (cat,
    head, sed -i, echo > file, tee, editors) in argv and in a ``bash -c`` line.
    The tool description carries the rule for everything else.
    """
    if not argv:
        return None
    if _refuses_simple(argv):
        return f"Refused: `{_program(argv)}` reads or edits files. {FILE_TOOLS_HINT}"
    if _program(argv) in _SHELLS:
        flag_index = next((i for i, arg in enumerate(argv[1:], 1) if arg.startswith("-") and "c" in arg), None)
        if flag_index is not None and flag_index + 1 < len(argv):
            line = argv[flag_index + 1]
            if _REDIRECT_TO_FILE.search(line):
                return f"Refused: the shell line writes into a file with a redirect. {FILE_TOOLS_HINT}"
            for words in _shell_segments(line):
                if _refuses_simple(words):
                    return f"Refused: `{_program(words)}` reads or edits files. {FILE_TOOLS_HINT}"
    return None


def workspace_cache_key(user_id: str, chat_id: str, project_id: str) -> str:
    user_hash = hashlib.sha256(user_id.encode("utf-8")).hexdigest()
    return f"code_cloud_workspace:{user_hash}:{chat_id}:{project_id}"


def command_budget_key(chat_id: str, message_id: str) -> str:
    return f"code_cloud_commands:{chat_id}:{message_id}"


def cloud_command_limits(
    *, background: bool, timeout_seconds: int, ready_url: str | None,
) -> tuple[int, str | None]:
    """Return (bounded timeout, error) for a cloud command request."""
    if background:
        if not ready_url or not re.match(r"^http://(localhost|127\.0\.0\.1)(:\d{1,5})?(/.*)?$", ready_url):
            return 0, "Background commands need ready_url on http://localhost or http://127.0.0.1."
        return min(max(timeout_seconds, 10), 300), None
    if timeout_seconds > CLOUD_FOREGROUND_MAX_SECONDS:
        return 0, f"Cloud commands run at most {CLOUD_FOREGROUND_MAX_SECONDS} seconds."
    return timeout_seconds, None


def command_display(argv: list[str], cwd: str) -> str:
    """The text the chat's command card shows."""
    import shlex

    location = "" if cwd in {"", "."} else f"cd {shlex.quote(cwd)} && "
    return f"$ {location}{shlex.join(argv)}\n"


def snapshot_texts(files: list[Any]) -> dict[str, str]:
    """Map the injected snapshot files to path -> text."""
    texts: dict[str, str] = {}
    for item in files:
        path = getattr(item, "path", None) if not isinstance(item, dict) else item.get("path")
        code = getattr(item, "code", None) if not isinstance(item, dict) else item.get("code", item.get("content"))
        if isinstance(path, str) and isinstance(code, str):
            texts[path] = code
    return texts
