"""Recoverable parent/child graph for an asynchronous media-generation invocation."""

from __future__ import annotations

import re
import uuid
from typing import Any, Mapping, Sequence
from contextvars import ContextVar

try:
    from toon_format import encode as toon_encode
except ImportError:  # pragma: no cover - lightweight contract-test environments
    import json

    def toon_encode(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False)


MEDIA_CHILD_TYPES = {
    "images": "generated_image",
    "audio": "generated_audio",
    # Private assistant narration uses the same encrypted audio asset transport.
    "assistant_response_speech": "generated_audio",
    "music": "generated_music",
    "videos": "generated_video",
    "models3d": "generated_model",
}

# Match the former per-output Celery soft limits. A batch keeps every advertised
# request slot but cannot let one provider call consume the entire invocation.
PER_CHILD_TIMEOUT_SECONDS = {
    ("images", "generate"): 600,
    ("images", "generate_draft"): 600,
    ("images", "vectorize"): 180,
    ("audio", "generate"): 600,
    ("audio", "speak"): 600,
    ("music", "generate"): 900,
    ("videos", "generate"): 1800,
    ("models3d", "generate"): 900,
}

active_media_batch_child: ContextVar[bool] = ContextVar("active_media_batch_child", default=False)

# Completion needs attribution and a child reference, not the asset's encrypted
# storage metadata or short-lived download tokens. The full result stays on the
# owner-bound embed and generated-asset record.
COMPLETION_RESULT_FIELDS = frozenset({
    "id", "type", "prompt", "text_preview", "model", "provider_model",
    "provider", "mode", "generation_type", "duration_seconds", "aspect_ratio",
    "resolution", "output_filetype", "billing_status", "generated_at", "input_embed_ids",
})

_INLINE_CARD_SKILLS = frozenset({("nutrition", "search_recipes"), ("design", "search_icons")})
_GENERATED_OUTPUT_SKILLS = frozenset({
    ("images", "generate"), ("images", "generate_draft"), ("images", "vectorize"),
    ("audio", "generate"), ("audio", "speak"), ("music", "generate"),
    ("videos", "generate"), ("videos", "create"), ("models3d", "generate"),
    ("code", "image_to_html"),
})
_OUTPUT_REF_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._~:-]{0,127}\Z")
_MARKDOWN_EMBED_LINK = re.compile(
    r"(?P<image>!?)\[(?P<label>[^\]\n]*)\]\(\s*<?(?P<prefix>embed:)?(?P<ref>[^\s<>)]+)>?"
    r"(?:\s+[\"'][^\"']*[\"'])?\s*\)"
)
_INLINE_CODE = re.compile(r"(?<!`)`[^`\n]+`(?!`)")
_FENCE_LINE = re.compile(r"^\s*(```|~~~)")
_BARE_EMBED_TARGET = re.compile(r"(?<![A-Za-z0-9_/:])embed:([A-Za-z0-9][A-Za-z0-9._~:-]{0,127})(?![A-Za-z0-9._~:-])")
_REF_RANDOM_SUFFIX = re.compile(r"^(.+)-[A-Za-z0-9]{3,4}$")


