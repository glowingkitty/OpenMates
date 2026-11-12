"""Internal ``save_memory`` tool: the assistant creates or updates one personal Memory.

Personal Memories are client-encrypted, so the server never stores them. The
tool validates the requested fields into one canonical document, then hands a
short-lived cleartext write job to the user's capable device that has this chat
open. That device claims the job, encrypts and stores the Memory, and reports
the outcome; the tool result tells the model what the device actually did in
this turn. Redis holds only ids, state and the outcome, never the document;
the document travels once over the transient chat-stream channel, like the
streamed answer itself.

Wire contract (protocol 1), see ``SAVE_MEMORY_*`` constants:
  server -> client  ``memory_write_job_available``   {protocol, job_id, chat_id, message_id,
                                                      action, memory_id, title, document, expires_at}
  client -> server  ``memory_write_job_claim``       {protocol, job_id, chat_id}
  server -> client  ``memory_write_job_claim_result``{job_id, chat_id, granted, reason}
  client -> server  ``memory_write_job_result``      {protocol, job_id, chat_id, status: applied|failed,
                                                      memory_id, error_code}
  server -> client  ``memory_write_job_result_ack``  {job_id, chat_id, accepted, reason}

Project target: under an authorized active Project Focus with Project file
tools, ``target: "project"`` turns the call into one ``project_create_file``
operation for ``.openmates/memories/<id>.md`` (see
``project_memory_file_arguments``). The client then encrypts and stores it as a
Project file through the existing Project file job path, with its revision
history; nothing is written as a personal Memory.

Privacy: title, when_to_use and content are never logged; logs carry ids,
action and sizes only.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from typing import Any, Iterable

from backend.apps.ai.processing.memory_document import (
    LOAD_MODES,
    MemoryDocumentError,
    validated_memory_document,
)

logger = logging.getLogger(__name__)

SAVE_MEMORY_TOOL_NAME = "save_memory"
MEMORY_WRITE_CAPABILITY = "memory_write_jobs"
# Load mode of assistant-saved Memories when the model does not choose one.
# A product decision on this default is pending; keep it in this one constant.
DEFAULT_ASSISTANT_MEMORY_LOAD_MODE = "ask_first"

MEMORY_WRITE_PROTOCOL = 1
MEMORY_WRITE_JOB_EVENT = "memory_write_job_available"
MEMORY_WRITE_CLAIM_MESSAGE = "memory_write_job_claim"
MEMORY_WRITE_CLAIM_RESULT_MESSAGE = "memory_write_job_claim_result"
MEMORY_WRITE_RESULT_MESSAGE = "memory_write_job_result"
MEMORY_WRITE_RESULT_ACK_MESSAGE = "memory_write_job_result_ack"
MEMORY_WRITE_CLAIM_TIMEOUT_SECONDS = 8.0
MEMORY_WRITE_RESULT_TIMEOUT_SECONDS = 20.0
MEMORY_WRITE_JOB_TTL_SECONDS = 120
MEMORY_WRITE_POLL_SECONDS = 0.25
_EXPIRED_CLAIM = "__expired__"
_ERROR_CODE = re.compile(r"^[a-z0-9_]{1,64}$")
SAVE_MEMORY_TARGETS = ("personal", "project")
PROJECT_MEMORY_DIRECTORY = ".openmates/memories"
PROJECT_MEMORY_FILE_TOOL = "project_create_file"

SAVE_MEMORY_TOOL_INSTRUCTION = """Saving Memories
save_memory creates or updates one personal Memory of the user. Use it only when
the user asks you to remember or save something, or has clearly agreed to your
offer to save it; never save without that. Write a short title, one sentence
when_to_use and a Markdown body without frontmatter. Update only a Memory whose
full text is loaded in this conversation, and keep what still applies. Never
save secrets, passwords, keys or tokens. Say a Memory was saved or updated only
after save_memory returned status applied; otherwise say plainly it was not saved.
"""

SAVE_PROJECT_MEMORY_TOOL_INSTRUCTION = """Saving Memories to the active Project
A Project is active with write access, so save_memory also accepts target
"project": the Memory is stored in this Project's Memories, not in the user's
personal Memories. Use it for knowledge that belongs to this Project or company
(for example a press style), and only after the user agreed to save it there.
It creates a new Project Memory; to change an existing one, read its file in
.openmates/memories with project_read_text and apply project_update_file. Say it
was saved only after the Project file operation reports success.
"""


class MemoryWriteToolError(ValueError):
    """A model-facing rejection. Messages never echo Memory text."""


def save_memory_tool(*, project_target: bool = False, personal: bool = True) -> dict[str, Any]:
    """Internal-only function definition; no REST route or skill-use card exists.

    ``project_target`` adds the ``target`` choice; offer it only when the chat has an
    authorized active Project Focus and the Project file tools in this turn.
    ``personal=False`` (a client without personal memory jobs) offers only the Project.
    """
    if not personal and not project_target:
        raise ValueError("save_memory needs a personal or a project target")
    tool = {"type": "function", "function": {
        "name": SAVE_MEMORY_TOOL_NAME,
        "description": ("Create or update one personal Memory of the user, saved encrypted by the user's device. "
                        "Only after the user asked to remember something or agreed to save it."),
        "parameters": {"type": "object", "properties": {
            "action": {"type": "string", "enum": ["create", "update"]},
            "memory_id": {"type": "string", "description": "Required for update: id of a Memory loaded in this conversation."},
            "title": {"type": "string", "description": "Short title."},
            "when_to_use": {"type": "string", "description": "One sentence on when this Memory applies."},
            "content": {"type": "string", "description": "Markdown body, no frontmatter."},
            "load_mode": {"type": "string", "enum": list(LOAD_MODES),
                          "description": f"Optional; {DEFAULT_ASSISTANT_MEMORY_LOAD_MODE} by default."},
            "valid_from": {"type": "string", "description": "Optional ISO date."},
            "valid_until": {"type": "string", "description": "Optional ISO date."},
        }, "required": ["action", "title", "when_to_use", "content"], "additionalProperties": False},
    }}
    if project_target:
        tool["function"]["parameters"]["properties"]["target"] = {
            "type": "string", "enum": list(SAVE_MEMORY_TARGETS) if personal else ["project"],
            "description": ("personal (default) or project: save to the active Project's Memories." if personal
                            else "project: save to the active Project's Memories.")}
    if not personal:
        tool["function"]["description"] = (
            "Create one Memory in the active Project's Memories, saved encrypted by the user's device. "
            "Only after the user agreed to save it there.")
        tool["function"]["parameters"]["required"].append("target")
    return tool


def is_save_memory_tool_name(name: Any) -> bool:
    return isinstance(name, str) and name.replace("-", "_") == SAVE_MEMORY_TOOL_NAME


def save_memory_enabled(request: Any) -> bool:
    """Offered only to a signed-in user's capable client in a normal, saved, top-level chat."""
    capabilities = getattr(request, "client_capabilities", None) or []
    return MEMORY_WRITE_CAPABILITY in capabilities and save_memory_chat_allowed(request)


