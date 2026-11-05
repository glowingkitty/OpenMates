"""Ordered, one-shot completion barrier for a suspended text assistant turn.

Redis holds only task identities, terminal statuses and opaque handoff references.
Provider results are sealed by the existing API-process private context handoff.
"""

from __future__ import annotations

import json
import re
import time
import uuid
import base64
import zlib
from typing import Any

PREFIX = "same_turn_skill"
TTL_SECONDS = 90 * 60

# Hard task envelopes plus four minutes for queueing, callback and resume.
_MEDIA_CHILD_LIMITS = {
    ("images", "generate"): (600, 5),
    ("images", "generate_draft"): (600, 5),
    ("images", "vectorize"): (180, 1),
    ("music", "generate"): (900, 5),
    ("audio", "generate"): (600, 5),
    ("audio", "speak"): (600, 3),
    ("videos", "generate"): (1800, 1),
    ("models3d", "generate"): (900, 1),
}
_OTHER_HARD_LIMITS = {
    ("videos", "create"): 1260,
    ("code", "image_to_html"): 960,
    # E2B phases total at most 600s: two installs (2*120), Python diagnostics
    # (2*15), execution (300) and artifact discovery (30). Allow 360s for
    # scanning, billing, setup/upload and encrypted persistence; the standard
    # queue/callback/resume allowance is added by deadline_seconds_for_jobs.
    ("code", "run"): 960,
    ("social_media", "search"): 360,
    ("social_media", "get-posts"): 360,
}


def deadline_seconds_for_jobs(jobs: list[dict[str, Any]]) -> int:
    seconds = 3 * 60
    for job in jobs:
        app, skill = job.get("app_id"), job.get("skill_id")
        child_limit = _MEDIA_CHILD_LIMITS.get((app, skill))
        hard_limit = _OTHER_HARD_LIMITS.get((app, skill))
        if child_limit:
            child_seconds, max_count = child_limit
            count = job.get("request_count", 1)
            if not isinstance(count, int) or not 1 <= count <= max_count:
                raise RuntimeError("Same-turn request count is outside the skill envelope")
            seconds = max(seconds, count * child_seconds + 9 * 60)
            continue
        if hard_limit is None and app in {"images", "music", "audio", "videos", "models3d", "code", "social_media"}:
            raise RuntimeError(f"Same-turn deadline has no envelope for {app}.{skill}")
        if hard_limit is not None:
            seconds = max(seconds, hard_limit + 4 * 60)
    return seconds


def _key(batch_id: str, kind: str, task_id: str = "") -> str:
    return f"{PREFIX}:{batch_id}:{kind}" + (f":{task_id}" if task_id else "")


def _latest_turn_key(user_id: str, chat_id: str) -> str:
    return f"async_skill_latest_user_turn:{user_id}:{chat_id}"


async def _set_once(cache: Any, key: str, value: str) -> bool:
    client = await cache.client
    if client is None:
        raise RuntimeError("Same-turn completion authority is unavailable")
    return bool(await client.set(key, value, nx=True, ex=TTL_SECONDS))


async def register_barrier(
    cache: Any, *, batch_id: str, user_id: str, chat_id: str, turn_id: str,
    task_ids: list[str], checkpoint_ref: str, deadline: float, logical_task_id: str,
    source_delivery_task_id: str, recovery_inference_task_id: str | None = None,
    handoff_ttl_seconds: int = 20 * 60,
) -> None:
    if (not task_ids or len(task_ids) != len(set(task_ids)) or deadline <= time.time()
            or not 1200 <= handoff_ttl_seconds <= TTL_SECONDS
            or deadline >= time.time() + handoff_ttl_seconds):
        raise ValueError("Invalid same-turn completion barrier")
    metadata = {
        "version": 1, "user_id": user_id, "chat_id": chat_id,
        "turn_id": turn_id, "task_ids": task_ids, "checkpoint_ref": checkpoint_ref,
        "deadline": deadline, "logical_task_id": logical_task_id,
        "source_delivery_task_id": source_delivery_task_id,
        "recovery_inference_task_id": recovery_inference_task_id,
        "handoff_ttl_seconds": handoff_ttl_seconds,
    }
    if not await _set_once(cache, _key(batch_id, "batch"), json.dumps(metadata)):
        previous = await cache.get(_key(batch_id, "batch"))
        if previous != metadata:
            raise RuntimeError("Same-turn barrier identity changed")
    await cache.set(f"{PREFIX}:source:{source_delivery_task_id}", batch_id, ttl=TTL_SECONDS)


