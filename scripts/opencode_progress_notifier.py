#!/usr/bin/env python3
"""Send periodic Discord progress summaries for active OpenCode chats.

This observer reads existing OpenCode presence and bounded transcript projections,
summarizes active top-level chats with a low-cost model, and posts one
maintainer-facing Discord digest. It is intentionally external to OpenCode hooks:
passive lifecycle events must not start prompts or mutate chats.
Architecture: docs/specs/opencode-active-progress-notifier/spec.yml.
"""

from __future__ import annotations

import argparse
import base64
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile
import time
from typing import Any, Callable
from urllib import error, request


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
DEFAULT_MODEL = "mistral-small-latest"
DEFAULT_GEMINI_MODEL = "gemini-3.5-flash-lite"
DEFAULT_MISTRAL_MODEL = "mistral-small-latest"
DEFAULT_INTERVAL_MINUTES = 15
DEFAULT_DAILY_ACTIVE_HOURS = 12
MODEL_PRICING_USD_PER_MILLION_TOKENS = {
    # Mistral official API pricing, verified 2026-08-11: https://docs.mistral.ai/inference/pricing
    "mistral-small-latest": {"input": 0.15, "output": 0.60},
    "gemini-3.5-flash-lite": {"input": 0.30, "output": 2.50},
}
ESTIMATED_CHARS_PER_TOKEN = 4
DISCORD_ENV = "DISCORD_WEBHOOK_AGENT_PROGRESS"
CRON_BEGIN = "# BEGIN OpenMates OpenCode active progress notifier"
CRON_END = "# END OpenMates OpenCode active progress notifier"
CRON_SCHEDULE = "*/15 * * * *"
MAX_ACTIVE_CHATS = 20
MAX_MESSAGES_PER_CHAT = 20
MAX_PARTS_PER_MESSAGE = 6
MAX_TEXT_CHARS = 1_200
MAX_ISSUE_SIGNALS = 8
MAX_DISCORD_CONTENT_CHARS = 1_900
MAX_DISCORD_EMBED_DESCRIPTION_CHARS = 4_000
MAX_DISCORD_EMBED_TOTAL_CHARS = 6_000
ACTIVE_CHATS_EMBED_TITLE = "Currently Active Chats"
ACTIVE_CHATS_CONTINUED_EMBED_TITLE = "Currently Active Chats (continued)"
GEMINI_SYSTEM_PROMPT = (
    "You summarize active OpenCode coding chats for the OpenMates maintainer. "
    "Return concise, scannable, evidence-grounded JSON. Use exact task_items when present. "
    "When task_items are absent, infer a short task list with completed, current, and next steps. "
    "Use the top-level notifier_config for the current notifier model and cadence; do not repeat older transcript claims as current config. "
    "For the progress-notifier chat, never describe Gemini or 10-minute cadence as current when notifier_config says otherwise. "
    "Highlight important decisions, places the maintainer should watch, product/code issues, and agent workflow issues. "
    "Do not quote raw secrets, webhook URLs, API keys, reasoning traces, attachment content, or long tool outputs."
)
STATE_SCHEMA_VERSION = 1
OPENCODE_WEB_BASE_URL = os.environ.get("OPENCODE_WEB_BASE_URL", "https://code.dev.openmates.org")

if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from discord_webhook import post_message  # noqa: E402


@dataclass(frozen=True)
class ActiveChatRoot:
    session_id: str
    status_label: str
    title: str
    updated_at: str
    active_child_session_ids: list[str]


class ProgressNotifierError(RuntimeError):
    """Raised when active progress notification cannot complete."""


SECRET_PATTERNS = [
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.IGNORECASE | re.DOTALL), "<PRIVATE_KEY>"),
    (re.compile(r"https://discord\.com/api/webhooks/[^\s)]+", re.IGNORECASE), "<DISCORD_WEBHOOK>"),
    (re.compile(r"(https?://)([^/\s:@]+):([^@\s/]+)@", re.IGNORECASE), r"\1<REDACTED>@"),
    (re.compile(r"([?&](?:api[_-]?key|apikey|key|token|access_token|auth|password|secret)=)[^&#\s]+", re.IGNORECASE), r"\1<REDACTED>"),
    (re.compile(r"\bAuthorization:\s*Bearer\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE), "Authorization: Bearer <REDACTED>"),
    (re.compile(r"(?i)\b([A-Z0-9_]*(?:URL|URI|DSN))\s*[:=]\s*['\"]?[a-z][a-z0-9+.-]*://[^\s'\"]+"), r"\1=<REDACTED_URL>"),
    (re.compile(r"(?i)\bAWS_(?:ACCESS_KEY_ID|SECRET_ACCESS_KEY|SESSION_TOKEN)\s*[:=]\s*['\"]?[^\s'\"]{8,}"), "AWS_CREDENTIAL=<REDACTED>"),
    (re.compile(r"#key=[A-Za-z0-9_-]{8,}"), "#key=<REDACTED>"),
    (re.compile(r"\bsk-(?:api|proj|live|test)?[-_A-Za-z0-9]{8,}", re.IGNORECASE), "<API_KEY>"),
    (re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{20,}\b"), "<GITHUB_TOKEN>"),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"), "<GITHUB_TOKEN>"),
    (re.compile(r"\bAIza[0-9A-Za-z_-]{20,}\b"), "<GOOGLE_API_KEY>"),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"), "<JWT>"),
    (
        re.compile(r"(?i)\b([A-Z0-9_]*(?:api[_-]?key|private[_-]?key|access[_-]?key(?:_id)?|session[_-]?token|secret|token|password))\s*[:=]\s*['\"]?[^\s'\"]{8,}"),
        r"\1=<REDACTED>",
    ),
    (
        re.compile(r"(?i)\b(api[_-]?key|secret|token|password)\s*[:=]\s*['\"]?[^\s'\"]{8,}"),
        r"\1=<REDACTED>",
    ),
]


def root_from_common_git_dir(common_dir: Path, fallback: Path) -> Path:
    resolved = common_dir.resolve()
    return resolved.parent if resolved.name == ".git" else fallback.resolve()