def save_memory_chat_allowed(request: Any) -> bool:
    """A signed-in user's normal, saved, top-level chat; capability checks are separate.

    Project saves need only this plus the authorized Project file tools of the turn,
    because the Project file job (not the personal memory job) stores them.
    """
    return bool(
        getattr(request, "user_id", None) and getattr(request, "chat_id", None)
        and not getattr(request, "is_incognito", False)
        and not getattr(request, "is_anonymous", False)
        and not getattr(request, "is_external", False)
        and not getattr(request, "is_sub_chat", False)
        and not getattr(request, "is_sub_chat_continuation", False)
        and not (getattr(request, "sub_chat_depth", 0) or 0)
    )


def loaded_personal_memory_ids(memories: Iterable[Any]) -> set[str]:
    """Ids of personal Memories whose complete body is in this turn's context."""
    return {m.id for m in memories if getattr(m, "source", None) == "personal" and isinstance(m.id, str)}


def prepare_memory_write(arguments: Any, *, loaded_ids: set[str], chat_id: str, message_id: str) -> dict[str, Any]:
    """Validate the call into a client job. Raises MemoryWriteToolError with a model-facing reason."""
    if not isinstance(arguments, dict):
        raise MemoryWriteToolError("save_memory arguments must be an object.")
    allowed = {"action", "memory_id", "title", "when_to_use", "content", "load_mode", "valid_from", "valid_until",
               "target"}
    if set(arguments) - allowed:
        raise MemoryWriteToolError("Unknown save_memory arguments.")
    if arguments.get("target") not in (None, "personal"):
        raise MemoryWriteToolError(
            "Saving to a Project needs an active Project Focus with write access in this chat. Nothing was saved. "
            "Offer a personal Memory instead, or tell the user they can add it in the Project's Memories tab.")
    action = arguments.get("action")
    if action not in ("create", "update"):
        raise MemoryWriteToolError("action must be create or update.")
    load_mode = arguments.get("load_mode") or DEFAULT_ASSISTANT_MEMORY_LOAD_MODE
    if load_mode not in LOAD_MODES:
        raise MemoryWriteToolError("load_mode must be auto_include, ask_first or mention_only.")
    if action == "update":
        memory_id = arguments.get("memory_id")
        if not isinstance(memory_id, str) or memory_id not in loaded_ids:
            raise MemoryWriteToolError(
                "That Memory is not loaded in this conversation, so it cannot be updated. Ask the user to load it "
                "first, or create a new Memory instead.")
    else:
        memory_id = str(uuid.uuid4())
    try:
        fields = validated_memory_document(arguments, load_mode=load_mode)
    except MemoryDocumentError as exc:
        raise MemoryWriteToolError(_document_reason(str(exc))) from exc
    now = int(time.time())
    return {
        "protocol": MEMORY_WRITE_PROTOCOL, "job_id": f"memory-write-job-{uuid.uuid4()}", "action": action,
        "memory_id": memory_id, "document": fields["body"], "title": fields["title"],
        "chat_id": chat_id, "message_id": message_id, "expires_at": now + MEMORY_WRITE_JOB_TTL_SECONDS,
    }


