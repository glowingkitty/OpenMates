"""One images.modify request: load, check, author and run, store, charge, deliver.

Runs inside the registered generated-media batch (``run_generated_media_batch``)
on the shared media worker. Expected failures (a call outside the contract, an
unreadable picture, a safety rejection, too few credits, no valid picture after
all rounds, a sandbox that cannot run) publish a failed result child with the
reason in plain words and are never charged. Infrastructure errors propagate so
the batch helper records the slot as failed; nothing is charged then either,
because the charge is the last step before delivery.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional, Sequence

import httpx

from backend.apps.images.modify_author import MODIFY_AUTHOR_MODELS, ModifyAuthorError, author_modification
from backend.apps.images.modify_program import MAX_IMAGES, ModifyInputError, prepare_inputs
from backend.apps.images.modify_request import ModifyRequestError, parse_modify_request
from backend.apps.images.tasks.modify_billing import charge_modify_credits, estimate_modify_credits, modify_credits
from backend.apps.images.tasks.modify_inputs import LoadedInput, load_modify_inputs
from backend.apps.images.tasks.modify_memory import KeptProgram, KeptProgramError, recall_program, remember_program
from backend.apps.images.tasks.modify_progress import ModifyProgressPublisher
from backend.apps.images.tasks.modify_result import (
    assistant_result,
    build_failed_content,
    build_finished_content,
    display_model,
    store_modified_image,
)
from backend.apps.images.tasks.reference_images import ReferenceImageUnavailable
from backend.core.api.app.services.s3.config import get_bucket_name
from backend.shared.providers.e2b_image_edit import ImageEditError
from backend.shared.python_utils.billing_utils import BillingError, ensure_credit_headroom
from backend.shared.python_utils.generated_media_graph import send_generated_media_child
from backend.shared.python_utils.image_safety import get_pipeline
from backend.shared.python_utils.storage_availability import initialize_task_storage, require_storage_available

logger = logging.getLogger(__name__)

ERROR_INVALID_REQUEST = "invalid_request"
ERROR_INVALID_INPUT = "invalid_input"
ERROR_SAFETY = "safety_rejected"
ERROR_CREDITS = "insufficient_credits"
ERROR_NO_PICTURE = "no_valid_picture"
ERROR_SANDBOX = "sandbox_failed"

UNREADABLE_INPUT_MESSAGE = (
    "A picture of this request could not be read, so nothing was changed or charged. "
    "Pass pictures shown in this chat (uploads within the last 24 hours, generated images, vector "
    "graphics or embroidery results)."
)
NO_PICTURE_MESSAGE = "No valid picture could be computed for this request, so nothing was charged."
CREDITS_MESSAGE = "There are not enough credits to modify this picture."
SAFETY_MESSAGE = "This picture couldn't be modified."


class ModifyFailure(Exception):
    """An expected failure: a failed result child is published and nothing is charged."""

    def __init__(self, code: str, user_message: str) -> None:
        super().__init__(f"{code}: {user_message}")
        self.code = code
        self.user_message = user_message


@dataclass(frozen=True)
class InputPlan:
    """The pictures the program runs on and, for a change of an earlier result, its kept program."""

    embed_ids: tuple[str, ...]
    refs: tuple[str, ...]
    source_program: Optional[str]
    changed_result_id: Optional[str]


def plan_inputs(embed_ids: Sequence[str], refs: Sequence[str], kept: dict[str, KeptProgram]) -> InputPlan:
    """Expand the first referenced result with a kept program into its original inputs.

    Its original inputs come first, in their original order, so the kept program's
    input positions stay valid; the other referenced pictures follow in request order.
    When the expansion would exceed the picture limit the result is used as an
    ordinary picture (``changed_result_id`` is then ``None``).
    """
    for embed_id in embed_ids:
        program = kept.get(embed_id)
        if program is None:
            continue
        rest = [(other_id, ref) for other_id, ref in zip(embed_ids, refs) if other_id != embed_id]
        if len(program.input_embed_ids) + len(rest) > MAX_IMAGES:
            logger.info("Kept program of %s not used: %d original plus %d other pictures exceed the limit",
                        embed_id[:8], len(program.input_embed_ids), len(rest))
            break
        return InputPlan(
            embed_ids=(*program.input_embed_ids, *(other_id for other_id, _ in rest)),
            refs=(*program.input_refs, *(ref for _, ref in rest)),
            source_program=program.program, changed_result_id=embed_id,
        )
    return InputPlan(embed_ids=tuple(embed_ids), refs=tuple(refs), source_program=None, changed_result_id=None)


def _embed_service(task: Any) -> Any:
    from backend.core.api.app.services.embed_service import EmbedService

    return EmbedService(task._cache_service, task._directus_service, task._encryption_service)


async def _assert_can_generate(task: Any, *, embed_id: str, chat_id: Any, message_id: Any, owner_hash: str) -> None:
    from backend.core.api.app.services.embed_service import EmbedService

    await EmbedService.assert_registered_output_can_generate(
        task._directus_service, embed_id=embed_id, chat_id=chat_id, message_id=message_id, owner_hash=owner_hash,
    )


async def _recall_kept_programs(task: Any, embed_ids: Sequence[str], vault_key_id: str) -> dict[str, KeptProgram]:
    for embed_id in embed_ids:
        try:
            kept = await recall_program(task, embed_id=embed_id, vault_key_id=vault_key_id)
        except KeptProgramError as exc:
            raise ModifyFailure(ERROR_INVALID_INPUT, UNREADABLE_INPUT_MESSAGE) from exc
        if kept is not None:
            return {embed_id: kept}
    return {}


async def _check_input_safety(task: Any, *, instructions: str, prepared: Sequence[Any], user_id: str,
                              message_id: Any, source_embed_id: str, log_prefix: str) -> None:
    decision = await get_pipeline().validate_input(
        prompt=instructions, reference_images=[(item.preview, item.preview_mime) for item in prepared],
        secrets_manager=task._secrets_manager,
    )
    if not decision.allowed and decision.rejection:
        await _reject(task, decision.rejection, instructions=instructions, user_id=user_id, message_id=message_id,
                      source_embed_id=source_embed_id, output_embed_id=None, model=None, log_prefix=log_prefix)


async def _check_output_safety(task: Any, *, instructions: str, image: bytes, mime_type: str, user_id: str,
                               message_id: Any, source_embed_id: str, output_embed_id: str, model: str,
                               log_prefix: str) -> None:
    decision = await get_pipeline().validate_output(
        prompt=instructions, image_bytes=image, mime_type=mime_type, secrets_manager=task._secrets_manager,
    )
    if not decision.allowed and decision.rejection:
        await _reject(task, decision.rejection, instructions=instructions, user_id=user_id, message_id=message_id,
                      source_embed_id=source_embed_id, output_embed_id=output_embed_id, model=model,
                      log_prefix=log_prefix)


async def _reject(task: Any, rejection: Any, *, instructions: str, user_id: str, message_id: Any,
                  source_embed_id: str, output_embed_id: Optional[str], model: Optional[str], log_prefix: str) -> None:
    """Record the strike and audit entry like generated images, then fail the request."""
    from backend.apps.images.tasks.generate_task import _handle_safety_rejection

    tool_response = await _handle_safety_rejection(
        task, rejection, user_id=user_id, prompt=instructions, assistant_response_id=message_id,
        source_embed_id=source_embed_id, output_embed_id=output_embed_id, provider=None, model=model,
        log_prefix=log_prefix,
    )
    raise ModifyFailure(ERROR_SAFETY, str(tool_response.get("user_facing_message") or SAFETY_MESSAGE))


async def _ensure_headroom(task: Any, *, user_id: str, team_id: Optional[str], picture_count: int,
                           log_prefix: str) -> None:
    estimated = await estimate_modify_credits(picture_count=picture_count, author_model=MODIFY_AUTHOR_MODELS[0])
    try:
        if team_id:
            from backend.shared.python_utils.team_skill_billing import ensure_team_skill_credit_headroom

            await ensure_team_skill_credit_headroom(task._directus_service, team_id, user_id, estimated)
        else:
            await ensure_credit_headroom(user_id=user_id, estimated_credits=estimated, log_prefix=log_prefix,
                                         operation_name="picture editing")
    except BillingError as exc:
        raise ModifyFailure(ERROR_CREDITS, CREDITS_MESSAGE) from exc
    except ValueError as exc:
        if str(exc) != "INSUFFICIENT_TEAM_CREDITS":
            raise
        raise ModifyFailure(ERROR_CREDITS, CREDITS_MESSAGE) from exc


async def _load_and_prepare(task: Any, *, plan: InputPlan, user_id: str, vault_key_id: str, s3_service: Any,
                            bucket: str, log_prefix: str) -> tuple[list[LoadedInput], list[Any]]:
    try:
        loaded = await load_modify_inputs(
            task, embed_ids=plan.embed_ids, refs=plan.refs, user_id=user_id, user_vault_key_id=vault_key_id,
            s3_service=s3_service, bucket=bucket, log_prefix=log_prefix,
        )
        prepared = prepare_inputs([(item.name, item.data, item.program_kind) for item in loaded])
    except ReferenceImageUnavailable as exc:
        logger.info("%s Input picture unavailable: %s", log_prefix, exc)
        raise ModifyFailure(ERROR_INVALID_INPUT, UNREADABLE_INPUT_MESSAGE) from exc
    except ModifyInputError as exc:
        raise ModifyFailure(ERROR_INVALID_INPUT, f"The pictures could not be used: {exc}. Nothing was charged.") \
            from exc
    return loaded, prepared


async def run_modify(task: Any, app_id: str, skill_id: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Modify the referenced pictures and publish the result child (or a failed one)."""
    log_prefix = f"[images.modify task:{task.request.id}]"
    user_id = str(arguments.get("user_id") or "")
    vault_key_id = str(arguments.get("user_vault_key_id") or "")
    if not user_id or not vault_key_id:
        raise ValueError("images.modify requires user and vault key identifiers")
    embed_id = str(arguments.get("embed_id") or uuid.uuid4())
    parent_embed_id = str(arguments.get("producer_embed_id") or embed_id)
    chat_id, message_id = arguments.get("chat_id"), arguments.get("message_id")
    team_id = str(arguments["team_id"]) if arguments.get("team_id") else None
    user_id_hash = hashlib.sha256(user_id.encode("utf-8")).hexdigest()
    requested_ids = [str(value) for value in arguments.get("input_embed_ids") or []]
    instructions = str(arguments.get("instructions") or "")
    output_filetype = str(arguments.get("output_filetype") or "png")

    await task.initialize_core_services()
    await _assert_can_generate(task, embed_id=parent_embed_id, chat_id=chat_id, message_id=message_id,
                               owner_hash=user_id_hash)
    embed_service = _embed_service(task)

    async def publish(content: dict[str, Any]) -> None:
        await send_generated_media_child(
            embed_service, parent_embed_id=parent_embed_id, child_embed_id=embed_id,
            child_index=int(arguments.get("media_child_index") or 0), content=content,
            chat_id=chat_id, message_id=message_id, user_id=user_id, user_id_hash=user_id_hash,
            created_at=int(datetime.now(timezone.utc).timestamp()), log_prefix=log_prefix,
        )

    progress = ModifyProgressPublisher(
        embed_service, embed_id=embed_id, parent_embed_id=parent_embed_id, user_id=user_id, chat_id=chat_id,
        message_id=message_id, instructions=instructions, model=display_model(MODIFY_AUTHOR_MODELS[0]),
        output_filetype=output_filetype, input_embed_ids=requested_ids, log_prefix=log_prefix,
    )
    input_ids_for_result: list[str] = requested_ids
    try:
        try:
            request = parse_modify_request(
                instructions=arguments.get("instructions"), images=arguments.get("images"),
                requirements=arguments.get("requirements"), output_filetype=arguments.get("output_filetype"),
            )
        except ModifyRequestError as exc:
            raise ModifyFailure(ERROR_INVALID_REQUEST, str(exc)) from exc
        if len(requested_ids) != len(request.images):
            raise ModifyFailure(ERROR_INVALID_REQUEST, "Every picture reference must resolve to a picture.")
        await progress.announce()
        s3_service = await initialize_task_storage(task)
        await require_storage_available(s3_service)
        bucket = get_bucket_name("chatfiles", s3_service.environment)

        plan = plan_inputs(requested_ids, request.images,
                           await _recall_kept_programs(task, requested_ids, vault_key_id))
        input_ids_for_result = list(plan.embed_ids)
        progress.set_input_embed_ids(input_ids_for_result)
        try:
            loaded, prepared = await _load_and_prepare(task, plan=plan, user_id=user_id, vault_key_id=vault_key_id,
                                                       s3_service=s3_service, bucket=bucket, log_prefix=log_prefix)
        except ModifyFailure:
            if plan.changed_result_id is None:
                raise
            # The kept program's original pictures are past their window: the earlier result is used
            # as an ordinary picture, and the result says so (changed_from_program false).
            logger.info("%s Original inputs of %s unavailable; using it as an ordinary picture", log_prefix,
                        plan.changed_result_id[:8])
            plan = plan_inputs(requested_ids, request.images, {})
            input_ids_for_result = list(plan.embed_ids)
            progress.set_input_embed_ids(input_ids_for_result)
            loaded, prepared = await _load_and_prepare(task, plan=plan, user_id=user_id, vault_key_id=vault_key_id,
                                                       s3_service=s3_service, bucket=bucket, log_prefix=log_prefix)
        await _check_input_safety(task, instructions=request.instructions, prepared=prepared, user_id=user_id,
                                  message_id=message_id, source_embed_id=plan.embed_ids[0], log_prefix=log_prefix)
        await _ensure_headroom(task, user_id=user_id, team_id=team_id, picture_count=len(prepared),
                               log_prefix=log_prefix)
        try:
            authored = await author_modification(
                task_id=str(task.request.id), instructions=request.instructions, inputs=prepared,
                requirements=request.requirements, output_type=request.output_filetype,
                source_program=plan.source_program, secrets_manager=task._secrets_manager, progress=progress,
            )
        except ModifyAuthorError as exc:
            logger.warning("%s No valid picture: %s", log_prefix, exc)
            raise ModifyFailure(ERROR_NO_PICTURE, NO_PICTURE_MESSAGE) from exc
        except ModifyInputError as exc:
            raise ModifyFailure(ERROR_INVALID_INPUT, f"The pictures could not be used: {exc}. Nothing was charged.") \
                from exc
        except ImageEditError as exc:
            logger.warning("%s Sandbox failure %s: %s", log_prefix, exc.code, exc.user_message)
            code = ERROR_INVALID_INPUT if exc.code == "invalid_input" else ERROR_SANDBOX
            raise ModifyFailure(code, f"{exc.user_message} Nothing was charged.") from exc
        await _check_output_safety(
            task, instructions=request.instructions, image=authored.image, mime_type=authored.mime_type,
            user_id=user_id, message_id=message_id, source_embed_id=plan.embed_ids[0], output_embed_id=embed_id,
            model=authored.model_id, log_prefix=log_prefix,
        )
    except ModifyFailure as failure:
        logger.info("%s images.modify failed (%s), not charged", log_prefix, failure.code)
        await publish(build_failed_content(
            skill_id=skill_id, instructions=instructions, output_filetype=output_filetype,
            input_embed_ids=input_ids_for_result, error_code=failure.code, user_message=failure.user_message,
        ))
        return {
            "embed_id": embed_id, "child_embed_id": embed_id, "status": "failed", "child_published": True,
            "error": failure.user_message, "error_code": failure.code, "billing_status": "not_charged",
            "input_embed_ids": input_ids_for_result,
        }

    # Price before storing: a missing price is an error, so nothing is delivered unbilled.
    credits, usage_details = await modify_credits(usage=authored.usage, sandbox_seconds=authored.sandbox_seconds)
    # Kept before storing, so a stored picture always has its program for a later change.
    await remember_program(
        task, embed_id=embed_id, program=authored.program, input_embed_ids=[item.embed_id for item in loaded],
        input_refs=list(plan.refs), vault_key_id=vault_key_id,
    )
    stored = await store_modified_image(
        task, s3_service=s3_service, bucket_name=bucket, user_id=user_id, embed_id=embed_id, authored=authored,
        instructions=request.instructions, vault_key_id=vault_key_id, log_prefix=log_prefix,
    )
    billing_status = await _charge(
        arguments, user_id=user_id, user_id_hash=user_id_hash, app_id=app_id, skill_id=skill_id, credits=credits,
        usage_details=usage_details, model_ref=authored.model_id, team_id=team_id, event_id=embed_id,
        log_prefix=log_prefix,
    )
    content = build_finished_content(
        skill_id=skill_id, stored=stored, authored=authored, instructions=request.instructions,
        input_embed_ids=input_ids_for_result, changed_from_program=plan.changed_result_id is not None,
        billing_status=billing_status,
    )
    await publish(content)
    logger.info("%s images.modify delivered (%s, %d round(s), %d credits)", log_prefix, authored.review_status,
                authored.attempts, credits)
    return assistant_result(embed_id=embed_id, content=content)


async def _charge(arguments: dict[str, Any], *, user_id: str, user_id_hash: str, app_id: str, skill_id: str,
                  credits: int, usage_details: dict[str, Any], model_ref: str, team_id: Optional[str],
                  event_id: str, log_prefix: str) -> str:
    """Charge the delivered picture; a Personal billing failure is recorded on the result, a Team one raises."""
    try:
        await charge_modify_credits(
            user_id=user_id, user_id_hash=user_id_hash, app_id=app_id, skill_id=skill_id, credits=credits,
            usage_details=usage_details, model_ref=model_ref, chat_id=arguments.get("chat_id"),
            message_id=arguments.get("message_id"), team_id=team_id,
            api_key_hash=str(arguments["api_key_hash"]) if arguments.get("api_key_hash") else None,
            device_hash=str(arguments["device_hash"]) if arguments.get("device_hash") else None, event_id=event_id,
        )
    except httpx.HTTPError as exc:
        if team_id:
            raise
        logger.error("%s Picture stored but billing failed; delivering with billing_status=failed: %s",
                     log_prefix, exc, exc_info=True)
        return "failed"
    return "charged"

