"""Finalize the chat's parent app_skill_use card of a cloud terminal command.

main_processor publishes the parent placeholder of an async skill as
"processing" and expects the worker to close it. A cloud command's output lives
in the child terminal code embed; the parent finishes (or errors) when the run
ends. Spec: code-run.cloud.commands.
"""
from __future__ import annotations

import time
from typing import Any

from toon_format import encode as toon_encode

from backend.apps.code.cloud_command import command_display


def command_card_fields(command_run: dict[str, Any], child_id: str | None) -> dict[str, Any]:
    """The fields shown while the command runs and after: argv, folder, command line, terminal card."""
    argv = [str(part) for part in command_run.get("argv") or []]
    cwd = command_run.get("cwd")
    return {
        "argv": argv,
        "cwd": cwd,
        "command": command_display(argv, str(cwd or ".")).strip(),
        "embed_ids": [child_id] if child_id else [],
    }


OUTPUT_TAIL_LINES = 3
OUTPUT_TAIL_CHARS = 240


def output_tail(output: Any) -> str:
    """The last few non-empty lines of the guarded output, for the card's result line."""
    if not isinstance(output, str):
        return ""
    lines = [line.rstrip() for line in output.splitlines() if line.strip()]
    return "\n".join(lines[-OUTPUT_TAIL_LINES:])[-OUTPUT_TAIL_CHARS:]


def build_command_parent_content(
    payload: dict[str, Any], final_status: dict[str, Any], *, guarded_output: Any = None,
) -> tuple[str, dict[str, Any]]:
    """Return the terminal status and the card content for the finished run.

    ``guarded_output`` is the output after the terminal-text guard (the text the
    model receives); only its last lines go on the card, the full output stays
    in the terminal child card.
    """
    command_run = payload["command_run"]
    status = "finished" if final_status.get("status") == "finished" else "error"
    child_id = payload.get("target_embed_id")
    content: dict[str, Any] = {
        "app_id": "code",
        "skill_id": "run",
        "status": status,
        **command_card_fields(command_run, child_id),
        "exit_code": final_status.get("exit_code"),
        "result_count": 1 if child_id else 0,
    }
    duration = final_status.get("duration_seconds")
    if isinstance(duration, (int, float)) and duration >= 0:
        content["duration_seconds"] = round(float(duration), 1)
    tail = output_tail(guarded_output)
    if tail:
        content["output_tail"] = tail
    if status == "error":
        content["error"] = str(final_status.get("error") or final_status.get("status") or "failed")
    return status, content


async def _publish_parent(
    payload: dict[str, Any], status: str, content: dict[str, Any], cache_service: Any,
) -> bool:
    """Write the parent card; False when the run has no placeholder to write."""
    parent_id = (payload.get("command_run") or {}).get("parent_embed_id")
    chat_id, message_id = payload.get("chat_id"), payload.get("message_id")
    user_id, user_id_hash = payload.get("user_id"), payload.get("user_id_hash")
    if not (parent_id and chat_id and message_id and user_id and user_id_hash):
        return False
    from backend.core.api.app.services.directus import DirectusService
    from backend.core.api.app.services.embed_service import EmbedService
    from backend.core.api.app.utils.encryption import EncryptionService

    encryption_service = EncryptionService(cache_service=cache_service)
    await encryption_service.initialize()
    directus_service = DirectusService(cache_service=cache_service, encryption_service=encryption_service)
    embed_service = EmbedService(
        cache_service=cache_service, directus_service=directus_service, encryption_service=encryption_service,
    )
    now = int(time.time())
    await embed_service.send_embed_data_to_client(
        embed_id=str(parent_id), embed_type="app_skill_use", content_toon=toon_encode(content),
        chat_id=str(chat_id), message_id=str(message_id), user_id=str(user_id),
        user_id_hash=str(user_id_hash), status=status, encryption_mode="client",
        created_at=now, updated_at=now, embed_ids=content["embed_ids"],
        log_prefix="[CloudCommandParent]", check_cache_status=False,
    )
    return True


async def publish_running_command_parent(payload: dict[str, Any], cache_service: Any) -> bool:
    """Show the command on the parent card while it runs (the placeholder carries no input)."""
    content = {
        "app_id": "code", "skill_id": "run", "status": "processing",
        **command_card_fields(payload["command_run"], payload.get("target_embed_id")),
    }
    return await _publish_parent(payload, "processing", content, cache_service)


async def finalize_command_parent_embed(
    payload: dict[str, Any], final_status: dict[str, Any], cache_service: Any, *, guarded_output: Any = None,
) -> bool:
    """Set the parent placeholder to finished/error; False when the run had no placeholder."""
    status, content = build_command_parent_content(payload, final_status, guarded_output=guarded_output)
    return await _publish_parent(payload, status, content, cache_service)


def test_run_parent_payload(payload: dict[str, Any]) -> dict[str, Any] | None:
    """The payload that shows an assistant test run's command on its "Run" card; None without a card.

    A test run's result is its own test result card, so this card points at no child.
    """
    test_command = (payload.get("test_run") or {}).get("test_command") or {}
    parent_id = payload.get("parent_embed_id")
    if not parent_id or not test_command.get("argv"):
        return None
    return {
        **payload, "target_embed_id": None,
        "command_run": {"argv": list(test_command["argv"]), "cwd": test_command.get("cwd") or ".",
                        "parent_embed_id": parent_id},
    }