def is_project_memory_call(arguments: Any) -> bool:
    return isinstance(arguments, dict) and arguments.get("target") == "project"


def with_default_project_target(arguments: Any, *, personal_available: bool) -> Any:
    """Without personal memory jobs the only possible target is the Project."""
    if not personal_available and isinstance(arguments, dict) and arguments.get("target") is None:
        return {**arguments, "target": "project"}
    return arguments


def project_memory_file_arguments(arguments: Any) -> dict[str, Any]:
    """Turn a ``target: "project"`` save into ``project_create_file`` arguments.

    The document is the same canonical Memory Markdown that personal Memories use,
    so the Project Memories tab and the Memory loader read it unchanged. Raises
    MemoryWriteToolError with a model-facing reason.
    """
    if not is_project_memory_call(arguments):
        raise MemoryWriteToolError("target must be project.")
    allowed = {"action", "title", "when_to_use", "content", "load_mode", "valid_from", "valid_until", "target"}
    if set(arguments) - allowed:
        raise MemoryWriteToolError(
            "Unknown save_memory arguments for a Project Memory (memory_id is only for personal updates).")
    if arguments.get("action") != "create":
        raise MemoryWriteToolError(
            "save_memory only creates Project Memories. To change one, read its file in "
            f"{PROJECT_MEMORY_DIRECTORY} with project_read_text and apply project_update_file.")
    load_mode = arguments.get("load_mode") or DEFAULT_ASSISTANT_MEMORY_LOAD_MODE
    if load_mode not in LOAD_MODES:
        raise MemoryWriteToolError("load_mode must be auto_include, ask_first or mention_only.")
    try:
        fields = validated_memory_document(arguments, load_mode=load_mode)
    except MemoryDocumentError as exc:
        raise MemoryWriteToolError(_document_reason(str(exc))) from exc
    return {"path": f"{PROJECT_MEMORY_DIRECTORY}/{uuid.uuid4()}.md", "expected_base": None,
            "content": fields["body"]}