def pack_private_checkpoint(request_payload: dict[str, Any], checkpoint: dict[str, Any]) -> dict[str, str]:
    """One bounded JSON copy of the private turn in the API-only sealed handoff."""
    raw = json.dumps({"request": request_payload, "checkpoint": checkpoint}, ensure_ascii=False,
                     separators=(",", ":")).encode("utf-8")
    if len(raw) > 4_000_000:
        raise RuntimeError("Same-turn private checkpoint exceeds the bounded handoff")
    compressed = zlib.compress(raw, level=6)
    if len(compressed) > 140_000:
        raise RuntimeError("Same-turn private checkpoint cannot fit in transient handoff")
    return {"codec": "json-zlib-base64-v1", "data": base64.b64encode(compressed).decode("ascii")}


def preflight_private_checkpoint_capacity(
    request_payload: dict[str, Any], transcript: list[dict[str, Any]],
    native_state: Any, native_main_cursor: Any, native_main_snapshot: Any,
) -> None:
    """Reject oversized input before dispatch, reserving final-checkpoint headroom."""
    preview = pack_private_checkpoint(request_payload, {
        "current_message_history": transcript,
        "native_state": native_state,
        "native_main_cursor": native_main_cursor,
        "native_main_snapshot": native_main_snapshot,
    })
    if len(preview["data"]) > 160_000:
        raise RuntimeError("Same-turn checkpoint headroom is exhausted")