def _canonical_output_id(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        return str(uuid.UUID(value))
    except (ValueError, AttributeError):
        return None


def collect_authored_skill_output_bindings(
    *, app_id: str, skill_id: str, results: Sequence[Mapping[str, Any]],
    authored_embeds: Sequence[Mapping[str, Any]],
) -> list[dict[str, str]]:
    """Bind result refs only when the successful writer returned matching child IDs.

    The skill's fetched results alone are not authority to render an inline card.
    A failed or incomplete writer cannot authorize speculative refs.
    """
    if (app_id, skill_id) not in _INLINE_CARD_SKILLS:
        return []
    child_ids: list[str] = []
    for embed in authored_embeds:
        if not isinstance(embed, Mapping) or embed.get("status") in {"error", "failed", "cancelled"}:
            continue
        ids = embed.get("child_embed_ids")
        if not isinstance(ids, list):
            continue
        for child_id in ids:
            canonical = _canonical_output_id(child_id)
            if canonical is None:
                return []
            child_ids.append(canonical)
    if not child_ids or len(child_ids) != len(results) or len(set(child_ids)) != len(child_ids):
        return []
    bindings: list[dict[str, str]] = []
    for result, child_id in zip(results, child_ids):
        if not isinstance(result, Mapping):
            return []
        ref = result.get("embed_ref")
        if not isinstance(ref, str) or not _OUTPUT_REF_PATTERN.fullmatch(ref):
            return []
        title = next((str(result[key]).strip() for key in ("title", "name", "label")
                      if isinstance(result.get(key), str) and result[key].strip()), "")
        bindings.append({"app_id": app_id, "skill_id": skill_id, "embed_ref": ref,
                         "embed_id": child_id, "status": "finished", "title": title})
    return bindings


def finalize_trusted_inline_refs(
    answer: str, authored_outputs: Sequence[Mapping[str, Any]], *,
    required_refs: Sequence[str] = (),
    include_named_search_results: bool = True,
) -> str:
    """Render only authenticated output refs as cards, correcting unique slug typos.

    Only successful, server-authored child UUID/ref pairs may be rewritten.
    An unknown random suffix can be corrected only when its stable slug or name
    identifies exactly one authored child. Search title matches are capped at
    three, so the fetched candidate list is never forced inline wholesale.
    """
    if not authored_outputs:
        return answer
    refs: dict[str, Mapping[str, Any]] = {}
    aliases: dict[str, str] = {}
    canonical_by_identity: dict[str, str] = {}
    stable_bases: dict[str, set[str]] = {}
    for row in authored_outputs:
        if not isinstance(row, Mapping) or row.get("status") != "finished":
            continue
        ref, identity = row.get("embed_ref"), _canonical_output_id(row.get("embed_id"))
        if not isinstance(ref, str) or not _OUTPUT_REF_PATTERN.fullmatch(ref) or identity is None:
            continue
        if (row.get("app_id"), row.get("skill_id")) not in (_INLINE_CARD_SKILLS | _GENERATED_OUTPUT_SKILLS):
            continue
        existing = refs.get(ref)
        if existing and _canonical_output_id(existing.get("embed_id")) != identity:
            continue
        if identity in canonical_by_identity:
            aliases[ref] = canonical_by_identity[identity]
            continue
        refs[ref] = row
        canonical_by_identity[identity] = ref
        aliases[ref] = ref
        aliases[identity] = ref
        suffix = _REF_RANDOM_SUFFIX.fullmatch(ref)
        if suffix and (row.get("app_id"), row.get("skill_id")) in _INLINE_CARD_SKILLS:
            stable_bases.setdefault(suffix.group(1).casefold(), set()).add(ref)
    if not refs:
        return answer

    def resolve(target: str) -> tuple[str | None, bool]:
        """Return the authenticated ref and whether a plausible name is ambiguous."""
        canonical = _canonical_output_id(target) or target
        if canonical in aliases:
            return aliases[canonical], False
        suffix = _REF_RANDOM_SUFFIX.fullmatch(target)
        if not suffix:
            return None, False
        candidates = stable_bases.get(suffix.group(1).casefold(), set())
        if len(candidates) == 1:
            return next(iter(candidates)), False
        return None, len(candidates) > 1

    present: set[str] = set()
    saw_ambiguous_ref = False
    normalized_lines: list[str] = []
    fence: str | None = None
    for line in answer.splitlines(keepends=True):
        fence_match = _FENCE_LINE.match(line)
        if fence_match:
            marker = fence_match.group(1)
            fence = None if fence == marker else marker if fence is None else fence
            normalized_lines.append(line)
            continue
        if fence:
            normalized_lines.append(line)
            continue
        code_spans = [match.span() for match in _INLINE_CODE.finditer(line)]

        def normalize_link(match: re.Match[str]) -> str:
            nonlocal saw_ambiguous_ref
            if any(start <= match.start() < end for start, end in code_spans):
                return match.group(0)
            ref, ambiguous = resolve(match.group("ref"))
            if ref is None:
                saw_ambiguous_ref |= ambiguous
                return match.group("label") if ambiguous else match.group(0)
            if ref in present:
                return match.group("label") if not match.group("image") and match.group("label") != "!" else ""
            present.add(ref)
            generated = (refs[ref].get("app_id"), refs[ref].get("skill_id")) in _GENERATED_OUTPUT_SKILLS
            label = "!" if generated or match.group("image") else match.group("label")
            return f"[{label}](embed:{ref})"

        normalized_lines.append(_MARKDOWN_EMBED_LINK.sub(normalize_link, line))

    lines: list[str] = []
    fence = None
    for line in normalized_lines:
        fence_match = _FENCE_LINE.match(line)
        if fence_match:
            marker = fence_match.group(1)
            fence = None if fence == marker else marker if fence is None else fence
            lines.append(line)
            continue
        if fence:
            lines.append(line)
            continue
        protected = [match.span() for pattern in (_MARKDOWN_EMBED_LINK, _INLINE_CODE)
                     for match in pattern.finditer(line)]

        def normalize_bare(match: re.Match[str]) -> str:
            nonlocal saw_ambiguous_ref
            if any(start <= match.start() < end for start, end in protected):
                return match.group(0)
            ref, ambiguous = resolve(match.group(1))
            if ref is None:
                saw_ambiguous_ref |= ambiguous
                return "result unavailable" if ambiguous else match.group(0)
            if ref in present:
                title = refs[ref].get("title")
                return title if isinstance(title, str) and title else "this result"
            present.add(ref)
            return f"[!](embed:{ref})"

        updated = _BARE_EMBED_TARGET.sub(normalize_bare, line)
        lines.append(updated)
    answer = "".join(lines)

    if include_named_search_results and not saw_ambiguous_ref:
        chosen: list[str] = []
        prose: list[str] = []
        fence = None
        for line in answer.splitlines():
            fence_match = _FENCE_LINE.match(line)
            if fence_match:
                marker = fence_match.group(1)
                fence = None if fence == marker else marker if fence is None else fence
                continue
            if fence:
                continue
            line = _INLINE_CODE.sub("", line)
            line = _MARKDOWN_EMBED_LINK.sub(lambda match: match.group("label"), line)
            line = _BARE_EMBED_TARGET.sub("", line)
            prose.append(line)
        folded = re.sub(r"\s+", " ", " ".join(prose).casefold())
        for ref, row in refs.items():
            title = row.get("title")
            if ((row.get("app_id"), row.get("skill_id")) in _INLINE_CARD_SKILLS
                    and ref not in present and isinstance(title, str) and len(title.strip()) >= 4
                    and re.search(r"(?<!\w)" + re.escape(re.sub(r"\s+", " ", title.strip().casefold()))
                                  + r"(?!\w)", folded)):
                chosen.append(ref)
                present.add(ref)
            if len(chosen) == 3:
                break
        if chosen:
            cards = "\n".join(f"[!](embed:{ref})" for ref in chosen)
            answer = f"{answer.rstrip()}\n\n{cards}"

    required: list[str] = []
    for target in required_refs:
        if isinstance(target, str):
            ref, _ = resolve(target)
            if ref is not None and ref not in present:
                required.append(ref)
                present.add(ref)
    if required:
        cards = "\n".join(f"[!](embed:{ref})" for ref in required)
        answer = f"{answer.rstrip()}\n\n{cards}" if answer.strip() else cards
    return answer


def media_completion_result(result: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in result.items() if key in COMPLETION_RESULT_FIELDS}


def generated_media_embed_ref(app_id: str, child_embed_id: str) -> str:
    """A stable visible reference for an already registered output child."""
    return f"generated-{app_id}-{child_embed_id.replace('-', '')[:12]}"


def generated_media_parent_ref(app_id: str, parent_embed_id: str) -> str:
    return f"generated-media-{app_id}-{parent_embed_id.replace('-', '')[:12]}"


async def run_generated_media_batch(
    task: Any,
    *,
    app_id: str,
    skill_id: str,
    arguments: dict[str, Any],
    generate_one: Any,
) -> dict[str, Any]:
    """Run one registered producer with a distinct asset ID for each request."""
    import hashlib
    import asyncio
    from datetime import datetime, timezone

    from backend.core.api.app.services.embed_service import EmbedService
    from backend.shared.python_utils.chat_recovery_context import RequiredRecoveryOutputError

    parent_id = str(arguments["embed_id"])
    requests = arguments.get("requests")
    if not isinstance(requests, list) or not requests:
        raise ValueError("Generated media batch has no requests")
    if len(requests) > 32:
        raise ValueError("Generated media batch exceeds registered child limit")
    child_timeout = PER_CHILD_TIMEOUT_SECONDS.get((app_id, skill_id))
    if child_timeout is None:
        raise ValueError("Generated media batch has no bounded child timeout")
    children: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for index, request in enumerate(requests):
        if not isinstance(request, dict):
            failures.append({"request_index": index, "error": "Invalid request"})
            continue
        child_id = EmbedService._registered_child_embed_id(parent_id, index)
        child_args = {
            **arguments, **request,
            "embed_id": child_id,
            "producer_embed_id": parent_id,
            "media_child_index": index,
            "media_batch": True,
        }
        child_args.pop("requests", None)
        try:
            token = active_media_batch_child.set(True)
            try:
                result = await asyncio.wait_for(
                    generate_one(task, app_id, skill_id, child_args), timeout=child_timeout,
                )
            finally:
                active_media_batch_child.reset(token)
            if not isinstance(result, dict) or result.get("status") != "finished":
                failures.append({"request_index": index, "error": "Generation did not finish"})
                continue
            children.append({
                "request_index": index,
                "child_embed_id": child_id,
                "embed_ref": generated_media_embed_ref(app_id, child_id),
                "result": result,
            })
        except RequiredRecoveryOutputError:
            raise
        except TimeoutError:
            failures.append({"request_index": index, "error": "Generation timed out"})
        except Exception:
            failures.append({"request_index": index, "error": "Generation failed"})
    if arguments.get("chat_id") and arguments.get("message_id"):
        await task.initialize_core_services()
        try:
            service = EmbedService(task._cache_service, task._directus_service, task._encryption_service)
            user_id = str(arguments["user_id"])
            await finalize_generated_media_parent(
                service, parent_embed_id=parent_id, app_id=app_id, skill_id=skill_id,
                children=children, failures=failures,
                input_embed_ids=list(dict.fromkeys(
                    source_id for request in requests if isinstance(request, dict)
                    for source_id in request.get("input_embed_ids", []) if isinstance(source_id, str)
                )),
                chat_id=str(arguments["chat_id"]),
                message_id=str(arguments["message_id"]),
                user_id=user_id, user_id_hash=hashlib.sha256(user_id.encode()).hexdigest(),
                created_at=int(datetime.now(timezone.utc).timestamp()),
                log_prefix=f"[media batch:{task.request.id}]",
            )
            # The registered task ID is the one terminal slot in the same-turn
            # barrier. Dispatch only after the parent manifest has sealed every
            # successful child, including when other request slots failed.
            from backend.apps.ai.tasks.async_skill_continuation import dispatch_async_skill_continuation
            completed_results = [
                {
                    **media_completion_result(row["result"]),
                    "parent_embed_id": parent_id,
                    "parent_embed_ref": generated_media_parent_ref(app_id, parent_id),
                    "request_index": row["request_index"],
                    "child_embed_id": row["child_embed_id"],
                    "embed_ref": row["embed_ref"],
                    "status": "finished",
                }
                for row in children
            ] + [
                {
                    "parent_embed_id": parent_id,
                    "parent_embed_ref": generated_media_parent_ref(app_id, parent_id),
                    "request_index": row["request_index"], "status": "error", "error": row["error"],
                }
                for row in failures
            ]
            completed_results.sort(key=lambda row: row["request_index"])
            await dispatch_async_skill_continuation(
                cache_service=task._cache_service,
                async_task_id=task.request.id,
                completed_results=completed_results,
                result_status="finished" if not failures else "failed",
                request_metadata={
                    "app_id": app_id, "skill_id": skill_id,
                    "parent_embed_id": parent_id,
                    "parent_embed_ref": generated_media_parent_ref(app_id, parent_id),
                    "user_id": str(arguments["user_id"]),
                    "chat_id": str(arguments["chat_id"]),
                    "message_id": str(arguments["message_id"]),
                    **({"same_turn_batch_id": str(arguments["same_turn_batch_id"])}
                       if arguments.get("same_turn_batch_id") else {}),
                },
            )
        finally:
            await task.cleanup_services()
    return {
        "embed_id": parent_id,
        "status": "finished" if not failures else "partial" if children else "error",
        "results": [row["result"] for row in children],
        "completed_results": children,
        "child_embed_ids": [row["child_embed_id"] for row in children],
        "failed_results": failures,
        "input_embed_ids": list(dict.fromkeys(
            source_id for row in children for source_id in row.get("result", {}).get("input_embed_ids", [])
            if isinstance(source_id, str)
        )),
    }


async def send_generated_media_child(
    embed_service: Any,
    *,
    parent_embed_id: str,
    child_embed_id: str,
    child_index: int,
    content: dict[str, Any],
    chat_id: str,
    message_id: str,
    user_id: str,
    user_id_hash: str,
    created_at: int,
    log_prefix: str,
) -> str:
    """Publish one actual asset child under its stable registered output ID."""
    app_id = str(content["app_id"])
    child_type = MEDIA_CHILD_TYPES[app_id]
    from backend.shared.python_utils.chat_recovery_context import active_verified_output_producer
    producer = active_verified_output_producer.get()
    is_registered = producer is not None and producer.classification == "registered_ai"
    has_distinct_parent = parent_embed_id != child_embed_id
    if is_registered and has_distinct_parent:
        expected_id = embed_service._registered_child_embed_id(parent_embed_id, child_index)
        if child_embed_id != expected_id:
            raise ValueError("Generated media child does not match producer registration")
    child_ref = generated_media_embed_ref(app_id, child_embed_id)
    child_content = {**content, "type": child_type, "embed_ref": child_ref}
    await embed_service.send_embed_data_to_client(
        embed_id=child_embed_id,
        embed_type=child_type,
        content_toon=toon_encode(child_content),
        chat_id=chat_id,
        message_id=message_id,
        user_id=user_id,
        user_id_hash=user_id_hash,
        status="finished",
        encryption_mode="client",
        created_at=created_at,
        updated_at=created_at,
        parent_embed_id=parent_embed_id if has_distinct_parent else None,
        log_prefix=log_prefix,
        check_cache_status=False,
        app_id=app_id,
        skill_id=child_type,
        producer_child_index=child_index if is_registered and has_distinct_parent else None,
        producer_final_children=[] if is_registered and not has_distinct_parent else None,
    )
    return child_ref


async def finalize_generated_media_parent(
    embed_service: Any,
    *,
    parent_embed_id: str,
    app_id: str,
    skill_id: str,
    children: list[dict[str, Any]],
    failures: list[dict[str, Any]],
    chat_id: str,
    message_id: str,
    user_id: str,
    user_id_hash: str,
    created_at: int,
    log_prefix: str,
    input_embed_ids: list[str] | None = None,
) -> None:
    """Close the one producer after all request slots have reached a terminal state."""
    ordered = sorted(children, key=lambda row: int(row["request_index"]))
    child_ids = [str(row["child_embed_id"]) for row in ordered]
    content = {
        "app_id": app_id,
        "skill_id": skill_id,
        "embed_ref": generated_media_parent_ref(app_id, parent_embed_id),
        "status": "finished" if child_ids else "error",
        "result_count": len(child_ids),
        "embed_ids": child_ids,
        "output_embed_refs": [str(row["embed_ref"]) for row in ordered],
        "failed_results": failures,
        "input_embed_ids": list(dict.fromkeys([*(input_embed_ids or []), *(
            source_id for row in ordered for source_id in row.get("result", {}).get("input_embed_ids", [])
            if isinstance(source_id, str)
        )])),
    }
    if failures:
        content["partial_failure"] = bool(child_ids)
        content["error"] = f"{len(failures)} output(s) could not be generated"
    await embed_service.send_embed_data_to_client(
        embed_id=parent_embed_id,
        embed_type="app_skill_use",
        content_toon=toon_encode(content),
        chat_id=chat_id,
        message_id=message_id,
        user_id=user_id,
        user_id_hash=user_id_hash,
        status="finished",  # terminal manifest even when all slots failed
        encryption_mode="client",
        created_at=created_at,
        updated_at=created_at,
        embed_ids=child_ids,
        log_prefix=log_prefix,
        check_cache_status=False,
        producer_final_children=[
            {"subject_id": child_id, "output_kind": "embed", "output_version": 1}
            for child_id in child_ids
        ],
    )