def _document_reason(reason: str) -> str:
    return {
        "secret detected": "The Memory looks like it contains a secret (password, key or token). Never save secrets.",
        "content is too long": "content is too long; keep the Memory shorter.",
        "document is too long": "The Memory document is too long; keep it shorter.",
        "invalid date": "valid_from and valid_until must be ISO dates such as 2027-01-31.",
        "unknown load mode": "load_mode must be auto_include, ask_first or mention_only.",
        "non-canonical document": "The Memory could not form a valid document (check dates and text).",
    }.get(reason, "title, when_to_use and content are required and must be plain text.")


def _claimant(device_hash: str) -> str:
    # Prefixed so the cache's JSON decoding always returns this exact string.
    return f"device:{device_hash}"


def _key(user_id: str, job_id: str, part: str = "") -> str:
    return f"memory_write_job:v1:{user_id}:{job_id}{':' + part if part else ''}"


async def _set_once(cache_service: Any, key: str, value: str) -> bool:
    client = await cache_service.client
    if client is None:
        raise RuntimeError("cache unavailable")
    return bool(await client.set(key, value, nx=True, ex=MEMORY_WRITE_JOB_TTL_SECONDS))


async def _wait_for(cache_service: Any, key: str, timeout: float) -> Any:
    deadline = time.monotonic() + timeout
    while True:
        value = await cache_service.get(key)
        if value is not None or time.monotonic() >= deadline:
            return value
        await asyncio.sleep(MEMORY_WRITE_POLL_SECONDS)


async def claim_memory_write_job(cache_service: Any, *, user_id: str, device_hash: str,
                                 payload: Any) -> tuple[bool, str]:
    """First capable device wins; an expired job can no longer be claimed."""
    if not isinstance(payload, dict) or payload.get("protocol") != MEMORY_WRITE_PROTOCOL:
        return False, "unsupported_protocol"
    job_id, chat_id = payload.get("job_id"), payload.get("chat_id")
    record = await cache_service.get(_key(user_id, str(job_id))) if isinstance(job_id, str) else None
    if not isinstance(record, dict) or record.get("chat_id") != chat_id:
        return False, "not_found"
    if not await _set_once(cache_service, _key(user_id, job_id, "claim"), _claimant(device_hash)):
        return False, "already_claimed"
    return True, "granted"


async def record_memory_write_result(cache_service: Any, *, user_id: str, device_hash: str,
                                     payload: Any) -> tuple[bool, str]:
    """Accept one outcome from the claiming device; never stores Memory text."""
    if not isinstance(payload, dict) or payload.get("protocol") != MEMORY_WRITE_PROTOCOL:
        return False, "unsupported_protocol"
    job_id, status, error_code = payload.get("job_id"), payload.get("status"), payload.get("error_code")
    record = await cache_service.get(_key(user_id, str(job_id))) if isinstance(job_id, str) else None
    if not isinstance(record, dict) or record.get("chat_id") != payload.get("chat_id"):
        return False, "not_found"
    claimant = await cache_service.get(_key(user_id, job_id, "claim"))
    if claimant != _claimant(device_hash):
        return False, "not_claimed_by_device"
    if status not in ("applied", "failed") or (status == "applied" and payload.get("memory_id") != record.get("memory_id")):
        return False, "invalid_result"
    if error_code is not None and (not isinstance(error_code, str) or not _ERROR_CODE.match(error_code)):
        return False, "invalid_result"
    result = {"status": status, "memory_id": record.get("memory_id"), "error_code": error_code if status == "failed" else None}
    if not await _set_once(cache_service, _key(user_id, job_id, "result"), json.dumps(result)):
        return False, "already_reported"
    logger.info("[MEMORY_WRITE] result job=%s memory=%s status=%s", job_id, record.get("memory_id"), status)
    return True, "accepted"