def unpack_private_checkpoint(value: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(value, dict) or value.get("codec") != "json-zlib-base64-v1":
        raise RuntimeError("Same-turn checkpoint encoding is invalid")
    encoded = value.get("data")
    if not isinstance(encoded, str) or len(encoded) > 190_000:
        raise RuntimeError("Same-turn checkpoint encoding is too large")
    try:
        compressed = base64.b64decode(encoded, validate=True)
        inflater = zlib.decompressobj()
        raw = inflater.decompress(compressed, 4_000_001)
        if len(raw) > 4_000_000 or inflater.unconsumed_tail or not inflater.eof:
            raise ValueError("checkpoint too large or incomplete")
        data = json.loads(raw)
    except (ValueError, zlib.error) as exc:
        raise RuntimeError("Same-turn checkpoint cannot be restored") from exc
    if not isinstance(data, dict) or not isinstance(data.get("request"), dict) or not isinstance(data.get("checkpoint"), dict):
        raise RuntimeError("Same-turn checkpoint shape is invalid")
    return data["request"], data["checkpoint"]


def verify_resume_recovery_identity(original: dict[str, Any], resume: Any) -> None:
    """Bind queued recovery metadata to the admitted request in the sealed checkpoint."""
    from backend.shared.python_utils.chat_recovery_context import RequiredRecoveryOutputError

    original_target = original.get("chat_id")
    original_root = original.get("root_chat_id") or original_target
    resume_target = getattr(resume, "chat_id", None)
    resume_root = getattr(resume, "root_chat_id", None) or resume_target
    if not original_target or original_target != resume_target or original_root != resume_root:
        raise RequiredRecoveryOutputError("Same-turn recovery chat identity changed")
    original_task_id = original.get("recovery_task_id") or original.get("recovery_inference_task_id")
    if original_task_id != getattr(resume, "recovery_inference_task_id", None):
        raise RequiredRecoveryOutputError("Same-turn recovery inference identity changed")
    if original_task_id:
        fields = ("recovery_preflight_id", "recovery_turn_id",
                  "recovery_public_key", "chat_key_version")
        if (not all(original.get(field) for field in fields)
                or any(original.get(field) != getattr(resume, field, None) for field in fields)):
            raise RequiredRecoveryOutputError("Same-turn sealed recovery identity changed")
    elif original.get("legacy_cutover_task_id") or original.get("root_legacy_cutover_task_id"):
        fields = ("legacy_cutover_task_id", "root_legacy_cutover_task_id",
                  "root_turn_id", "root_user_message_id", "is_sub_chat", "team_id_hash")
        if any(original.get(field) != getattr(resume, field, None) for field in fields):
            raise RequiredRecoveryOutputError("Same-turn sealed legacy identity changed")


_MARKDOWN_EMBED_TARGET = re.compile(
    r"\]\(\s*<?embed:([^\s<>)]+)>?(?:\s+[\"'][^\"']*[\"'])?\s*\)"
)


def _valid_ref(value: Any) -> bool:
    return (isinstance(value, str) and 1 <= len(value) <= 128
            and not any(char.isspace() or char in ")<>" for char in value))


def _normalized_target(value: str) -> str:
    try:
        return str(uuid.UUID(value))
    except (ValueError, AttributeError):
        return value


def _generated_ref_bindings(
    value: Any, *, app_id: str | None = None, metadata: dict[str, Any] | None = None,
) -> tuple[list[str], dict[str, list[str]]]:
    """Collect only authored successful output refs and exact identity aliases."""
    refs: list[str] = []
    aliases: dict[str, list[str]] = {}

    def add(ref: Any, embed_id: Any) -> None:
        if not _valid_ref(ref):
            return
        if ref not in refs:
            refs.append(ref)
        if isinstance(embed_id, str):
            try:
                identity = str(uuid.UUID(embed_id))
            except (ValueError, AttributeError):
                return
            if identity not in aliases.setdefault(ref, []):
                aliases[ref].append(identity)

    successful_child = False

    def add_parent(ref: Any, embed_id: Any) -> None:
        if app_id not in {"images", "audio", "music", "videos", "models3d"}:
            return
        if not isinstance(embed_id, str):
            return
        try:
            canonical_id = str(uuid.UUID(embed_id))
        except (ValueError, AttributeError):
            return
        expected = f"generated-media-{app_id}-{canonical_id.replace('-', '')[:12]}"
        if ref == expected:
            add(ref, canonical_id)

    def walk(node: Any) -> None:
        nonlocal successful_child
        if isinstance(node, list):
            for item in node:
                walk(item)
        elif isinstance(node, dict):
            if node.get("status") not in {"error", "failed", "cancelled", "timed_out"}:
                add(node.get("embed_ref"), node.get("child_embed_id") or node.get("embed_id"))
                # The parent is a real registered manifest, authored before
                # callback. It is useful only when at least one child succeeded.
                if node.get("status") == "finished" and _valid_ref(node.get("embed_ref")):
                    successful_child = True
                    add_parent(node.get("parent_embed_ref"), node.get("parent_embed_id"))
            for key, child in node.items():
                if key not in {"embed_ref", "parent_embed_ref"}:
                    walk(child)

    walk(value)
    if successful_child and isinstance(metadata, dict):
        add_parent(metadata.get("parent_embed_ref"), metadata.get("parent_embed_id"))
    return refs, aliases


def ensure_generated_refs(
    answer: str, refs: list[str], aliases: dict[str, list[str]] | None = None,
) -> str:
    """Append only missing refs, comparing complete Markdown embed targets."""
    present = {_normalized_target(target) for target in _MARKDOWN_EMBED_TARGET.findall(answer)}
    missing: list[str] = []
    for ref in refs:
        if not _valid_ref(ref):
            continue
        equivalents = {_normalized_target(ref)}
        equivalents.update(_normalized_target(alias) for alias in (aliases or {}).get(ref, [])
                           if _valid_ref(alias))
        if present.isdisjoint(equivalents):
            missing.append(ref)
        present.update(equivalents)
    if not missing:
        return answer
    links = "\n".join(f"- [Generated result](embed:{ref})" for ref in missing)
    return f"{answer.rstrip()}\n\n{links}" if answer.strip() else links


def selected_resume_route(
    checkpoint: dict[str, Any], models_to_try: list[str], selected_mate_id: str | None,
) -> tuple[int, str]:
    """Use only the original provider/Mate route for a suspended tool loop."""
    try:
        index = int(checkpoint["current_model_index"])
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError("Same-turn selected model is unavailable") from exc
    if (models_to_try != checkpoint.get("models_to_try")
            or selected_mate_id != checkpoint.get("selected_mate_id")
            or index < 0 or index >= len(models_to_try)
            or models_to_try[index] != checkpoint.get("current_model_id")):
        raise RuntimeError("Same-turn selected model or mate changed before resume")
    return index, models_to_try[index]


async def arm_barrier(cache: Any, batch_id: str) -> None:
    """Publish readiness only after the durable recovery pause is established."""
    if not isinstance(await cache.get(_key(batch_id, "batch")), dict):
        raise RuntimeError("Same-turn barrier is unavailable")
    await _set_once(cache, _key(batch_id, "armed"), "armed")


async def barrier_is_armed(cache: Any, batch_id: str) -> bool:
    """Accept older numeric markers after CacheService JSON decoding."""
    marker = await cache.get(_key(batch_id, "armed"))
    return marker in ("armed", "1") or (type(marker) is int and marker == 1)


async def record_terminal(
    cache: Any, *, batch_id: str, task_id: str,
    payload_ref: str, status: str,
) -> bool:
    """Record a terminal job once; retries never replace successful output."""
    if status not in {"finished", "failed", "cancelled", "timed_out"}:
        raise ValueError("Completion must be terminal")
    return await _set_once(cache, _key(batch_id, "slot", task_id), json.dumps({
        "task_id": task_id, "status": status, "payload_ref": payload_ref,
    }))


async def claim_ready(cache: Any, *, batch_id: str, expire_missing: bool = False) -> dict[str, Any] | None:
    """Claim exactly one resume delivery after all ordered slots are terminal."""
    metadata = await cache.get(_key(batch_id, "batch"))
    if not isinstance(metadata, dict) or metadata.get("version") != 1:
        return None
    if not await barrier_is_armed(cache, batch_id):
        return None
    if await cache.get(_latest_turn_key(metadata["user_id"], metadata["chat_id"])) != metadata["turn_id"]:
        await _set_once(cache, _key(batch_id, "stale"), "1")
        return None
    expire_missing = bool(expire_missing and time.time() >= metadata["deadline"])
    slots = []
    for task_id in metadata["task_ids"]:
        slot = await cache.get(_key(batch_id, "slot", task_id))
        if not isinstance(slot, dict):
            if not expire_missing:
                return None
            await record_terminal(cache, batch_id=batch_id, task_id=task_id,
                                  payload_ref="", status="timed_out")
            slot = await cache.get(_key(batch_id, "slot", task_id))
        if not isinstance(slot, dict) or slot.get("task_id") != task_id:
            raise RuntimeError("Same-turn completion slot is unavailable")
        slots.append(slot)
    logical_task_id = metadata["logical_task_id"]
    if isinstance(logical_task_id, str) and re.fullmatch(r"[0-9a-f]{64}", logical_task_id):
        task_namespace = uuid.uuid5(uuid.NAMESPACE_URL, f"openmates:logical-task:{logical_task_id}")
    else:
        # Preserve already-issued resume identities for UUID-based tasks.
        task_namespace = uuid.UUID(logical_task_id)
    delivery_id = str(uuid.uuid5(task_namespace, f"resume:{batch_id}"))
    await _set_once(cache, _key(batch_id, "resume_claim"), delivery_id)
    if await cache.get(_key(batch_id, "resume_claim")) != delivery_id:
        return None
    return {**metadata, "batch_id": batch_id, "slots": slots,
            "resume_task_id": delivery_id}


async def restore_ordered_tool_results(request: Any, checkpoint: dict[str, Any]) -> list[dict[str, Any]]:
    """Replace only the saved pending tool messages with their terminal outputs."""
    from backend.shared.python_utils.recent_work_summary_client import restore_private_context_payload
    from backend.core.api.app.utils.text_sanitization import sanitize_text_payload_for_ascii_smuggling

    slots = request.same_turn_slots
    jobs = checkpoint.get("jobs")
    if not isinstance(jobs, list) or not isinstance(slots, list) or len(jobs) != len(slots):
        raise RuntimeError("Same-turn completion slots do not match the provider checkpoint")
    by_call: dict[str, list[dict[str, Any]]] = {}
    generated_refs = list(checkpoint.get("generated_embed_refs") or [])
    generated_aliases = dict(checkpoint.get("generated_embed_aliases") or {})
    authored_inline_outputs = list(checkpoint.get("authored_inline_outputs") or [])
    for job, slot in zip(jobs, slots):
        if not isinstance(job, dict) or not isinstance(slot, dict) or job.get("task_id") != slot.get("task_id"):
            raise RuntimeError("Same-turn completion order changed")
        status = slot.get("status")
        payload: dict[str, Any] = {"status": status, "results": [],
                                   "message": "The requested job did not finish."}
        if slot.get("payload_ref"):
            restored = await restore_private_context_payload({
                "user_id": request.user_id, "chat_id": request.chat_id,
                "message_id": request.message_id,
                "agentic_context_turn_id": request.message_id,
                "agentic_context_request_id": job["task_id"],
                "agentic_context_ref": slot["payload_ref"],
            })
            completion = restored.get("async_tool_completion")
            if isinstance(completion, dict):
                payload = completion
            elif status == "finished":
                payload = {"status": "content_unavailable", "results": [],
                           "message": "The completed result expired before it could be restored."}
        payload, _ = sanitize_text_payload_for_ascii_smuggling(payload)
        if job.get("app_id") in {"images", "audio", "music", "videos", "models3d"} or (
            job.get("app_id") == "code" and job.get("skill_id") == "image_to_html"
        ):
            refs, aliases = _generated_ref_bindings(
                payload.get("results") or [], app_id=job.get("app_id"),
                metadata=payload.get("request_metadata"),
            )
            for ref in refs:
                if ref not in generated_refs:
                    generated_refs.append(ref)
                known = generated_aliases.setdefault(ref, [])
                for alias in aliases.get(ref, []):
                    if alias not in known:
                        known.append(alias)
                if aliases.get(ref):
                    result = next((row for row in payload.get("results", [])
                                   if isinstance(row, dict) and row.get("status") == "finished"
                                   and row.get("embed_ref") == ref
                                   and (row.get("child_embed_id") or row.get("embed_id")) == aliases[ref][0]), {})
                    authored_inline_outputs.append({
                        "app_id": job["app_id"], "skill_id": job["skill_id"],
                        "embed_ref": ref, "embed_id": aliases[ref][0], "status": "finished",
                        **({"filename": result["filename"]} if isinstance(result.get("filename"), str) else {}),
                    })
        by_call.setdefault(str(job["tool_call_id"]), []).append(payload)
    checkpoint["generated_embed_refs"] = generated_refs
    checkpoint["generated_embed_aliases"] = generated_aliases
    checkpoint["authored_inline_outputs"] = authored_inline_outputs
    history = checkpoint.get("current_message_history")
    if not isinstance(history, list):
        raise RuntimeError("Same-turn provider transcript is unavailable")
    matched: set[str] = set()
    restored_history: list[dict[str, Any]] = []
    for message in history:
        if not isinstance(message, dict):
            raise RuntimeError("Same-turn provider transcript is invalid")
        row = dict(message)
        call_id = str(row.get("tool_call_id") or "")
        if row.get("role") == "tool" and call_id in by_call:
            results = by_call[call_id]
            row["content"] = json.dumps(results[0] if len(results) == 1 else {
                "status": "finished" if all(result.get("status") == "finished" for result in results) else "partial",
                "results": results,
            }, ensure_ascii=False)
            matched.add(call_id)
        restored_history.append(row)
    if matched != set(by_call):
        raise RuntimeError("Same-turn provider transcript lost a tool-call identity")
    return restored_history


async def verify_resume_delivery(cache: Any, request: Any, delivery_task_id: str) -> bool:
    """Bind a resumed delivery to the sealed checkpoint and original owner/turn."""
    batch_id = request.same_turn_batch_id
    metadata = await cache.get(_key(batch_id, "batch")) if batch_id else None
    if not isinstance(metadata, dict):
        return False
    if any((metadata.get("user_id") != request.user_id,
            metadata.get("chat_id") != request.chat_id,
            metadata.get("turn_id") != request.message_id,
            metadata.get("checkpoint_ref") != request.agentic_context_ref,
            metadata.get("resume_task_id") not in (None, delivery_task_id))):
        return False
    if await cache.get(_key(batch_id, "resume_claim")) != delivery_task_id:
        return False
    if await cache.get(_latest_turn_key(request.user_id, request.chat_id)) != request.message_id:
        return False
    if [slot.get("task_id") for slot in request.same_turn_slots] != metadata.get("task_ids"):
        return False
    if not isinstance(request.same_turn_checkpoint, dict):
        return False
    return True