def canonical_checkout_root(fallback: Path = PROJECT_ROOT) -> Path:
    result = subprocess.run(
        ["git", "-C", str(fallback), "rev-parse", "--path-format=absolute", "--git-common-dir"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return fallback.resolve()
    return root_from_common_git_dir(Path(result.stdout.strip()), fallback)


CONTROL_PLANE_ROOT = canonical_checkout_root(PROJECT_ROOT)
DEFAULT_STATE_FILE = CONTROL_PLANE_ROOT / ".opencode" / "progress-notifier-state.json"


def _now_iso(now: datetime | None = None) -> str:
    current = now or datetime.now(timezone.utc)
    return current.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _bounded_text(value: Any, max_chars: int = MAX_TEXT_CHARS) -> str:
    text = str(value or "")
    text = redact_text(" ".join(text.split()))
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 14].rstrip() + "...[truncated]"


def _display_text(value: Any, max_chars: int) -> str:
    text = redact_text(" ".join(str(value or "").split()))
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"


def redact_text(value: str) -> str:
    redacted = value
    for pattern, replacement in SECRET_PATTERNS:
        redacted = pattern.sub(replacement, redacted)
    return redacted


def _string_list(value: Any, *, max_items: int = 8, max_chars: int = 300) -> list[str]:
    if not isinstance(value, list):
        return []
    result = []
    for item in value[:max_items]:
        text = _bounded_text(item, max_chars)
        if text:
            result.append(text)
    return result


def _dotenv_value(root: Path, key: str) -> str:
    value = os.environ.get(key, "").strip()
    if value:
        return value
    env_path = root / ".env"
    if not env_path.is_file():
        return ""
    prefix = f"{key}="
    for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith(prefix):
            return line[len(prefix) :].strip().strip("\"'")
    return ""


def load_gemini_api_key() -> str:
    for name in ("GEMINI_API_KEY", "SECRET__GOOGLE_AI_STUDIO__API_KEY"):
        value = _dotenv_value(CONTROL_PLANE_ROOT, name)
        if value and value != "IMPORTED_TO_VAULT":
            return value
    value = load_gemini_api_key_from_vault()
    if value:
        return value
    raise ProgressNotifierError("Gemini API key not found. Set GEMINI_API_KEY or SECRET__GOOGLE_AI_STUDIO__API_KEY.")


def load_mistral_api_key() -> str:
    for name in ("MISTRAL_API_KEY", "MISTRAL_AI_API_KEY", "SECRET__MISTRAL_AI__API_KEY"):
        value = _dotenv_value(CONTROL_PLANE_ROOT, name)
        if value and value != "IMPORTED_TO_VAULT":
            return value
    value = load_mistral_api_key_from_vault()
    if value:
        return value
    raise ProgressNotifierError("Mistral API key not found. Set MISTRAL_API_KEY or SECRET__MISTRAL_AI__API_KEY.")


def load_model_api_key(model: str) -> str:
    if model == DEFAULT_GEMINI_MODEL:
        return load_gemini_api_key()
    if model == DEFAULT_MISTRAL_MODEL or model.startswith("mistral-"):
        return load_mistral_api_key()
    raise ProgressNotifierError(f"Unsupported progress summary model: {model}")


def load_gemini_api_key_from_vault() -> str:
    compose_file = CONTROL_PLANE_ROOT / "backend" / "core" / "docker-compose.yml"
    env_file = CONTROL_PLANE_ROOT / ".env"
    if not compose_file.exists():
        return ""
    fetch_script = (
        "import asyncio\n"
        "from backend.core.api.app.utils.secrets_manager import SecretsManager\n"
        "from backend.apps.ai.llm_providers.google_client import _get_google_ai_studio_api_key\n"
        "async def main():\n"
        "    sm = SecretsManager()\n"
        "    await sm.initialize()\n"
        "    key = await _get_google_ai_studio_api_key(sm)\n"
        "    print(key or '', end='')\n"
        "asyncio.run(main())\n"
    )
    command = ["docker", "compose"]
    if env_file.exists():
        command.extend(["--env-file", str(env_file)])
    command.extend(["-f", str(compose_file), "exec", "-T", "api", "python3", "-c", fetch_script])
    try:
        result = subprocess.run(command, cwd=CONTROL_PLANE_ROOT, text=True, capture_output=True, timeout=20, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return result.stdout.strip()


def load_mistral_api_key_from_vault() -> str:
    compose_file = CONTROL_PLANE_ROOT / "backend" / "core" / "docker-compose.yml"
    env_file = CONTROL_PLANE_ROOT / ".env"
    if not compose_file.exists():
        return ""
    fetch_script = (
        "import asyncio\n"
        "from backend.core.api.app.utils.secrets_manager import SecretsManager\n"
        "async def main():\n"
        "    sm = SecretsManager()\n"
        "    await sm.initialize()\n"
        "    key = await sm.get_secret(secret_path='kv/data/providers/mistral_ai', secret_key='api_key')\n"
        "    print(key or '', end='')\n"
        "asyncio.run(main())\n"
    )
    command = ["docker", "compose"]
    if env_file.exists():
        command.extend(["--env-file", str(env_file)])
    command.extend(["-f", str(compose_file), "exec", "-T", "api", "python3", "-c", fetch_script])
    try:
        result = subprocess.run(command, cwd=CONTROL_PLANE_ROOT, text=True, capture_output=True, timeout=20, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return result.stdout.strip()


def load_status() -> dict[str, Any]:
    result = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "scripts" / "sessions.py"), "status", "--json"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()[:500]
        raise ProgressNotifierError(f"sessions.py status --json failed: {detail}")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ProgressNotifierError("sessions.py status --json returned invalid JSON") from exc


def read_chat_view(session_id: str) -> dict[str, Any]:
    import sessions  # type: ignore[import-not-found]

    return sessions.read_opencode_chat(
        session_id,
        include_children=True,
        include_tool_output=True,
        max_messages=MAX_MESSAGES_PER_CHAT,
        max_parts_per_message=MAX_PARTS_PER_MESSAGE,
        max_part_chars=MAX_TEXT_CHARS,
    )


def opencode_chat_url(session_id: str) -> str:
    encoded = base64.urlsafe_b64encode(str(CONTROL_PLANE_ROOT.resolve()).encode("utf-8")).decode("ascii").rstrip("=")
    return f"{OPENCODE_WEB_BASE_URL.rstrip('/')}/{encoded}/session/{session_id}"


def select_active_chat_roots(
    status: dict[str, Any],
    *,
    exclude_session_ids: set[str] | None = None,
    max_chats: int = MAX_ACTIVE_CHATS,
) -> list[ActiveChatRoot]:
    excluded = exclude_session_ids or set()
    live = status.get("live") if isinstance(status.get("live"), dict) else {}
    sections = (
        ("working", "working"),
        ("waiting_for_user", "waiting_for_user"),
        ("stopped_or_failed", "stopped_or_failed"),
    )
    roots: dict[str, dict[str, Any]] = {}
    for section, status_label in sections:
        items = live.get(section) if isinstance(live.get(section), list) else []
        for item in items:
            if not isinstance(item, dict):
                continue
            session_id = str(item.get("opencode_session_id") or "")
            root_id = str(item.get("top_level_session_id") or item.get("parent_id") or session_id)
            if not session_id or not root_id or root_id in excluded:
                continue
            record = roots.setdefault(
                root_id,
                {
                    "session_id": root_id,
                    "status_label": status_label,
                    "title": str(item.get("task") or item.get("title") or ""),
                    "updated_at": str(item.get("updated_at") or ""),
                    "children": [],
                },
            )
            if session_id == root_id:
                record["title"] = str(item.get("task") or item.get("title") or record.get("title") or "")
                record["updated_at"] = str(item.get("updated_at") or record.get("updated_at") or "")
            elif session_id not in record["children"]:
                record["children"].append(session_id)
    result = []
    for record in roots.values():
        title = str(record.get("title") or "")
        if title.casefold().startswith("opencode active progress notifier"):
            continue
        result.append(
            ActiveChatRoot(
                session_id=str(record["session_id"]),
                status_label=str(record["status_label"]),
                title=title,
                updated_at=str(record.get("updated_at") or ""),
                active_child_session_ids=list(record.get("children") or []),
            )
        )
        if len(result) >= max_chats:
            break
    return result


def _chat_title(active: ActiveChatRoot, view: dict[str, Any]) -> str:
    sessions = view.get("sessions") if isinstance(view.get("sessions"), list) else []
    for session in sessions:
        if isinstance(session, dict) and session.get("session_id") == active.session_id and session.get("title"):
            return _bounded_text(session["title"], 200)
    for session in sessions:
        if isinstance(session, dict) and session.get("title"):
            return _bounded_text(session["title"], 200)
    return _bounded_text(active.title or active.session_id, 200)


def _project_part(part: dict[str, Any]) -> dict[str, Any] | None:
    part_type = str(part.get("type") or "unknown")
    if part_type == "text":
        text = _bounded_text(part.get("text", ""))
        return {"type": "text", "text": text} if text else None
    if part_type == "tool":
        projected = {
            "type": "tool",
            "tool": _bounded_text(part.get("tool") or "unknown", 120),
            "status": _bounded_text(part.get("status") or "unknown", 80),
        }
        if part.get("error"):
            projected["error"] = _bounded_text(part.get("error"), 500)
        if str(part.get("tool") or "").lower() == "todowrite":
            projected["task_items"] = _task_items_from_todowrite_part(part)
        return projected
    if part_type in {"file", "image", "attachment"}:
        return {
            "type": part_type,
            "filename": _bounded_text(part.get("filename") or "unnamed", 160),
            "note": "attachment content omitted",
        }
    if part_type in {"reasoning", "step-start", "step-finish", "snapshot"}:
        return None
    return {"type": _bounded_text(part_type, 80), "status": _bounded_text(part.get("status") or "", 80)}


def _normalize_task_status(value: Any) -> str:
    status = str(value or "").strip().lower().replace("-", "_")
    if status in {"completed", "complete", "done", "finished", "succeeded"}:
        return "completed"
    if status in {"in_progress", "current", "working", "active", "now", "doing"}:
        return "in_progress"
    if status in {"cancelled", "canceled", "blocked"}:
        return "cancelled"
    return "pending"


def _normalize_task_item(item: Any, *, default_status: str = "pending") -> dict[str, str] | None:
    if isinstance(item, str):
        content = _bounded_text(item, 160)
        return {"content": content, "status": _normalize_task_status(default_status)} if content else None
    if not isinstance(item, dict):
        return None
    content = _bounded_text(item.get("content") or item.get("text") or item.get("task") or item.get("title") or "", 160)
    if not content:
        return None
    return {
        "content": content,
        "status": _normalize_task_status(item.get("status") or default_status),
        "priority": _bounded_text(item.get("priority") or "", 40),
    }


def _normalize_task_items(value: Any, *, max_items: int = 12, default_status: str = "pending") -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    tasks = []
    for item in value:
        normalized = _normalize_task_item(item, default_status=default_status)
        if normalized:
            tasks.append(normalized)
        if len(tasks) >= max_items:
            break
    return tasks


def _task_items_from_todowrite_part(part: dict[str, Any]) -> list[dict[str, str]]:
    input_value = part.get("input") if isinstance(part.get("input"), dict) else {}
    return _normalize_task_items(input_value.get("todos"), max_items=12)


def _task_items_from_digest(value: Any) -> list[dict[str, str]]:
    if isinstance(value, dict):
        tasks: list[dict[str, str]] = []
        for key, status in (("completed", "completed"), ("current", "in_progress"), ("in_progress", "in_progress"), ("next", "pending"), ("pending", "pending")):
            tasks.extend(_normalize_task_items(value.get(key), max_items=6, default_status=status))
        return tasks[:12]
    return _normalize_task_items(value, max_items=12)


def project_chat_view(active: ActiveChatRoot, view: dict[str, Any]) -> dict[str, Any]:
    messages = []
    latest_task_items: list[dict[str, str]] = []
    raw_messages = view.get("messages") if isinstance(view.get("messages"), list) else []
    for message in raw_messages[-MAX_MESSAGES_PER_CHAT:]:
        if not isinstance(message, dict):
            continue
        parts = []
        raw_parts = message.get("parts") if isinstance(message.get("parts"), list) else []
        for raw_part in raw_parts[:MAX_PARTS_PER_MESSAGE]:
            if isinstance(raw_part, dict):
                projected = _project_part(raw_part)
                if projected:
                    if projected.get("tool") == "todowrite" and projected.get("task_items"):
                        latest_task_items = list(projected["task_items"])
                    parts.append(projected)
        if parts:
            messages.append(
                {
                    "role": _bounded_text(message.get("role") or "unknown", 80),
                    "time_updated": _bounded_text(message.get("time_updated") or message.get("time_created") or "", 80),
                    "parts": parts,
                }
            )

    modified_files: list[str] = []
    for repository_session in view.get("repository_sessions") or []:
        if not isinstance(repository_session, dict):
            continue
        for path in repository_session.get("modified_files") or []:
            text = _bounded_text(path, 240)
            if text and text not in modified_files:
                modified_files.append(text)
    issue_signals = []
    for signal in (view.get("issue_signals") or [])[:MAX_ISSUE_SIGNALS]:
        if not isinstance(signal, dict):
            continue
        issue_signals.append(
            {
                "kind": _bounded_text(signal.get("kind") or "unknown", 80),
                "tool": _bounded_text(signal.get("tool") or "", 80),
                "text": _bounded_text(signal.get("text") or "", 300),
            }
        )

    return {
        "session_id": active.session_id,
        "title": _chat_title(active, view),
        "url": opencode_chat_url(active.session_id),
        "status_label": active.status_label,
        "updated_at": active.updated_at,
        "active_child_session_ids": active.active_child_session_ids,
        "modified_files": modified_files[:12],
        "modified_file_count": len(modified_files),
        "issue_signals": issue_signals,
        "task_items": latest_task_items,
        "messages": messages,
        "truncated": view.get("truncated") if isinstance(view.get("truncated"), dict) else {},
    }


def build_evidence(
    active_roots: list[ActiveChatRoot],
    *,
    chat_reader: Callable[[str], dict[str, Any]],
    now: datetime,
    model: str = DEFAULT_MODEL,
    interval_minutes: int = DEFAULT_INTERVAL_MINUTES,
    daily_active_hours: float = DEFAULT_DAILY_ACTIVE_HOURS,
) -> dict[str, Any]:
    active_chats = []
    for active in active_roots:
        active_chats.append(project_chat_view(active, chat_reader(active.session_id)))
    return {
        "schema_version": 1,
        "generated_at": _now_iso(now),
        "model": model,
        "notifier_config": {
            "summary_model": model,
            "interval_minutes": interval_minutes,
            "daily_active_hours": daily_active_hours,
            "daily_runs_assumption": _runs_per_day(interval_minutes, daily_active_hours),
            "obsolete_current_claims": ["Gemini 3.5 Flash Lite", "gemini-3.5-flash-lite", "10-minute cadence", "10 minutes"],
        },
        "active_count": len(active_chats),
        "instructions": {
            "summary_shape": "short top text summary, then per-active-chat summaries with title, OpenCode link, and completed/current/next task lists",
            "privacy": "summarize only; do not quote secrets, raw tool output, reasoning, or attachment content",
        },
        "active_chats": active_chats,
    }


def fingerprint_evidence(evidence: dict[str, Any]) -> str:
    stable = {key: value for key, value in evidence.items() if key != "generated_at"}
    stable_chats = []
    for chat in stable.get("active_chats") or []:
        if not isinstance(chat, dict):
            stable_chats.append(chat)
            continue
        stable_chat = dict(chat)
        stable_chat.pop("updated_at", None)
        stable_chats.append(stable_chat)
    stable["active_chats"] = stable_chats
    encoded = json.dumps(stable, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def load_state(path: Path) -> dict[str, Any]:
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"schema_version": STATE_SCHEMA_VERSION, "last_digest": {}, "duplicate_suppressions": 0}
    if state.get("schema_version") != STATE_SCHEMA_VERSION:
        return {"schema_version": STATE_SCHEMA_VERSION, "last_digest": {}, "duplicate_suppressions": 0}
    state.setdefault("last_digest", {})
    state.setdefault("duplicate_suppressions", 0)
    return state


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        json.dump(state, handle, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)


@contextmanager
def state_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")
    with lock_path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _remove_managed_cron_block(lines: list[str]) -> list[str]:
    result: list[str] = []
    skipping = False
    for line in lines:
        if line.strip() == CRON_BEGIN:
            skipping = True
            continue
        if line.strip() == CRON_END:
            skipping = False
            continue
        if not skipping:
            result.append(line)
    return result


def render_crontab(existing: str, project_root: Path) -> str:
    lines = _remove_managed_cron_block(existing.splitlines())
    while lines and not lines[-1].strip():
        lines.pop()
    root = shlex.quote(str(project_root))
    runner = shlex.quote(str(project_root / "scripts" / "opencode_progress_notifier.py"))
    log_path = shlex.quote(str(project_root / "logs" / "opencode-progress-notifier.log"))
    lines.extend(
        [
            "",
            CRON_BEGIN,
            "# Every 15 minutes. Skips silently when no active chats or no DISCORD_WEBHOOK_AGENT_PROGRESS is configured.",
            f"{CRON_SCHEDULE} cd {root} && python3 {runner} --once >> {log_path} 2>&1",
            CRON_END,
        ]
    )
    return "\n".join(lines) + "\n"


def install_cron(project_root: Path) -> None:
    (project_root / "logs").mkdir(parents=True, exist_ok=True)
    current = subprocess.run(["crontab", "-l"], capture_output=True, text=True, check=False)
    if current.returncode not in (0, 1):
        raise RuntimeError(f"crontab -l failed: {current.stderr.strip()}")
    rendered = render_crontab(current.stdout, project_root)
    result = subprocess.run(["crontab", "-"], input=rendered, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"crontab installation failed: {result.stderr.strip()}")


def should_skip_duplicate(state: dict[str, Any], fingerprint: str, *, now: datetime, interval_minutes: int) -> bool:
    last = state.get("last_digest") if isinstance(state.get("last_digest"), dict) else {}
    if last.get("fingerprint") != fingerprint:
        return False
    sent_at = _parse_iso(str(last.get("sent_at") or ""))
    if not sent_at:
        return False
    return now - sent_at < timedelta(minutes=interval_minutes)


def record_duplicate_suppression(state: dict[str, Any], *, now: datetime) -> None:
    state["duplicate_suppressions"] = int(state.get("duplicate_suppressions") or 0) + 1
    state["last_suppressed_at"] = _now_iso(now)


def record_sent(state: dict[str, Any], *, fingerprint: str, now: datetime, active_count: int, model: str, message_id: str = "") -> None:
    state["last_digest"] = {
        "fingerprint": fingerprint,
        "sent_at": _now_iso(now),
        "active_count": active_count,
        "message_id": message_id,
        "model": model,
    }


def progress_summary_schema() -> dict[str, Any]:
    task_list = {"type": "array", "items": {"type": "string"}}
    chat_item = {
        "type": "object",
        "properties": {
            "session_id": {"type": "string"},
            "summary": {"type": "string"},
            "tasks": {
                "type": "object",
                "properties": {
                    "completed": task_list,
                    "current": task_list,
                    "next": task_list,
                },
                "required": ["completed", "current", "next"],
            },
            "important_decisions": {"type": "array", "items": {"type": "string"}},
            "watch_points": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["session_id", "summary", "tasks", "important_decisions", "watch_points"],
    }
    return {
        "type": "object",
        "properties": {
            "overall_summary": {"type": "string"},
            "summary_bullets": {"type": "array", "items": {"type": "string"}},
            "important_decisions": {"type": "array", "items": {"type": "string"}},
            "watch_points": {"type": "array", "items": {"type": "string"}},
            "chats": {"type": "array", "items": chat_item},
        },
        "required": ["overall_summary", "summary_bullets", "important_decisions", "watch_points", "chats"],
    }


def call_gemini_progress_summary(
    *,
    evidence: dict[str, Any],
    api_key: str,
    model: str = DEFAULT_GEMINI_MODEL,
    opener: Callable[..., Any] = request.urlopen,
) -> dict[str, Any]:
    if model != DEFAULT_GEMINI_MODEL:
        raise ProgressNotifierError(f"Progress summaries must use {DEFAULT_GEMINI_MODEL}")
    user_message = "Summarize this bounded active-chat evidence:\n" + json.dumps(evidence, ensure_ascii=False, sort_keys=True)
    tool = {
        "function_declarations": [
            {
                "name": "return_progress_digest",
                "description": "Return one active OpenCode progress digest.",
                "parameters": progress_summary_schema(),
            }
        ]
    }
    payload = {
        "system_instruction": {"parts": [{"text": GEMINI_SYSTEM_PROMPT}]},
        "contents": [{"role": "user", "parts": [{"text": user_message}]}],
        "tools": [tool],
        "tool_config": {"function_calling_config": {"mode": "ANY"}},
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 4096},
    }
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with opener(req, timeout=90) as response:
            response_payload = json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise ProgressNotifierError(f"Gemini API error {exc.code}: {detail}") from exc
    except (OSError, TimeoutError, json.JSONDecodeError) as exc:
        raise ProgressNotifierError(f"Gemini request failed: {exc}") from exc

    try:
        parts = response_payload.get("candidates", [])[0].get("content", {}).get("parts", [])
    except (AttributeError, IndexError) as exc:
        raise ProgressNotifierError("Gemini response did not include candidates") from exc
    for part in parts:
        function_call = part.get("functionCall") if isinstance(part, dict) else None
        if function_call and function_call.get("name") == "return_progress_digest":
            digest = function_call.get("args") or {}
            if isinstance(digest, dict):
                return {**digest, "_usage_metadata": response_payload.get("usageMetadata") or {}}
            return {"_usage_metadata": response_payload.get("usageMetadata") or {}}
    text_response = "\n".join(part.get("text", "") for part in parts if isinstance(part, dict)).strip()
    if text_response:
        try:
            digest = json.loads(text_response)
            if isinstance(digest, dict):
                return {**digest, "_usage_metadata": response_payload.get("usageMetadata") or {}}
            return {"_usage_metadata": response_payload.get("usageMetadata") or {}}
        except json.JSONDecodeError as exc:
            raise ProgressNotifierError("Gemini response was not valid JSON and did not include a function call") from exc
    raise ProgressNotifierError("Gemini response did not include a progress digest")


def _message_content_text(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "\n".join(parts).strip()
    return ""


def _parse_json_digest(text: str, *, provider_name: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned.removeprefix("```json").removesuffix("```").strip()
    elif cleaned.startswith("```"):
        cleaned = cleaned.removeprefix("```").removesuffix("```").strip()
    try:
        digest = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ProgressNotifierError(f"{provider_name} response was not valid JSON") from exc
    if not isinstance(digest, dict):
        raise ProgressNotifierError(f"{provider_name} response JSON was not an object")
    return digest


def call_mistral_progress_summary(
    *,
    evidence: dict[str, Any],
    api_key: str,
    model: str = DEFAULT_MISTRAL_MODEL,
    opener: Callable[..., Any] = request.urlopen,
) -> dict[str, Any]:
    if model != DEFAULT_MISTRAL_MODEL and not model.startswith("mistral-"):
        raise ProgressNotifierError(f"Unsupported Mistral progress summary model: {model}")
    user_message = "Summarize this bounded active-chat evidence as JSON:\n" + json.dumps(evidence, ensure_ascii=False, sort_keys=True)
    system_message = (
        GEMINI_SYSTEM_PROMPT
        + " Return only a JSON object matching this schema: "
        + json.dumps(progress_summary_schema(), ensure_ascii=False, sort_keys=True)
    )
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_message},
            {"role": "user", "content": user_message},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.2,
        "max_tokens": 4096,
    }
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(
        "https://api.mistral.ai/v1/chat/completions",
        data=body,
        headers={"Content-Type": "application/json", "Accept": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST",
    )
    try:
        with opener(req, timeout=90) as response:
            response_payload = json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise ProgressNotifierError(f"Mistral API error {exc.code}: {detail}") from exc
    except (OSError, TimeoutError, json.JSONDecodeError) as exc:
        raise ProgressNotifierError(f"Mistral request failed: {exc}") from exc

    try:
        message = response_payload.get("choices", [])[0].get("message", {})
    except (AttributeError, IndexError) as exc:
        raise ProgressNotifierError("Mistral response did not include choices") from exc
    text_response = _message_content_text(message.get("content"))
    if not text_response:
        raise ProgressNotifierError("Mistral response did not include content")
    digest = _parse_json_digest(text_response, provider_name="Mistral")
    return {**digest, "_usage_metadata": response_payload.get("usage") or {}}


def call_progress_summary(
    *,
    evidence: dict[str, Any],
    api_key: str,
    model: str = DEFAULT_MODEL,
) -> dict[str, Any]:
    if model == DEFAULT_GEMINI_MODEL:
        return call_gemini_progress_summary(evidence=evidence, api_key=api_key, model=model)
    if model == DEFAULT_MISTRAL_MODEL or model.startswith("mistral-"):
        return call_mistral_progress_summary(evidence=evidence, api_key=api_key, model=model)
    raise ProgressNotifierError(f"Unsupported progress summary model: {model}")


def _fallback_chat_summary(chat: dict[str, Any]) -> str:
    signals = chat.get("issue_signals") or []
    if signals:
        return _bounded_text("Latest issue signal: " + str(signals[0].get("text") or signals[0].get("kind") or "unknown"), 280)
    messages = chat.get("messages") or []
    for message in reversed(messages):
        for part in reversed(message.get("parts") or []):
            if part.get("type") == "text" and part.get("text"):
                return _bounded_text(part["text"], 280)
            if part.get("type") == "tool":
                return _bounded_text(f"Tool {part.get('tool', 'unknown')} is {part.get('status', 'unknown')}", 280)
    return "No detailed transcript activity was available in the bounded projection."


def normalize_digest(raw: dict[str, Any], active_chats: list[dict[str, Any]]) -> dict[str, Any]:
    digest = raw if isinstance(raw, dict) else {}
    raw_chats = digest.get("chats") if isinstance(digest.get("chats"), list) else []
    by_session = {str(item.get("session_id") or ""): item for item in raw_chats if isinstance(item, dict)}
    chats = []
    for chat in active_chats:
        session_id = str(chat.get("session_id") or "")
        summarized = by_session.get(session_id, {})
        exact_tasks = chat.get("task_items") if isinstance(chat.get("task_items"), list) else []
        chats.append(
            {
                "session_id": session_id,
                "title": _bounded_text(chat.get("title") or session_id, 160),
                "url": str(chat.get("url") or opencode_chat_url(session_id)),
                "status_label": _bounded_text(chat.get("status_label") or "active", 80),
                "summary": _display_text(summarized.get("summary") or _fallback_chat_summary(chat), 160),
                "tasks": exact_tasks or _task_items_from_digest(summarized.get("tasks")),
                "important_decisions": _string_list(summarized.get("important_decisions"), max_items=4, max_chars=220),
                "watch_points": _string_list(summarized.get("watch_points"), max_items=4, max_chars=220),
            }
        )
    overall = _display_text(digest.get("overall_summary") or f"{len(chats)} OpenCode chat(s) are currently active.", 170)
    return {
        "overall_summary": overall,
        "summary_bullets": [_display_text(item, 130) for item in _string_list(digest.get("summary_bullets"), max_items=3, max_chars=160)],
        "important_decisions": [_display_text(item, 140) for item in _string_list(digest.get("important_decisions"), max_items=3, max_chars=170)],
        "watch_points": [_display_text(item, 140) for item in _string_list(digest.get("watch_points"), max_items=3, max_chars=170)],
        "chats": chats,
    }


def _estimated_tokens(text: str) -> int:
    return max(1, (len(text) + ESTIMATED_CHARS_PER_TOKEN - 1) // ESTIMATED_CHARS_PER_TOKEN)


def _usage_token_count(usage_metadata: dict[str, Any], *keys: str) -> int:
    for key in keys:
        value = usage_metadata.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, int) and value >= 0:
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
    return 0


def _runs_per_day(interval_minutes: int, daily_active_hours: float) -> int:
    if interval_minutes <= 0 or daily_active_hours <= 0:
        return 0
    return int((daily_active_hours * 60) // interval_minutes)


def estimate_summary_cost(
    evidence: dict[str, Any],
    digest: dict[str, Any],
    *,
    usage_metadata: dict[str, Any] | None = None,
    model: str = DEFAULT_MODEL,
    interval_minutes: int = DEFAULT_INTERVAL_MINUTES,
    daily_active_hours: float = DEFAULT_DAILY_ACTIVE_HOURS,
) -> dict[str, Any]:
    usage_metadata = usage_metadata if isinstance(usage_metadata, dict) else {}
    input_tokens = _usage_token_count(usage_metadata, "prompt_tokens", "promptTokenCount", "prompt_token_count", "inputTokenCount", "input_token_count")
    output_tokens = _usage_token_count(usage_metadata, "completion_tokens", "candidatesTokenCount", "candidates_token_count", "outputTokenCount", "output_token_count")
    total_tokens = _usage_token_count(usage_metadata, "total_tokens", "totalTokenCount", "total_token_count")
    source = "usage"
    if input_tokens and not output_tokens and total_tokens >= input_tokens:
        output_tokens = total_tokens - input_tokens
    if not input_tokens or not output_tokens:
        input_text = GEMINI_SYSTEM_PROMPT + "\n" + json.dumps(progress_summary_schema(), ensure_ascii=False, sort_keys=True) + "\n" + json.dumps(evidence, ensure_ascii=False, sort_keys=True)
        output_text = json.dumps(digest, ensure_ascii=False, sort_keys=True)
        input_tokens = _estimated_tokens(input_text)
        output_tokens = _estimated_tokens(output_text)
        source = "character_estimate"
    pricing = MODEL_PRICING_USD_PER_MILLION_TOKENS.get(model) or MODEL_PRICING_USD_PER_MILLION_TOKENS[DEFAULT_MISTRAL_MODEL]
    input_price = pricing["input"]
    output_price = pricing["output"]
    input_usd = (input_tokens / 1_000_000) * input_price
    output_usd = (output_tokens / 1_000_000) * output_price
    estimated_usd = input_usd + output_usd
    runs_per_day = _runs_per_day(interval_minutes, daily_active_hours)
    return {
        "input_tokens_estimate": input_tokens,
        "output_tokens_estimate": output_tokens,
        "token_source": source,
        "input_usd_per_million_tokens": input_price,
        "output_usd_per_million_tokens": output_price,
        "estimated_usd": estimated_usd,
        "interval_minutes": interval_minutes,
        "daily_active_hours": daily_active_hours,
        "daily_runs": runs_per_day,
        "daily_estimated_usd": estimated_usd * runs_per_day,
    }


def _format_usd(value: float) -> str:
    if value < 0.01:
        return f"${value:.4f}"
    return f"${value:.2f}"


def _format_cost_estimate(cost: dict[str, Any] | None) -> str:
    if not cost:
        return "unavailable"
    input_tokens = int(cost.get("input_tokens_estimate") or 0)
    output_tokens = int(cost.get("output_tokens_estimate") or 0)
    estimated_usd = float(cost.get("estimated_usd") or 0)
    daily_runs = int(cost.get("daily_runs") or 0)
    daily_estimated_usd = float(cost.get("daily_estimated_usd") or 0)
    daily_active_hours = float(cost.get("daily_active_hours") or 0)
    source = "metered" if cost.get("token_source") in {"usage", "usageMetadata"} else "est."
    return (
        f"~{_format_usd(estimated_usd)}/run · ~{_format_usd(daily_estimated_usd)}/day "
        f"({daily_runs} runs over {daily_active_hours:g}h; {source}: {input_tokens / 1000:.1f}k in, {output_tokens / 1000:.1f}k out; "
        f"${float(cost.get('input_usd_per_million_tokens') or 0):.2f}/M in, ${float(cost.get('output_usd_per_million_tokens') or 0):.2f}/M out)"
    )


def _fit_discord_content(content: str) -> str:
    if len(content) <= MAX_DISCORD_CONTENT_CHARS:
        return content
    suffix = "\n\n...[truncated to fit Discord; open the linked chats for full context]"
    return content[: MAX_DISCORD_CONTENT_CHARS - len(suffix)].rstrip() + suffix


def _fit_discord_embed_description(content: str) -> str:
    if len(content) <= MAX_DISCORD_EMBED_DESCRIPTION_CHARS:
        return content
    suffix = "\n\n...[truncated to fit Discord; open the linked chats for full context]"
    return content[: MAX_DISCORD_EMBED_DESCRIPTION_CHARS - len(suffix)].rstrip() + suffix


def _discord_link_label(value: Any, max_chars: int = 80) -> str:
    text = _bounded_text(value, max_chars)
    return (
        text.replace("\\", "\\\\")
        .replace("[", "\\[")
        .replace("]", "\\]")
        .replace("(", "\\(")
        .replace(")", "\\)")
    )


def _render_task_lines(tasks: list[dict[str, str]], *, max_items: int) -> list[str]:
    if not tasks or max_items <= 0:
        return ["Next: not identified"]
    grouped = {
        "in_progress": [task for task in tasks if _normalize_task_status(task.get("status")) == "in_progress"],
        "pending": [task for task in tasks if _normalize_task_status(task.get("status")) == "pending"],
        "completed": [task for task in tasks if _normalize_task_status(task.get("status")) == "completed"],
        "cancelled": [task for task in tasks if _normalize_task_status(task.get("status")) == "cancelled"],
    }
    lines = []
    slots = (
        ("in_progress", "Now", 1),
        ("pending", "Next", 1),
        ("completed", "Done", 2),
        ("cancelled", "Canceled", 1),
    )
    for status, label, per_status_limit in slots:
        for task in grouped[status][:per_status_limit]:
            lines.append(f"{label}: {_display_text(task.get('content') or '', 110)}")
            if len(lines) >= max_items:
                return lines
    ordered = grouped["in_progress"] + grouped["pending"] + grouped["completed"] + grouped["cancelled"]
    if len(ordered) > max_items:
        lines.append(f"... +{len(ordered) - max_items} more")
    return lines


def _chat_block(index: int, chat: dict[str, Any], *, summary_limit: int, task_limit: int, include_details: bool, compact_label: bool) -> str:
    label_source = chat.get("session_id") if compact_label else (chat.get("title") or chat.get("session_id") or "Untitled chat")
    title = _discord_link_label(label_source)
    url = str(chat.get("url") or "")
    status = _bounded_text(chat.get("status_label") or "active", 80)
    lines = [f"**{index}. [{title}]({url})**", f"Status: `{status}`"]
    if summary_limit > 0:
        lines.extend(["", f"Summary: {_display_text(chat.get('summary') or 'No summary returned.', summary_limit)}"])
    if task_limit > 0:
        lines.extend(["", "Tasks:"])
        lines.extend(_render_task_lines(chat.get("tasks") or [], max_items=task_limit))
    if include_details and chat.get("important_decisions"):
        lines.extend(["", "Decision: " + _display_text("; ".join(chat["important_decisions"]), 140)])
    if include_details and chat.get("watch_points"):
        lines.append("Watch: " + _display_text("; ".join(chat["watch_points"]), 140))
    return "\n".join(lines)


def _chunk_chat_blocks(blocks: list[str]) -> list[str]:
    chunks: list[str] = []
    current = "**Active Chats**"
    continued_header = "**Active Chats (continued)**"
    for block in blocks:
        separator = "\n\n" if current else ""
        candidate = current + separator + block
        if len(candidate) <= MAX_DISCORD_EMBED_DESCRIPTION_CHARS:
            current = candidate
            continue
        if current:
            chunks.append(current)
        current = continued_header + "\n" + _fit_discord_embed_description(block)
    if current:
        chunks.append(current)
    return chunks


def _embed_descriptions_fit(chunks: list[str]) -> bool:
    return (
        len(chunks) <= 9
        and all(len(chunk) <= MAX_DISCORD_EMBED_DESCRIPTION_CHARS for chunk in chunks)
        and _embed_total_chars(chunks) <= MAX_DISCORD_EMBED_TOTAL_CHARS
    )


def _embed_title_chars(count: int) -> int:
    if count <= 0:
        return 0
    return len(ACTIVE_CHATS_EMBED_TITLE) + ((count - 1) * len(ACTIVE_CHATS_CONTINUED_EMBED_TITLE))


def _embed_total_chars(chunks: list[str]) -> int:
    return sum(len(chunk) for chunk in chunks) + _embed_title_chars(len(chunks))


def _fit_embed_descriptions_total(chunks: list[str]) -> list[str]:
    fitted: list[str] = []
    remaining = MAX_DISCORD_EMBED_TOTAL_CHARS - _embed_title_chars(min(len(chunks), 9))
    suffix = "\n\n...[truncated to fit Discord; open the linked chats for full context]"
    for chunk in chunks[:9]:
        limit = min(MAX_DISCORD_EMBED_DESCRIPTION_CHARS, remaining)
        if limit <= 0:
            break
        if len(chunk) <= limit:
            fitted.append(chunk)
            remaining -= len(chunk)
            continue
        if limit <= len(suffix):
            break
        fitted.append(chunk[: limit - len(suffix)].rstrip() + suffix)
        break
    return fitted


def _render_active_chat_descriptions(chats: list[dict[str, Any]]) -> list[str]:
    for summary_limit, task_limit in ((160, 5), (120, 4), (80, 3), (50, 2), (0, 2), (0, 1), (0, 0)):
        include_details = summary_limit >= 160 and len(chats) <= 3
        compact_label = summary_limit == 0 and task_limit <= 1
        blocks = [
            _chat_block(index, chat, summary_limit=summary_limit, task_limit=task_limit, include_details=include_details, compact_label=compact_label)
            for index, chat in enumerate(chats, start=1)
        ]
        chunks = _chunk_chat_blocks(blocks)
        if _embed_descriptions_fit(chunks):
            return chunks
    return _fit_embed_descriptions_total(chunks)


def build_discord_payload(
    digest: dict[str, Any],
    *,
    active_count: int,
    now: datetime,
    model: str = DEFAULT_MODEL,
    cost_estimate: dict[str, Any] | None = None,
) -> dict[str, Any]:
    lines = [
        "**OpenCode Progress**",
        f"{active_count} active · `{model}` · `{_now_iso(now)}`",
        "",
        f"Cost: {_format_cost_estimate(cost_estimate)}",
        "",
        "**Summary**",
        str(digest.get("overall_summary") or "No overall summary returned."),
    ]
    summary_bullets = digest.get("summary_bullets") or []
    for item in summary_bullets[:3]:
        lines.append(f"• {_display_text(item, 130)}")
    decisions = digest.get("important_decisions") or []
    watch_points = digest.get("watch_points") or []
    if decisions:
        lines.extend(["", "**Decisions**"])
        lines.extend(f"• {_display_text(item, 140)}" for item in decisions[:3])
    if watch_points:
        lines.extend(["", "**Watch**"])
        lines.extend(f"• {_display_text(item, 140)}" for item in watch_points[:3])
    chats = digest.get("chats") if isinstance(digest.get("chats"), list) else []
    embeds = [
        {
            "title": ACTIVE_CHATS_EMBED_TITLE if index == 0 else ACTIVE_CHATS_CONTINUED_EMBED_TITLE,
            "description": description,
            "color": 0x3B82F6,
        }
        for index, description in enumerate(_render_active_chat_descriptions(chats))
    ]
    return {
        "username": "OpenMates Agent Progress",
        "avatar_url": "https://openmates.org/favicon.png",
        "allowed_mentions": {"parse": []},
        "content": _fit_discord_content("\n".join(lines)),
        "embeds": embeds,
    }


def run_once(
    *,
    status_loader: Callable[[], dict[str, Any]] = load_status,
    chat_reader: Callable[[str], dict[str, Any]] = read_chat_view,
    summarizer: Callable[..., dict[str, Any]] = call_progress_summary,
    discord_sender: Callable[..., dict[str, str] | None] = post_message,
    state_path: Path = DEFAULT_STATE_FILE,
    api_key: str | None = None,
    webhook_url: str = "",
    interval_minutes: int = DEFAULT_INTERVAL_MINUTES,
    daily_active_hours: float = DEFAULT_DAILY_ACTIVE_HOURS,
    max_chats: int = MAX_ACTIVE_CHATS,
    model: str = DEFAULT_MODEL,
    force: bool = False,
    dry_run: bool = False,
    update_state: bool = True,
    now: datetime | None = None,
) -> dict[str, Any]:
    current_time = now or datetime.now(timezone.utc)
    status = status_loader()
    active_roots = select_active_chat_roots(status, max_chats=max_chats)
    if not active_roots:
        return {"status": "skipped_no_active_chats", "active_count": 0, "model": model}
    if not webhook_url and not dry_run:
        return {"status": "skipped_missing_webhook", "active_count": len(active_roots), "model": model}

    evidence = build_evidence(
        active_roots,
        chat_reader=chat_reader,
        now=current_time,
        model=model,
        interval_minutes=interval_minutes,
        daily_active_hours=daily_active_hours,
    )
    fingerprint = fingerprint_evidence(evidence)
    lock_context = state_lock(state_path) if update_state and not dry_run else nullcontext()
    with lock_context:
        state = load_state(state_path)
        if not force and should_skip_duplicate(state, fingerprint, now=current_time, interval_minutes=interval_minutes):
            if update_state:
                record_duplicate_suppression(state, now=current_time)
                save_state(state_path, state)
            return {
                "status": "skipped_duplicate",
                "active_count": len(active_roots),
                "fingerprint": fingerprint,
                "model": model,
            }

        key = api_key or load_model_api_key(model)
        raw_digest = summarizer(evidence=evidence, api_key=key, model=model)
        digest = normalize_digest(raw_digest, evidence["active_chats"])
        usage_metadata = raw_digest.get("_usage_metadata") if isinstance(raw_digest, dict) else None
        cost_estimate = estimate_summary_cost(
            evidence,
            raw_digest if isinstance(raw_digest, dict) else digest,
            usage_metadata=usage_metadata,
            model=model,
            interval_minutes=interval_minutes,
            daily_active_hours=daily_active_hours,
        )
        payload = build_discord_payload(digest, active_count=len(evidence["active_chats"]), now=current_time, model=model, cost_estimate=cost_estimate)
        if dry_run:
            return {
                "status": "dry_run",
                "active_count": len(evidence["active_chats"]),
                "fingerprint": fingerprint,
                "model": model,
                "cost_estimate": cost_estimate,
                "payload": payload,
            }
        result = discord_sender(webhook_url=webhook_url, payload=payload)
        if not result:
            return {
                "status": "failed_discord",
                "active_count": len(evidence["active_chats"]),
                "fingerprint": fingerprint,
                "model": model,
            }
        if update_state:
            record_sent(state, fingerprint=fingerprint, now=current_time, active_count=len(evidence["active_chats"]), model=model, message_id=result.get("message_id", ""))
            save_state(state_path, state)
        return {
            "status": "sent",
            "active_count": len(evidence["active_chats"]),
            "fingerprint": fingerprint,
            "message_id": result.get("message_id", ""),
            "model": model,
            "cost_estimate": cost_estimate,
            "payload": payload,
        }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Post Discord progress summaries for active OpenCode chats.")
    parser.add_argument("--once", action="store_true", help="Run one notifier tick and exit (default unless --watch is set).")
    parser.add_argument("--watch", action="store_true", help="Run continuously, sleeping --interval-minutes between ticks.")
    parser.add_argument("--interval-minutes", type=int, default=DEFAULT_INTERVAL_MINUTES, help="Notification cadence and duplicate suppression window.")
    parser.add_argument("--daily-active-hours", type=float, default=DEFAULT_DAILY_ACTIVE_HOURS, help="Active notifier hours per day used for displayed cost projection.")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Summary model. Default: mistral-small-latest; gemini-3.5-flash-lite remains available for comparison.")
    parser.add_argument("--dry-run", action="store_true", help="Call the summary model and print the Discord payload without posting to Discord.")
    parser.add_argument("--force", action="store_true", help="Bypass duplicate suppression for this tick.")
    parser.add_argument("--no-state-update", action="store_true", help="Do not write .opencode/progress-notifier-state.json.")
    parser.add_argument("--max-chats", type=int, default=MAX_ACTIVE_CHATS, help="Maximum top-level active chats to summarize.")
    parser.add_argument("--webhook-env", default=DISCORD_ENV, help="Environment/.env key containing the Discord webhook URL.")
    parser.add_argument("--state-file", type=Path, default=DEFAULT_STATE_FILE, help="Local dedupe state path.")
    parser.add_argument("--install-cron", action="store_true", help="Install or refresh the managed 15-minute cron entry.")
    parser.add_argument("--json", action="store_true", help="Print structured result JSON.")
    return parser


def _print_result(result: dict[str, Any], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True))
        return
    status = result.get("status")
    if status == "dry_run":
        payload = result.get("payload", {})
        print(payload.get("content", ""))
        for embed in payload.get("embeds") or []:
            if isinstance(embed, dict) and embed.get("description"):
                print()
                print(embed["description"])
        return
    if status == "skipped_no_active_chats":
        print("No active OpenCode chats; skipped progress summary.")
        return
    print(f"OpenCode progress notifier: {status} ({result.get('active_count', 0)} active chat(s))")


def main() -> int:
    args = build_parser().parse_args()
    if args.interval_minutes <= 0:
        raise SystemExit("--interval-minutes must be positive")
    if args.max_chats <= 0:
        raise SystemExit("--max-chats must be positive")
    if args.daily_active_hours <= 0:
        raise SystemExit("--daily-active-hours must be positive")
    if args.install_cron:
        install_cron(CONTROL_PLANE_ROOT)
        print(f"[opencode-progress] installed 15-minute cron for {CONTROL_PLANE_ROOT}")
        return 0
    webhook_url = _dotenv_value(CONTROL_PLANE_ROOT, args.webhook_env)
    while True:
        result = run_once(
            webhook_url=webhook_url,
            interval_minutes=args.interval_minutes,
            daily_active_hours=args.daily_active_hours,
            max_chats=args.max_chats,
            model=args.model,
            force=args.force,
            dry_run=args.dry_run,
            update_state=not args.no_state_update and not args.dry_run,
            state_path=args.state_file,
        )
        _print_result(result, as_json=args.json)
        if not args.watch:
            return 0
        time.sleep(args.interval_minutes * 60)


if __name__ == "__main__":
    raise SystemExit(main())