async def dispatch_save_memory(*, arguments: Any, request: Any, approved_memories: Iterable[Any],
                               cache_service: Any, log_prefix: str = "",
                               claim_timeout: float = MEMORY_WRITE_CLAIM_TIMEOUT_SECONDS,
                               result_timeout: float = MEMORY_WRITE_RESULT_TIMEOUT_SECONDS) -> dict[str, Any]:
    """Run one save_memory call end to end and return the truthful model-facing result."""
    try:
        job = prepare_memory_write(arguments, loaded_ids=loaded_personal_memory_ids(approved_memories),
                                   chat_id=request.chat_id, message_id=request.message_id)
    except MemoryWriteToolError as exc:
        logger.info("%s [MEMORY_WRITE] rejected action=%s", log_prefix,
                    arguments.get("action") if isinstance(arguments, dict) else None)
        return {"status": "rejected", "message": str(exc)}
    user_id, job_id = request.user_id, job["job_id"]
    record = {key: job[key] for key in ("job_id", "action", "memory_id", "chat_id", "message_id", "expires_at")}
    logger.info("%s [MEMORY_WRITE] job=%s action=%s memory=%s document_chars=%d", log_prefix, job_id,
                job["action"], job["memory_id"], len(job["document"]))
    if cache_service is None or not await cache_service.set(_key(user_id, job_id), record,
                                                            ttl=MEMORY_WRITE_JOB_TTL_SECONDS):
        return {"status": "failed", "message": "Saving Memories is unavailable right now. Tell the user it was not saved."}
    await cache_service.publish_event(f"chat_stream::{request.chat_id}", {
        "type": MEMORY_WRITE_JOB_EVENT, "user_id_uuid": user_id,
        "user_id_hash": getattr(request, "user_id_hash", None), **job,
    })
    claimant = await _wait_for(cache_service, _key(user_id, job_id, "claim"), claim_timeout)
    if claimant is None and await _set_once(cache_service, _key(user_id, job_id, "claim"), _EXPIRED_CLAIM):
        logger.info("%s [MEMORY_WRITE] job=%s not claimed", log_prefix, job_id)
        return {"status": "not_saved", "message": (
            "No device of the user picked up the save, so the Memory was NOT saved. Tell the user plainly; "
            "they can ask again with the chat open in the app.")}
    result = await _wait_for(cache_service, _key(user_id, job_id, "result"), result_timeout)
    if not isinstance(result, dict):
        logger.info("%s [MEMORY_WRITE] job=%s no result", log_prefix, job_id)
        return {"status": "unconfirmed", "memory_id": job["memory_id"], "message": (
            "The user's device took the save but did not confirm it in time. Do not say it was saved; "
            "tell the user to check their Memories.")}
    if result.get("status") != "applied":
        logger.info("%s [MEMORY_WRITE] job=%s failed code=%s", log_prefix, job_id, result.get("error_code"))
        return {"status": "failed", "error_code": result.get("error_code"),
                "message": "The user's device could not save the Memory. Tell the user it was not saved."}
    record_turn_write(request, kind="memory", target_id=job["memory_id"], title=job["title"])
    return {"status": "applied", "action": job["action"], "memory_id": job["memory_id"], "title": job["title"],
            "load_mode": arguments.get("load_mode") or DEFAULT_ASSISTANT_MEMORY_LOAD_MODE,
            "message": f"Memory {'created' if job['action'] == 'create' else 'updated'}. The user can undo it in the chat."}


def record_turn_write(request: Any, *, kind: str, target_id: Any, title: Any) -> None:
    """Remember a write of this turn (in process memory only) for the post-processor."""
    entries = getattr(request, "turn_written_entries", None)
    if not isinstance(entries, list):
        return
    entries.append({"kind": kind, "target_id": str(target_id) if target_id else None,
                    "title": title if isinstance(title, str) else ""})


def record_workflow_writes(request: Any, app_id: str, skill_id: str, results: Any) -> None:
    """Record workflows saved by the workflows create-or-modify skill in this turn."""
    if app_id != "workflows" or skill_id.replace("_", "-") != "create-or-modify" or not isinstance(results, list):
        return
    for response in results:
        if not isinstance(response, dict) or response.get("success") is not True:
            continue
        if response.get("status") not in ("finished", "draft"):
            continue
        workflows = response.get("workflows") or ([response["workflow"]] if isinstance(response.get("workflow"), dict) else [])
        for workflow in workflows:
            if isinstance(workflow, dict) and (workflow.get("workflow_id") or workflow.get("id")):
                record_turn_write(request, kind="workflow", target_id=workflow.get("workflow_id") or workflow.get("id"),
                                  title=workflow.get("title"))
