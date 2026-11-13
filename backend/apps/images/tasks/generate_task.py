# backend/apps/images/tasks/generate_task.py
#
# Celery task for image generation.
# Handles provider API calls, image processing, encryption, S3 upload, and embed creation.
#
# Architecture:
# - Every generated image is stored as an embed (see docs/architecture/apps/images.md)
# - Embed content contains S3 references, Vault-wrapped AES key, and metadata
# - Download via GET /v1/embeds/{embed_id}/file?format=preview|full|original
# - Server decrypts using Vault and streams plaintext image to client

import logging
import asyncio
import uuid
import json
import math
import hashlib
import os
from datetime import datetime, timezone
from typing import Dict, Any, List, Sequence, Tuple, Optional
from io import BytesIO

import httpx
from PIL import Image

from backend.shared.python_utils.media_encryption import encrypt_media_variants, load_media_write_version
from backend.shared.python_utils.image_mime import validate_raster_image
from backend.shared.python_utils.storage_availability import initialize_task_storage, require_storage_available
from backend.shared.python_utils.chat_recovery_context import RequiredRecoveryOutputError

from backend.core.api.app.tasks.celery_config import app
from backend.core.api.app.tasks.base_task import BaseServiceTask
from backend.core.api.app.utils.image_processing import (
    process_image_for_storage,
    process_svg_for_storage,
)
from backend.shared.providers.google.gemini_image import generate_image_google
from backend.shared.providers.fal.flux import generate_image_fal_flux
from backend.shared.providers.openai.image_generation import generate_image_openai
from backend.shared.providers.recraft.recraft import (
    generate_vector_recraft,
    generate_raster_recraft,
    RECRAFT_MODEL_DEFAULT,
    RECRAFT_MODEL_MAX,
    RECRAFT_RASTER_MODEL_DEFAULT,
    RECRAFT_RASTER_MODEL_FLASH,
    RECRAFT_RASTER_MODEL_MAX,
)
from backend.core.api.app.services.s3.config import get_bucket_name
from backend.shared.python_utils.internal_llm_policy import DEFAULT_POLICY, InternalLlmPolicy
from backend.apps.images.vector_author import (
    MAX_CORRECTION_ROUNDS,
    MAX_SOURCE_SVG_CHARS,
    VECTOR_AUTHOR_MODELS,
    VectorAuthorError,
    VectorAuthorResult,
    VectorUsage,
    author_svg,
    normalize_requirements,
    render_review_jpeg,
    review_with_jev,
)
from backend.apps.images.vector_script import script_run_credits
from backend.apps.images.tasks import image_revision
from backend.core.api.app.services.embed_revision_authority import RevisionRefused
from backend.apps.images.tasks.reference_images import (
    REFERENCE_UNAVAILABLE_MESSAGE,
    ReferenceImageUnavailable,
    load_reference_images,
    remember_vector_script,
)
from backend.shared.python_utils.billing_utils import (
    MINIMUM_CREDITS_CHARGED,
    calculate_credits_from_tokens,
    calculate_total_credits,
    ensure_credit_headroom,
)
from backend.shared.python_utils.generated_assets import (
    build_download_url,
    create_download_token,
    index_generated_asset,
)
from backend.shared.python_utils.image_safety import (
    PipelineDecision,
    SafetyRejection,
    get_pipeline,
    get_strike_counter,
)
from backend.shared.python_utils.image_safety.audit_log import write_audit_entry
from backend.shared.python_utils.media_generation_safety import validate_media_generation_request

logger = logging.getLogger(__name__)

# Internal API configuration for billing calls
INTERNAL_API_BASE_URL = os.getenv("INTERNAL_API_BASE_URL", "http://api:8000")
INTERNAL_API_SHARED_TOKEN = os.getenv("INTERNAL_API_SHARED_TOKEN")
PUBLIC_API_BASE_URL = os.getenv("PUBLIC_API_BASE_URL", "https://api.dev.openmates.org")


async def _fetch_model_pricing_config(model_ref: Optional[str], log_prefix: str) -> Optional[Dict[str, Any]]:
    if not model_ref or "/" not in model_ref:
        return None

    headers = {"Content-Type": "application/json"}
    if INTERNAL_API_SHARED_TOKEN:
        headers["X-Internal-Service-Token"] = INTERNAL_API_SHARED_TOKEN

    provider_id, model_suffix = model_ref.split("/", 1)
    endpoint = f"{INTERNAL_API_BASE_URL}/internal/config/provider_model_pricing/{provider_id}/{model_suffix}"
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(endpoint, headers=headers)
        if response.status_code == 200:
            pricing_config = response.json()
            logger.info(f"{log_prefix} Fetched pricing config for '{model_ref}': {pricing_config}")
            return pricing_config
        logger.warning(f"{log_prefix} Failed to fetch pricing for '{model_ref}': {response.status_code}")
    return None


VECTOR_ENGINE_LLM = "llm"
VECTOR_ENGINE_RECRAFT = "recraft"
# Typical drawing: short request in, one SVG plus reasoning out. Only used for the
# balance check before work starts; the charge itself uses the reported tokens.
VECTOR_AUTHOR_ESTIMATE_INPUT_TOKENS = 1_500
VECTOR_AUTHOR_ESTIMATE_OUTPUT_TOKENS = 8_000


VECTOR_ENGINE_SCRIPT = "script"
_VECTOR_ENGINES = (VECTOR_ENGINE_LLM, VECTOR_ENGINE_SCRIPT, VECTOR_ENGINE_RECRAFT)


def _resolve_vector_engine(value: Any) -> str:
    """Who draws an SVG: the LLM author directly (default), a generator script, or Recraft."""
    engine = str(value or "").lower()
    return engine if engine in _VECTOR_ENGINES else VECTOR_ENGINE_LLM


async def _estimate_vector_author_credits(log_prefix: str) -> int:
    pricing_config = await _fetch_model_pricing_config(VECTOR_AUTHOR_MODELS[0], log_prefix)
    if not pricing_config:
        raise RuntimeError(f"No pricing for vector author model {VECTOR_AUTHOR_MODELS[0]}")
    return max(MINIMUM_CREDITS_CHARGED, calculate_total_credits(
        pricing_config=pricing_config,
        input_tokens=VECTOR_AUTHOR_ESTIMATE_INPUT_TOKENS,
        output_tokens=VECTOR_AUTHOR_ESTIMATE_OUTPUT_TOKENS,
    ))


async def _vector_author_credits(
    usage: List[VectorUsage], log_prefix: str, sandbox_seconds: Sequence[float] = (),
    flat_credits: int = 0,
) -> Tuple[int, Dict[str, Any]]:
    """Price everything one drawing used: model calls by tokens, sandbox runs by time.

    The exact (fractional) credits of all model calls are summed and rounded down
    once, so several small calls are not each rounded up. Each sandbox run adds
    the Code Run price per started minute, and ``flat_credits`` adds a flat
    provider fee (Recraft) that preceded a review. A call without usage or
    without a price is an error, never free: the drawing is not delivered
    unbilled and the user is not charged a guessed amount.
    """
    raw_credits = 0.0
    pricing_by_model: Dict[str, Any] = {}
    steps: List[Dict[str, Any]] = []
    for entry in usage:
        if entry.input_tokens + entry.output_tokens <= 0:
            raise RuntimeError(f"Vector author call '{entry.step}' on {entry.model_id} reported no token usage")
        if entry.model_id not in pricing_by_model:
            pricing_by_model[entry.model_id] = await _fetch_model_pricing_config(entry.model_id, log_prefix)
        pricing_config = pricing_by_model[entry.model_id]
        pricing_rules = (pricing_config or {}).get("pricing", pricing_config)
        if not pricing_rules or "tokens" not in pricing_rules:
            raise RuntimeError(f"No token pricing for vector author model {entry.model_id}")
        step_credits = calculate_credits_from_tokens(entry.input_tokens, entry.output_tokens, pricing_rules)
        raw_credits += step_credits
        steps.append({"step": entry.step, "model_used": entry.model_id, "input_tokens": entry.input_tokens,
                      "output_tokens": entry.output_tokens, "credits": round(step_credits, 4)})
    sandbox_credits = 0
    for seconds in sandbox_seconds:
        run_credits = script_run_credits(seconds)
        sandbox_credits += run_credits
        steps.append({"step": "script_run", "model_used": "e2b/sandbox", "duration_seconds": round(seconds, 2),
                      "credits": run_credits})
    if flat_credits:
        steps.append({"step": "provider_flat_fee", "credits": flat_credits})
    details = {
        "input_tokens": sum(entry.input_tokens for entry in usage),
        "output_tokens": sum(entry.output_tokens for entry in usage),
        "provider_calls": steps,
    }
    token_credits = math.floor(raw_credits)
    if raw_credits > 0 and token_credits == 0:
        token_credits = MINIMUM_CREDITS_CHARGED
    return max(MINIMUM_CREDITS_CHARGED, token_credits + sandbox_credits + flat_credits), details


DRAFT_FLASH_MODEL_REF = f"recraft/{RECRAFT_RASTER_MODEL_FLASH}"
DRAFT_EDIT_MODEL_REF = "bfl/flux-2-klein"


HIGHEST_QUALITY_RASTER_MODEL_REF = "google/gemini-3-pro-image-preview"


def _draft_model_ref_for_references(model_ref: Optional[str], has_reference_images: bool) -> Optional[str]:
    """The text-only Flash draft model cannot take reference images; those drafts use FLUX klein edit."""
    if model_ref == DRAFT_FLASH_MODEL_REF and has_reference_images:
        return DRAFT_EDIT_MODEL_REF
    return model_ref


def _resolve_raster_model_ref(
    model_ref: Optional[str], *, skill_id: Optional[str], quality: str, has_reference_images: bool,
) -> Optional[str]:
    """The pixel-image model that runs for this request.

    images.generate defaults to the cheap Flash model; only quality "max" (an
    explicit highest-quality request) switches the default to Gemini 3 Pro Image.
    Drafts ignore quality. A model the user saved in settings is kept as it is.
    """
    if model_ref == DRAFT_FLASH_MODEL_REF and skill_id == "generate" and quality == "max":
        return HIGHEST_QUALITY_RASTER_MODEL_REF
    return _draft_model_ref_for_references(model_ref, has_reference_images)


def _resolve_image_billing_model_ref(
    model_ref: Optional[str],
    output_filetype: str,
    quality: str,
    has_reference_images: bool,
    vector_engine: str = VECTOR_ENGINE_RECRAFT,
) -> Optional[str]:
    if output_filetype == "svg" and vector_engine in (VECTOR_ENGINE_LLM, VECTOR_ENGINE_SCRIPT):
        return VECTOR_AUTHOR_MODELS[0]
    if output_filetype == "svg":
        recraft_model_id = RECRAFT_MODEL_MAX if quality == "max" else RECRAFT_MODEL_DEFAULT
        return f"recraft/{recraft_model_id}"
    model_ref = _draft_model_ref_for_references(model_ref, has_reference_images)
    if model_ref == DRAFT_FLASH_MODEL_REF:
        return DRAFT_FLASH_MODEL_REF
    if model_ref and "recraft" in model_ref:
        recraft_model_id = RECRAFT_RASTER_MODEL_MAX if quality == "max" else RECRAFT_RASTER_MODEL_DEFAULT
        return f"recraft/{recraft_model_id}"
    if model_ref and ("bfl" in model_ref or "flux" in model_ref) and has_reference_images:
        return "bfl/flux-2-klein-edit"
    if model_ref:
        return model_ref
    return "bfl/flux-2-klein"


async def _estimate_image_generation_credits(model_ref: Optional[str], log_prefix: str) -> int:
    try:
        pricing_config = await _fetch_model_pricing_config(model_ref, log_prefix)
    except Exception as exc:
        logger.warning(f"{log_prefix} Failed to estimate image credits for '{model_ref}': {exc}")
        pricing_config = None

    return (
        calculate_total_credits(pricing_config=pricing_config, units_processed=1)
        if pricing_config
        else MINIMUM_CREDITS_CHARGED
    )


async def _charge_image_generation_credits(
    user_id: str,
    user_id_hash: str,
    app_id: str,
    skill_id: str,
    model_ref: Optional[str],
    chat_id: Optional[str],
    message_id: Optional[str],
    log_prefix: str,
    team_id: Optional[str] = None,
    event_id: Optional[str] = None,
    metered_credits: Optional[int] = None,
    metered_usage: Optional[Dict[str, Any]] = None,
    strict: bool = False,
) -> int:
    """
    Charge a flat per-image credit fee for a successful image generation.

    Returns the credits actually charged (0 when nothing was charged). A failed
    Team charge always raises; ``strict`` (image revisions) makes a failed
    Personal charge raise too, so a change is never published uncharged.

    ``metered_credits`` replaces the flat fee for token-metered engines (the LLM
    vector author); ``metered_usage`` is recorded with the charge.
    
    Fetches the provider pricing config via internal API and charges 1 unit
    (= 1 image). Pricing is defined in provider YAML files:
    - generate_draft (recraft/recraftv4_1_flash): 9 credits per image
    - generate (google/gemini-3-pro-image-preview): 200 credits per image
    
    Billing is non-blocking: failures are logged but don't break image delivery.
    """
    try:
        headers = {"Content-Type": "application/json"}
        if INTERNAL_API_SHARED_TOKEN:
            headers["X-Internal-Service-Token"] = INTERNAL_API_SHARED_TOKEN

        pricing_config = None if metered_credits is not None else await _fetch_model_pricing_config(model_ref, log_prefix)

        # Calculate credits: flat fee per image (1 unit = 1 image)
        if metered_credits is not None:
            credits_charged = metered_credits
        elif pricing_config:
            credits_charged = calculate_total_credits(
                pricing_config=pricing_config,
                units_processed=1
            )
        else:
            credits_charged = MINIMUM_CREDITS_CHARGED
            logger.warning(f"{log_prefix} No pricing config for '{model_ref}', using minimum charge: {credits_charged}")

        if credits_charged <= 0:
            logger.debug(f"{log_prefix} Calculated credits is 0, skipping billing.")
            return 0

        # Resolve provider info (name + region) for usage tracking
        resolved_provider_name = None
        resolved_region = None
        if model_ref and "/" in model_ref:
            try:
                info_provider_id = model_ref.split("/", 1)[0]
                model_ref_param = f"?model_ref={model_ref}"
                info_url = f"{INTERNAL_API_BASE_URL}/internal/config/provider_info/{info_provider_id}{model_ref_param}"
                async with httpx.AsyncClient(timeout=10.0) as info_client:
                    info_resp = await info_client.get(info_url, headers=headers)
                    if info_resp.status_code == 200:
                        provider_info = info_resp.json()
                        resolved_provider_name = provider_info.get("name")
                        resolved_region = provider_info.get("region")
                        logger.debug(f"{log_prefix} Resolved provider info: name={resolved_provider_name}, region={resolved_region}")
            except Exception as e:
                logger.warning(f"{log_prefix} Failed to fetch provider info for model '{model_ref}': {e}")

        charge_payload = {
            "user_id": user_id,
            "user_id_hash": user_id_hash,
            "credits": credits_charged,
            "skill_id": skill_id,
            "app_id": app_id,
            "usage_details": {
                "chat_id": chat_id,
                "message_id": message_id,
                "units_processed": 1,
                "model_used": model_ref,  # Full model reference (e.g., "bfl/flux-2-klein")
                "server_provider": resolved_provider_name,  # Provider display name (e.g., "BFL", "Google")
                "server_region": resolved_region,  # Server region (e.g., "US")
                **(metered_usage or {}),
            }
        }

        from backend.shared.python_utils.team_skill_billing import skill_billing_request
        billing_path, charge_payload = skill_billing_request(
            charge_payload, team_id, event_id=event_id or ""
        )
        async with httpx.AsyncClient(timeout=10.0) as client:
            url = f"{INTERNAL_API_BASE_URL}{billing_path}"
            logger.info(f"{log_prefix} Charging {credits_charged} credits for '{app_id}.{skill_id}' (model: {model_ref})")
            response = await client.post(url, json=charge_payload, headers=headers)
            response.raise_for_status()
            logger.info(f"{log_prefix} Successfully charged {credits_charged} credits for '{app_id}.{skill_id}'")
            return credits_charged

    except httpx.HTTPStatusError as e:
        logger.error(
            f"{log_prefix} HTTP error charging credits for '{app_id}.{skill_id}': "
            f"{e.response.status_code} - {e.response.text}", exc_info=True
        )
        if team_id or strict:
            raise
    except Exception as e:
        logger.error(f"{log_prefix} Error charging credits for '{app_id}.{skill_id}': {e}", exc_info=True)
        if team_id or strict:
            raise
    return 0


def _get_image_dimensions(image_bytes: bytes) -> Tuple[int, int]:
    """Extract width and height from image bytes using PIL."""
    try:
        img = Image.open(BytesIO(image_bytes))
        return img.size  # Returns (width, height)
    except Exception as e:
        logger.warning(f"Failed to get image dimensions: {e}")
        return (0, 0)


def _hash_value(value: str) -> str:
    """Create SHA256 hash of a value for privacy protection."""
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def _content_type_for_image_format(file_format: str) -> str:
    normalized = (file_format or "").lower()
    if normalized == "webp":
        return "image/webp"
    if normalized == "svg":
        return "image/svg+xml"
    if normalized in {"jpg", "jpeg"}:
        return "image/jpeg"
    return "image/png"


def _requested_raster_bytes(image_bytes: bytes, requested_format: str) -> bytes:
    """Honor the requested download format before the labeling postprocessor."""
    if requested_format not in {"png", "jpg"}:
        raise ValueError("Unsupported requested raster output format")
    with Image.open(BytesIO(image_bytes)) as image:
        target = "PNG" if requested_format == "png" else "JPEG"
        if image.format == target:
            return image_bytes
        if target == "JPEG":
            # JPEG cannot carry alpha. Composite both RGBA and palette/LA
            # transparency onto white instead of exposing hidden RGB pixels.
            rgba = image.convert("RGBA")
            converted = Image.new("RGB", image.size, "white")
            converted.paste(rgba, mask=rgba.getchannel("A"))
        else:
            converted = image.convert("RGB") if image.mode == "CMYK" else image
        output = BytesIO()
        converted.save(output, format=target, **({"quality": 98} if target == "JPEG" else {}))
        return output.getvalue()


# ---------------------------------------------------------------------------
# Image safety pipeline integration
# See docs/architecture/image-safety-pipeline.md §2, §3, §5, §9
# ---------------------------------------------------------------------------

# Redis key for the per-assistant-response rejection cache used to enforce
# `do_not_retry`: once one images-generate call in a response is rejected, any
# subsequent call in the same response is auto-rejected without invoking the
# classifiers.
_SAFETY_REJECT_CACHE_TTL = 1800  # 30 minutes — longer than any AI response


def _safety_reject_cache_key(user_id: str, assistant_response_id: str) -> str:
    return f"safety_response_reject:{user_id}:{assistant_response_id}"


async def _check_cached_safety_rejection(
    task: BaseServiceTask,
    user_id: str,
    assistant_response_id: Optional[str],
) -> Optional[Dict[str, Any]]:
    """
    Return the cached rejection payload for this (user, response) pair, if any.

    Used to auto-reject subsequent images-generate calls within the same
    assistant response after the first rejection — see pipeline doc §9
    "do_not_retry auto-reject behavior".
    """
    if not assistant_response_id:
        return None
    try:
        client = await task._cache_service.client
        if not client:
            return None
        raw = await client.get(_safety_reject_cache_key(user_id, assistant_response_id))
        if not raw:
            return None
        return json.loads(raw)
    except Exception as e:
        logger.warning(f"[ImageSafety] Failed to read reject cache: {e}")
        return None


async def _cache_safety_rejection(
    task: BaseServiceTask,
    user_id: str,
    assistant_response_id: Optional[str],
    rejection_payload: Dict[str, Any],
) -> None:
    """Cache a rejection payload so subsequent sub-calls auto-reject."""
    if not assistant_response_id:
        return
    try:
        client = await task._cache_service.client
        if not client:
            return
        await client.set(
            _safety_reject_cache_key(user_id, assistant_response_id),
            json.dumps(rejection_payload),
            ex=_SAFETY_REJECT_CACHE_TTL,
        )
    except Exception as e:
        logger.warning(f"[ImageSafety] Failed to write reject cache: {e}")


async def _handle_safety_rejection(
    task: BaseServiceTask,
    rejection: SafetyRejection,
    *,
    user_id: str,
    prompt: str,
    assistant_response_id: Optional[str],
    source_embed_id: Optional[str],
    output_embed_id: Optional[str],
    provider: Optional[str],
    model: Optional[str],
    log_prefix: str,
) -> Dict[str, Any]:
    """
    Unified rejection handler: records the strike, writes the audit log,
    caches the rejection for the remainder of the assistant response, and
    returns the structured tool response for the LLM.
    """
    strike_counter = get_strike_counter(task._cache_service)
    strike_result = await strike_counter.record_strike(
        user_id=user_id,
        severity=rejection.severity,
        assistant_response_id=assistant_response_id,
    )

    await write_audit_entry(
        directus_service=task._directus_service,
        user_id=user_id,
        stage=rejection.stage,
        decision="block",
        category=rejection.category,
        severity=rejection.severity,
        strike_weight=(0 if strike_result.debounced else
                       {"critical": 4, "adversarial": 2, "severe": 2,
                        "moderate": 1}.get(rejection.severity, 1)),
        sightengine_json=rejection.sightengine_audit,
        vlm_json=rejection.vlm_audit,
        safeguard_reasoning=(rejection.safeguard_audit or {}).get("reasoning"),
        provider=provider,
        model=model,
        source_embed_id=source_embed_id,
        output_embed_id=output_embed_id,
        prompt=prompt,
        assistant_response_id=assistant_response_id,
    )

    await _cache_safety_rejection(
        task, user_id, assistant_response_id, rejection.tool_response
    )

    logger.warning(
        f"{log_prefix} [ImageSafety] REJECTED at stage={rejection.stage} "
        f"category={rejection.category} severity={rejection.severity} "
        f"reason={rejection.reason} strike_count={strike_result.new_count} "
        f"ban={strike_result.ban_triggered} debounced={strike_result.debounced}"
    )

    # Ban path — kept best-effort; delegated to internal ban endpoint if the
    # strike counter crossed the threshold. Current upload-content-safety-reject
    # endpoint already implements account deletion, so we reuse the pattern
    # here when weight pushes the counter over the threshold.
    if strike_result.ban_triggered and not strike_result.debounced:
        await _trigger_safety_ban(
            user_id=user_id,
            category=rejection.category,
            log_prefix=log_prefix,
        )

    return rejection.tool_response


async def _trigger_safety_ban(
    *,
    user_id: str,
    category: str,
    log_prefix: str,
) -> None:
    """
    Call the internal API ban endpoint. Best-effort; logs on failure.
    Mirrors the existing upload-content-safety-reject behavior.
    """
    try:
        headers = {"Content-Type": "application/json"}
        if INTERNAL_API_SHARED_TOKEN:
            headers["X-Internal-Service-Token"] = INTERNAL_API_SHARED_TOKEN
        async with httpx.AsyncClient(timeout=15) as client:
            await client.post(
                f"{INTERNAL_API_BASE_URL}/internal/uploads/content-safety-reject",
                json={
                    "user_id": user_id,
                    "rejection_reason": f"image_generation_safety:{category}",
                    "upload_type": "chat_image",
                },
                headers=headers,
            )
        logger.warning(f"{log_prefix} [ImageSafety] Ban triggered for user")
    except Exception as e:
        logger.error(
            f"{log_prefix} [ImageSafety] Ban trigger failed (non-fatal): {e}",
            exc_info=True,
        )


async def _emit_safety_rejection_embed(
    task: BaseServiceTask,
    *,
    embed_id: Optional[str],
    user_id: str,
    chat_id: Optional[str],
    message_id: Optional[str],
    user_facing_message: str,
    log_prefix: str,
) -> None:
    """
    Emit an error embed to the client so the user sees why the generation
    was blocked. Mirrors the existing error-embed flow at the bottom of
    _async_generate_image but uses the safety user_facing_message.
    """
    if not (embed_id and user_id and chat_id and message_id):
        return
    from backend.shared.python_utils.chat_recovery_context import active_verified_output_producer
    producer = active_verified_output_producer.get()
    if producer is not None and embed_id != producer.primary_embed_id:
        # A batch child has no successful asset to publish; its parent records
        # the failed slot when all requests finish.
        return
    try:
        from toon_format import encode as toon_encode
        from backend.core.api.app.services.embed_service import EmbedService

        error_content = {
            "app_id": "images",
            "skill_id": "generate",
            "type": "image",
            "status": "error",
            "error": user_facing_message,
            "safety_rejection": True,
        }
        content_toon = toon_encode(error_content)
        now_ts = int(datetime.now(timezone.utc).timestamp())

        embed_service = EmbedService(
            cache_service=task._cache_service,
            directus_service=task._directus_service,
            encryption_service=task._encryption_service,
        )
        await embed_service.send_embed_data_to_client(
            embed_id=embed_id,
            embed_type="app_skill_use",
            content_toon=content_toon,
            chat_id=str(chat_id),
            message_id=str(message_id),
            user_id=user_id,
            user_id_hash=_hash_value(user_id),
            status="error",
            encryption_mode="client",
            created_at=now_ts,
            updated_at=now_ts,
            log_prefix=f"{log_prefix} [SAFETY_REJECT]",
            check_cache_status=False,
        )
    except Exception as e:
        logger.error(
            f"{log_prefix} Failed to emit safety rejection embed: {e}",
            exc_info=True,
        )


@app.task(
    bind=True,
    name="apps.images.tasks.skill_generate",
    base=BaseServiceTask,
    queue="app_images",
    soft_time_limit=3300,
    time_limit=3360
)
def generate_image_task(self, app_id: str, skill_id: str, arguments: Dict[str, Any]):
    """
    Celery task for high-end image generation.
    """
    from backend.shared.python_utils.generated_media_graph import run_generated_media_batch
    return asyncio.run(image_revision.run_with_batch_claims(run_generated_media_batch(
        self, app_id=app_id, skill_id=skill_id, arguments=arguments,
        generate_one=_async_generate_image,
    ))) if arguments.get("requests") else asyncio.run(_async_generate_image(self, app_id, skill_id, arguments))


@app.task(
    bind=True,
    name="apps.images.tasks.skill_generate_draft",
    base=BaseServiceTask,
    queue="app_images",
    soft_time_limit=3300,
    time_limit=3360
)
def generate_image_draft_task(self, app_id: str, skill_id: str, arguments: Dict[str, Any]):
    """
    Celery task for draft image generation.
    """
    from backend.shared.python_utils.generated_media_graph import run_generated_media_batch
    return asyncio.run(image_revision.run_with_batch_claims(run_generated_media_batch(
        self, app_id=app_id, skill_id=skill_id, arguments=arguments,
        generate_one=_async_generate_image,
    ))) if arguments.get("requests") else asyncio.run(_async_generate_image(self, app_id, skill_id, arguments))


def _vector_result_fields(authored: VectorAuthorResult, vector_engine: str) -> Dict[str, Any]:
    """Provenance of a vector drawing stored with the embed (and read back for later changes)."""
    fields: Dict[str, Any] = {
        "vector_engine": vector_engine,
        "vector_review": authored.review_status,
        "vector_attempts": authored.attempts,
    }
    if authored.unmet_requirements:
        fields["vector_unmet_requirements"] = list(authored.unmet_requirements)
    if authored.script:
        fields["vector_script"] = authored.script
    return fields


async def _flat_image_credits(model_ref: str, log_prefix: str) -> int:
    """Flat per-image price of a provider model; missing pricing is an error, not a guess."""
    pricing_config = await _fetch_model_pricing_config(model_ref, log_prefix)
    if not pricing_config:
        raise RuntimeError(f"No pricing for image model {model_ref}")
    return calculate_total_credits(pricing_config=pricing_config, units_processed=1)


async def _review_and_follow_up_recraft_svg(
    task: BaseServiceTask, svg: str, *, prompt: str, aspect_ratio: str, quality: str,
    requirements: List[str], task_id: str, on_draft: Any, policy: Optional[InternalLlmPolicy] = None,
) -> VectorAuthorResult:
    """Check a Recraft drawing against the requirements; let the LLM author fix clear misses."""
    review = await review_with_jev(
        svg=svg, prompt=prompt, requirements=requirements, is_modification=False,
        secrets_manager=task._secrets_manager, task_id=task_id, policy=policy,
    )
    usage = ([VectorUsage("review", review.model_id, review.input_tokens, review.output_tokens)]
             if review.input_tokens else [])
    reviewed = VectorAuthorResult(
        svg=svg, model_id="recraft", attempts=1, review_status=review.status, usage=usage,
        engine=VECTOR_ENGINE_RECRAFT, unmet_requirements=review.unmet,
    )
    if review.accepted:
        return reviewed
    follow_up_prompt = f"{prompt}\n\nThe current version has this problem: {review.feedback}. Fix it and keep the rest."
    # A traced drawing that is too large to edit as source is redrawn from its rendering.
    editable = len(svg) <= MAX_SOURCE_SVG_CHARS
    try:
        fixed = await author_svg(
            task_id=task_id, prompt=follow_up_prompt, aspect_ratio=aspect_ratio, quality=quality,
            requirements=requirements, source_svgs=[svg] if editable else [],
            reference_images=[] if editable else [(render_review_jpeg(svg), "image/jpeg")],
            secrets_manager=task._secrets_manager, on_draft=on_draft, max_attempts=MAX_CORRECTION_ROUNDS,
            policy=policy,
        )
    except VectorAuthorError as exc:
        # The follow-up produced nothing usable: the Recraft drawing is delivered with what it misses.
        logger.warning("[Task ID: %s] Recraft follow-up failed, delivering the original: %s", task_id, exc)
        return reviewed
    fixed.usage[:0] = usage
    fixed.attempts += 1
    return fixed


def _planned_display_model(model_ref: Optional[str], output_filetype: str, use_vector_author: bool,
                           quality: str, policy: Optional[InternalLlmPolicy] = None) -> Optional[str]:
    """Short id of the model that starts this request, as the client's model metadata knows it."""
    if use_vector_author:
        routes = (policy or DEFAULT_POLICY).author_routes(VECTOR_AUTHOR_MODELS)
        return (routes[0].model_id if routes else VECTOR_AUTHOR_MODELS[0]).split("/")[-1]
    if output_filetype == "svg":
        return RECRAFT_MODEL_MAX if quality == "max" else RECRAFT_MODEL_DEFAULT
    return model_ref.split("/")[-1] if model_ref else None


class _VectorDraftPublisher:
    """Sends the SVG written so far to the client so the picture builds up while it is drawn.

    Drafts go out as ``processing`` updates of the result embed and are never
    stored: only the finished drawing is encrypted, uploaded and persisted.
    """

    def __init__(self, task: BaseServiceTask, *, arguments: Dict[str, Any], embed_id: str, prompt: Any,
                 aspect_ratio: str, user_id: str, chat_id: Optional[str], message_id: Optional[str],
                 log_prefix: str, output_filetype: str = "svg", model: Optional[str] = None,
                 input_embed_ids: Optional[List[str]] = None,
                 revised_from: Optional[Dict[str, Any]] = None) -> None:
        from backend.core.api.app.services.embed_service import EmbedService
        self._embed_service = EmbedService(
            cache_service=task._cache_service,
            directus_service=task._directus_service,
            encryption_service=task._encryption_service,
        )
        self._embed_id = embed_id
        self._parent_embed_id = arguments.get("producer_embed_id") or embed_id
        self._base_content = {
            "app_id": "images", "skill_id": "generate", "type": "generated_image", "status": "processing",
            "prompt": prompt, "aspect_ratio": aspect_ratio, "output_filetype": output_filetype,
            # What the skill was asked to do, shown on the card until a picture exists.
            "model": model, "input_embed_ids": list(input_embed_ids or []),
            # A change of an existing image: the version it starts from (wire-contract.md).
            **({"revised_from": revised_from} if revised_from else {}),
        }
        self._user_id = user_id
        self._user_id_hash = _hash_value(user_id)
        self._chat_id = chat_id
        self._message_id = message_id
        self._log_prefix = log_prefix

    async def announce(self) -> None:
        """Tell the client the request (prompt, model, input images) before any picture exists."""
        await self.publish("", "starting", 1)

    async def publish(self, svg_draft: str, stage: str, attempt: int) -> None:
        if not self._chat_id or not self._message_id:
            return
        from toon_format import encode as toon_encode
        content = {**self._base_content, "svg_draft": svg_draft, "draft_stage": stage, "draft_attempt": attempt}
        await self._embed_service.send_embed_data_to_client(
            embed_id=self._embed_id,
            embed_type="generated_image",
            content_toon=toon_encode(content),
            chat_id=self._chat_id,
            message_id=self._message_id,
            user_id=self._user_id,
            user_id_hash=self._user_id_hash,
            status="processing",
            encryption_mode="client",
            parent_embed_id=self._parent_embed_id if self._parent_embed_id != self._embed_id else None,
            log_prefix=self._log_prefix,
            check_cache_status=False,
            app_id="images",
            skill_id="generated_image",
        )


async def _async_generate_image(task: BaseServiceTask, app_id: str, skill_id: str, arguments: Dict[str, Any]):
    task_id = task.request.id
    log_prefix = f"[Task ID: {task_id}]"
    logger.info(f"{log_prefix} Starting image generation task for {app_id}/{skill_id}")
    
    try:
        # 1. Initialize services (S3, Secrets, Encryption, Directus)
        await task.initialize_core_services()
        
        # 2. Extract arguments
        prompt = arguments.get("prompt")
        user_id = arguments.get("user_id")
        chat_id = arguments.get("chat_id")
        message_id = arguments.get("message_id")
        external_request = bool(arguments.get("external_request"))
        aspect_ratio = arguments.get("aspect_ratio", "1:1")
        model_ref = arguments.get("full_model_reference")
        # output_filetype: "png", "jpg", or "svg" (defaults to "png" for backward compat)
        output_filetype = str(arguments.get("output_filetype", "png")).lower()
        # quality: "default" or "max" — only used when output_filetype="svg"
        quality = str(arguments.get("quality", "default")).lower()
        # style: Recraft artistic style (e.g. "realistic_image", "digital_illustration")
        style = arguments.get("style")
        # vector_engine: who draws an SVG — the LLM vector author (default) or Recraft.
        vector_engine = _resolve_vector_engine(arguments.get("vector_engine"))
        # The user's AI model and server settings for the drawing author and its review.
        llm_policy = InternalLlmPolicy.from_payload(arguments.get("internal_llm_policy"))
        use_vector_author = output_filetype == "svg" and vector_engine != VECTOR_ENGINE_RECRAFT
        # Natural-language requirements a vector result is checked against (no review without them).
        vector_requirements = normalize_requirements(arguments.get("requirements")) if output_filetype == "svg" else []
        reference_svg_sources: List[str] = []
        reference_script_sources: List[str] = []
        # Reference images for image-to-image generation (resolved embed IDs from skill layer)
        reference_image_embed_ids: List[str] = arguments.get("reference_image_embed_ids") or []
        model_ref = _resolve_raster_model_ref(
            model_ref, skill_id=arguments.get("skill_id"), quality=quality,
            has_reference_images=bool(reference_image_embed_ids),
        )
        user_vault_key_id: Optional[str] = arguments.get("user_vault_key_id")

        if not prompt or not user_id:
            raise ValueError(f"Missing required arguments: prompt={bool(prompt)}, user_id={bool(user_id)}")

        # 3. Get embed_id from arguments (passed by the skill) or generate new one
        embed_id = arguments.get("embed_id") or str(uuid.uuid4())
        logger.info(f"{log_prefix} Using embed_id: {embed_id}")
        # A change of a generated image of this chat becomes its next version (images-generate.revision.*).
        revision = await image_revision.find_revision_target(
            task._directus_service, reference_embed_ids=reference_image_embed_ids, chat_id=chat_id,
            user_id=user_id, external_request=external_request,
        )
        output_embed_id = revision.embed_id if revision else embed_id
        if revision:
            logger.info(f"{log_prefix} Revising image {revision.embed_id} to version {revision.next_version}")

        # The card shows the request while nothing is drawn yet. The model named
        # here is the one that starts the work; the finished embed stores the
        # model that actually produced the result.
        progress_publisher = None if external_request else _VectorDraftPublisher(
            task, arguments=arguments, embed_id=embed_id, prompt=prompt, aspect_ratio=aspect_ratio,
            user_id=user_id, chat_id=chat_id, message_id=message_id, log_prefix=log_prefix,
            output_filetype=output_filetype, input_embed_ids=reference_image_embed_ids,
            model=_planned_display_model(model_ref, output_filetype, use_vector_author, quality, llm_policy),
            revised_from=image_revision.revision_content_fields(revision)["revised_from"] if revision else None,
        )
        if progress_publisher:
            await progress_publisher.announce()
        from backend.core.api.app.services.embed_service import EmbedService
        await EmbedService.assert_registered_output_can_generate(
            task._directus_service, embed_id=arguments.get("producer_embed_id") or embed_id, chat_id=chat_id,
            message_id=message_id, owner_hash=_hash_value(user_id),
        )

        media_decision = validate_media_generation_request(
            media_type="image",
            prompt=str(prompt),
            request_count=1,
            style=style,
            named_person_reviewed=arguments.get("named_person_reviewed") is True,
        )
        if not media_decision.allowed:
            tool_response = media_decision.to_rejection_payload()
            logger.warning(
                "%s [MediaSafety] REJECTED category=%s reason=%s",
                log_prefix,
                media_decision.category,
                media_decision.reason,
            )
            await _emit_safety_rejection_embed(
                task,
                embed_id=embed_id,
                user_id=user_id,
                chat_id=chat_id,
                message_id=message_id,
                user_facing_message=str(tool_response["user_facing_message"]),
                log_prefix=log_prefix,
            )
            return {"embed_id": embed_id, "status": "rejected", **tool_response}

        s3_service = await initialize_task_storage(task)
        await require_storage_available(s3_service)

        # 3b. Decrypt reference images (for image-to-image generation).
        # Reference image embed IDs were resolved by the skill layer (embed_ref → embed_id).
        # We fetch and decrypt them here in the task so that image bytes are never stored
        # in the Celery message queue (avoids size limits on large images).
        # Every named reference must load; drawing without it would answer (and bill) a different request.
        references = await load_reference_images(
            task, embed_ids=list(reference_image_embed_ids or []), user_id=user_id,
            user_vault_key_id=user_vault_key_id, s3_service=s3_service,
            want_vector_sources=use_vector_author, log_prefix=log_prefix,
        )
        reference_image_bytes_list: List[bytes] = [image for image, _ in references.images]
        reference_image_mime_types: List[str] = [mime for _, mime in references.images]
        reference_svg_sources.extend(references.svg_sources)
        reference_script_sources.extend(references.script_sources)

        # 3c. Image Safety Pipeline — input validation
        # See docs/architecture/image-safety-pipeline.md §2, §3
        cached_rejection = await _check_cached_safety_rejection(
            task, user_id, message_id
        )
        if cached_rejection:
            logger.info(
                f"{log_prefix} [ImageSafety] Auto-rejecting (cached decision "
                f"for assistant_response_id={message_id}): "
                f"{cached_rejection.get('category')}"
            )
            await _emit_safety_rejection_embed(
                task,
                embed_id=embed_id,
                user_id=user_id,
                chat_id=chat_id,
                message_id=message_id,
                user_facing_message=cached_rejection.get(
                    "user_facing_message", "This image couldn't be generated."
                ),
                log_prefix=log_prefix,
            )
            return {
                "embed_id": embed_id,
                "status": "rejected",
                **cached_rejection,
            }

        pipeline = get_pipeline()
        safety_reference_images = list(
            zip(reference_image_bytes_list, reference_image_mime_types)
        )
        input_decision: PipelineDecision = await pipeline.validate_input(
            prompt=prompt,
            reference_images=safety_reference_images,
            secrets_manager=task._secrets_manager,
        )

        if not input_decision.allowed and input_decision.rejection:
            tool_response = await _handle_safety_rejection(
                task,
                input_decision.rejection,
                user_id=user_id,
                prompt=prompt,
                assistant_response_id=message_id,
                source_embed_id=(
                    reference_image_embed_ids[0]
                    if reference_image_embed_ids
                    else None
                ),
                output_embed_id=None,
                provider=None,
                model=model_ref,
                log_prefix=log_prefix,
            )
            await _emit_safety_rejection_embed(
                task,
                embed_id=embed_id,
                user_id=user_id,
                chat_id=chat_id,
                message_id=message_id,
                user_facing_message=tool_response.get(
                    "user_facing_message", "This image couldn't be generated."
                ),
                log_prefix=log_prefix,
            )
            return {
                "embed_id": embed_id,
                "status": "rejected",
                **tool_response,
            }

        precheck_model_ref = _resolve_image_billing_model_ref(
            model_ref,
            output_filetype,
            quality,
            bool(reference_image_bytes_list),
            vector_engine,
        )
        estimated_credits = (
            await _estimate_vector_author_credits(log_prefix)
            if use_vector_author
            else await _estimate_image_generation_credits(precheck_model_ref, log_prefix)
        )
        if arguments.get("team_id"):
            from backend.shared.python_utils.team_skill_billing import ensure_team_skill_credit_headroom
            await ensure_team_skill_credit_headroom(
                task._directus_service, arguments["team_id"], user_id, estimated_credits
            )
        else:
            await ensure_credit_headroom(
                user_id=user_id,
                estimated_credits=estimated_credits,
                log_prefix=log_prefix,
                operation_name="image generation",
            )

        # 4. Call Provider API
        #
        # Routing logic:
        #   output_filetype == "svg"  → Recraft V4.1 Vector (returns SVG bytes)
        #     quality == "default"    → recraftv4_1_vector     (100 credits, $0.08)
        #     quality == "max"        → recraftv4_1_pro_vector (300 credits, $0.30)
        #   output_filetype == "png"/"jpg" and "recraft" in model_ref → Recraft V4.1 Raster
        #     quality == "default"    → recraftv4_1     ( 50 credits, $0.04)
        #     quality == "max"        → recraftv4_1_pro (250 credits, $0.25)
        #   output_filetype == "png"/"jpg" and "openai" in model_ref → GPT Image 2
        #   output_filetype == "png"/"jpg" and "google" in model_ref → Google Gemini (default)
        #   output_filetype == "png"/"jpg" and "bfl"/"flux" in model_ref → fal.ai FLUX
        #
        # actual_model:    full provider reference for logging and XMP metadata
        # display_model_id: short model ID for embed content (matches frontend modelsMetadata)
        logger.info(
            f"{log_prefix} Calling provider for model: {model_ref}, "
            f"output_filetype={output_filetype}, quality={quality}"
        )
        image_bytes: Optional[bytes] = None
        svg_bytes: Optional[bytes] = None
        actual_model = model_ref or "Unknown AI"
        display_model_id = (
            model_ref.split("/")[-1]
            if model_ref and "/" in model_ref
            else (model_ref or "Unknown")
        )

        metered_credits: Optional[int] = None
        metered_usage: Optional[Dict[str, Any]] = None
        authored: Optional[VectorAuthorResult] = None
        draft_publisher = progress_publisher if output_filetype == "svg" else None
        on_draft = draft_publisher.publish if draft_publisher else None
        if use_vector_author:
            # --- SVG branch: vector author (writes the SVG or a generator script, checks, corrects) ---
            # A script-made reference is changed through its generator and a vector
            # reference through its SVG source; only pixel references are attached
            # as images for the author to redraw.
            source_script = reference_script_sources[0] if reference_script_sources else None
            if source_script:
                # A computed drawing is always changed through its generator: editing its
                # (large) generated SVG by hand would cost far more and lose the structure.
                vector_engine = VECTOR_ENGINE_SCRIPT
            source_svgs = [] if source_script else reference_svg_sources
            pixel_references = [] if (source_script or source_svgs) else list(
                zip(reference_image_bytes_list, reference_image_mime_types)
            )
            authored = await author_svg(
                task_id=str(task_id), prompt=str(prompt), aspect_ratio=aspect_ratio, quality=quality,
                engine=vector_engine, requirements=vector_requirements,
                source_svgs=source_svgs, reference_images=pixel_references, source_script=source_script,
                secrets_manager=task._secrets_manager, on_draft=on_draft, policy=llm_policy,
            )
            svg_bytes = authored.svg.encode("utf-8")
            model_ref = authored.model_id
            actual_model = authored.model_id
            display_model_id = authored.model_id.split("/")[-1]
            metered_credits, metered_usage = await _vector_author_credits(
                authored.usage, log_prefix, authored.sandbox_seconds,
            )

        elif output_filetype == "svg":
            # --- SVG branch: Recraft V4.1 Vector ---
            # Both "default" and "max" use the same generate skill;
            # quality selects between the two Recraft model tiers.
            recraft_model_id = RECRAFT_MODEL_MAX if quality == "max" else RECRAFT_MODEL_DEFAULT
            svg_bytes = await generate_vector_recraft(
                prompt=prompt,
                secrets_manager=task._secrets_manager,
                model_id=recraft_model_id,
                size=aspect_ratio,  # Recraft accepts "w:h" format natively
                style_id=style,
            )
            actual_model = f"Recraft {recraft_model_id}"
            display_model_id = recraft_model_id
            # Override model_ref for billing so pricing is looked up from recraft.yml
            model_ref = f"recraft/{recraft_model_id}"
            if vector_requirements:
                # The Recraft drawing is checked against the requirements like any other;
                # clearly unmet ones trigger a follow-up by the LLM vector author.
                authored = await _review_and_follow_up_recraft_svg(
                    task, svg_bytes.decode("utf-8"), prompt=str(prompt), aspect_ratio=aspect_ratio,
                    quality=quality, requirements=vector_requirements, task_id=str(task_id), on_draft=on_draft,
                    policy=llm_policy,
                )
                svg_bytes = authored.svg.encode("utf-8")
                metered_credits, metered_usage = await _vector_author_credits(
                    authored.usage, log_prefix, authored.sandbox_seconds,
                    flat_credits=await _flat_image_credits(model_ref, log_prefix),
                )

        elif model_ref == DRAFT_FLASH_MODEL_REF:
            # --- Raster branch: Recraft V4.1 Flash text-only draft (no style, no references) ---
            image_bytes = await generate_raster_recraft(
                prompt=prompt,
                secrets_manager=task._secrets_manager,
                model_id=RECRAFT_RASTER_MODEL_FLASH,
                size=aspect_ratio,
                style_id=None,
            )
            actual_model = f"Recraft {RECRAFT_RASTER_MODEL_FLASH}"
            display_model_id = RECRAFT_RASTER_MODEL_FLASH

        elif model_ref and "recraft" in model_ref:
            # --- Raster branch: Recraft V4.1 PNG/JPG ---
            # Recraft V4.1 also supports high-quality raster generation.
            # quality selects between the two Recraft raster model tiers:
            #   "default" → recraftv4_1     ( 50 credits, $0.04)
            #   "max"     → recraftv4_1_pro (250 credits, $0.25)
            recraft_raster_model_id = (
                RECRAFT_RASTER_MODEL_MAX if quality == "max" else RECRAFT_RASTER_MODEL_DEFAULT
            )
            image_bytes = await generate_raster_recraft(
                prompt=prompt,
                secrets_manager=task._secrets_manager,
                model_id=recraft_raster_model_id,
                size=aspect_ratio,  # Recraft accepts "w:h" format natively
                style_id=style,
            )
            actual_model = f"Recraft {recraft_raster_model_id}"
            display_model_id = recraft_raster_model_id
            # Override model_ref for billing so pricing is looked up from recraft.yml
            model_ref = f"recraft/{recraft_raster_model_id}"

        elif model_ref and "google" in model_ref:
            # --- Raster branch: Google Gemini image generation ---
            # Supports both text-to-image and image-to-image via the same endpoint.
            # Reference images are passed as inline_data Parts alongside the text prompt.
            # Pricing stays at flat 200 credits even with reference images (input cost negligible).
            #
            # Server fallback chain:
            #   1. Google AI Studio (API key, known US region) — primary
            #   2. Google Vertex AI (service account, global endpoint) — fallback
            model_id = model_ref.split("/")[-1] if "/" in model_ref else model_ref
            try:
                image_bytes = await generate_image_google(
                    prompt=prompt,
                    secrets_manager=task._secrets_manager,
                    aspect_ratio=aspect_ratio,
                    model_id=model_id,
                    reference_image_bytes_list=reference_image_bytes_list or None,
                    reference_image_mime_types=reference_image_mime_types or None,
                    use_vertex=False,  # Primary: AI Studio (known US location)
                )
            except Exception as ai_studio_err:
                logger.warning(
                    f"{log_prefix} AI Studio failed for Gemini image generation "
                    f"({type(ai_studio_err).__name__}: {ai_studio_err}). "
                    "Retrying with Vertex AI (global endpoint) as fallback..."
                )
                image_bytes = await generate_image_google(
                    prompt=prompt,
                    secrets_manager=task._secrets_manager,
                    aspect_ratio=aspect_ratio,
                    model_id=model_id,
                    reference_image_bytes_list=reference_image_bytes_list or None,
                    reference_image_mime_types=reference_image_mime_types or None,
                    use_vertex=True,  # Fallback: Vertex AI (global endpoint)
                )
            actual_model = f"Google {model_id}"
            display_model_id = model_id

        elif model_ref and "openai" in model_ref:
            # --- Raster branch: OpenAI GPT Image generation ---
            # Billing uses a conservative flat 250 credits/image for GPT Image 2,
            # covering the published high-quality 1024 estimate (~$0.211/image).
            model_id = model_ref.split("/")[-1] if "/" in model_ref else model_ref
            image_bytes = await generate_image_openai(
                prompt=prompt,
                secrets_manager=task._secrets_manager,
                model_id=model_id,
                aspect_ratio=aspect_ratio,
                quality=quality,
                reference_image_bytes_list=reference_image_bytes_list or None,
                reference_image_mime_types=reference_image_mime_types or None,
            )
            actual_model = f"OpenAI {model_id}"
            display_model_id = model_id

        elif model_ref and ("bfl" in model_ref or "flux" in model_ref):
            # --- Raster branch: fal.ai FLUX ---
            # Text-to-image: bfl/flux-2-klein → fal-ai/flux-2/klein/9b/base (15 credits)
            # Image-to-image: auto-switches to fal-ai/flux-2/klein/4b/base/edit (27 credits)
            #   via generate_image_fal_flux — the provider function handles the routing.
            #   We update model_ref here for billing to use the correct pricing config.
            fal_model_id = "fal-ai/flux-2/klein/9b/base"
            if "pro" in model_ref:
                fal_model_id = "fal-ai/flux-pro/v1.1"
            image_bytes = await generate_image_fal_flux(
                prompt=prompt,
                secrets_manager=task._secrets_manager,
                model_id=fal_model_id,
                reference_image_bytes_list=reference_image_bytes_list or None,
                reference_image_mime_types=reference_image_mime_types or None,
            )
            if reference_image_bytes_list:
                # Image-to-image was used — update billing to the 4B edit model (27 credits)
                actual_model = "fal.ai fal-ai/flux-2/klein/4b/base/edit"
                model_ref = "bfl/flux-2-klein-edit"
                display_model_id = "flux-2-klein-edit"
            else:
                actual_model = f"fal.ai {fal_model_id}"
                # display_model_id already set from model_ref split (e.g., "flux-2-klein")

        else:
            # --- Fallback: FLUX.2 [klein] 9B if model ref is unknown/missing ---
            # No reference image support in fallback path (model_ref required for routing).
            logger.warning(
                f"{log_prefix} Unknown or missing model reference '{model_ref}', "
                "falling back to FLUX.2 [klein] 9B"
            )
            fal_model_id = "fal-ai/flux-2/klein/9b/base"
            image_bytes = await generate_image_fal_flux(
                prompt=prompt,
                secrets_manager=task._secrets_manager,
                model_id=fal_model_id,
            )
            actual_model = f"fal.ai {fal_model_id} (fallback)"
            display_model_id = "flux-2-klein"

        # Validate that the provider returned data
        if output_filetype == "svg" and not svg_bytes:
            raise Exception("Recraft provider returned empty SVG data")
        if output_filetype != "svg" and not image_bytes:
            raise Exception("Provider returned empty image data")

        # Log actual provider model used; display_model_id is stored in embed content
        logger.info(
            f"{log_prefix} Provider model: {actual_model}, display ID: {display_model_id}"
        )

        # 4b. Image Safety Pipeline — output validation
        # Run parallel Sightengine + Gemini scan against the generated image
        # with stricter thresholds. SVG is skipped (vector images are not
        # photorealistic) but raster output from any provider goes through
        # the same dual scan regardless of source.
        #
        # NOTE: This runs BEFORE billing. If the output is rejected:
        #   - the generated image is discarded (never persisted to S3)
        #   - the user is not charged for the generation
        #   - the audit log records full classifier detail
        #   - a strike is recorded (debounced per assistant response)
        if output_filetype != "svg" and image_bytes:
            # Providers may return JPEG even when PNG was requested. Preserve
            # the actual bytes and describe them accurately to safety/storage.
            _, output_mime = validate_raster_image(image_bytes)
            output_decision: PipelineDecision = await pipeline.validate_output(
                prompt=prompt,
                image_bytes=image_bytes,
                mime_type=output_mime,
                secrets_manager=task._secrets_manager,
            )
            if not output_decision.allowed and output_decision.rejection:
                tool_response = await _handle_safety_rejection(
                    task,
                    output_decision.rejection,
                    user_id=user_id,
                    prompt=prompt,
                    assistant_response_id=message_id,
                    source_embed_id=(
                        reference_image_embed_ids[0]
                        if reference_image_embed_ids
                        else None
                    ),
                    output_embed_id=embed_id,
                    provider=actual_model.split(" ")[0] if actual_model else None,
                    model=actual_model,
                    log_prefix=log_prefix,
                )
                await _emit_safety_rejection_embed(
                    task,
                    embed_id=embed_id,
                    user_id=user_id,
                    chat_id=chat_id,
                    message_id=message_id,
                    user_facing_message=tool_response.get(
                        "user_facing_message",
                        "This image couldn't be generated.",
                    ),
                    log_prefix=log_prefix,
                )
                return {
                    "embed_id": embed_id,
                    "status": "rejected",
                    **tool_response,
                }

        # 5. Get original dimensions (raster only; SVG is resolution-independent)
        original_width, original_height = 0, 0
        if output_filetype != "svg" and image_bytes:
            original_width, original_height = _get_image_dimensions(image_bytes)
            logger.info(
                f"{log_prefix} Original image dimensions: {original_width}x{original_height}"
            )
        else:
            logger.info(f"{log_prefix} SVG output — dimensions are resolution-independent")

        hashed_user_id = _hash_value(user_id)

        # 6. Process image into storage formats.
        # Prepare provenance metadata for XMP/C2PA labeling (raster only).
        # Uses actual_model (full provider reference) for accurate provenance tracking.
        labeling_metadata = {
            "prompt": prompt,
            "model": actual_model,
            "software": "OpenMates",
            "source": "OpenMates AI",
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

        if output_filetype == "svg":
            # SVG pipeline: store raw SVG as "original" + rasterized WEBP as "preview_webp".
            # No full_webp variant — the SVG is already infinitely scalable.
            logger.info(f"{log_prefix} Processing SVG for storage (original + preview_webp)...")
            processed_images = process_svg_for_storage(svg_bytes, metadata=labeling_metadata)  # type: ignore[arg-type]
        else:
            # Honor the user's PNG/JPG choice; existing postprocessing adds
            # provenance metadata and full/preview WEBP derivatives.
            logger.info(f"{log_prefix} Processing raster image into multiple formats...")
            processed_images = process_image_for_storage(
                _requested_raster_bytes(image_bytes, output_filetype),  # type: ignore[arg-type]
                metadata=labeling_metadata,
            )
        
        # 7. Hybrid Encryption Setup
        # Fetch user profile to get vault_key_id
        # get_user_profile returns (success, data, error_msg)
        result = await task._directus_service.get_user_profile(user_id)
        
        # Robust unpacking of (success, data, error_msg)
        success = False
        user_profile = None
        error_msg = "Unknown error"
        
        if isinstance(result, tuple):
            if len(result) >= 2:
                success = result[0]
                user_profile = result[1]
            if len(result) >= 3:
                error_msg = result[2]
        else:
            # Fallback if it somehow returned just the profile
            success = True
            user_profile = result
            
        if not success or not user_profile or not isinstance(user_profile, dict):
            raise Exception(f"User profile not found or invalid for {user_id}: {error_msg}")
            
        vault_key_id = user_profile.get("vault_key_id")
        if not vault_key_id:
            raise Exception(f"Vault key ID not found for user {user_id}")
            
        encrypted_variants = encrypt_media_variants(
            processed_images,
            write_version=load_media_write_version(),
        )

        # Wrap the local AES key using Vault
        aes_key_b64 = encrypted_variants.aes_key_b64
        encrypted_aes_key_vault, _ = await task._encryption_service.encrypt_with_user_key(
            aes_key_b64, vault_key_id
        )
        if not encrypted_aes_key_vault:
            raise Exception("Failed to wrap AES key with Vault")
            
        nonce_b64 = encrypted_variants.legacy_nonce_b64 or ""
        
        # 8. Encrypt and Upload each version to S3, collect file metadata
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        unique_id = uuid.uuid4().hex[:8]
        files_metadata = {}

        # Map internal format keys to public format names
        format_mapping = {
            "original": "original",
            "full_webp": "full",
            "preview_webp": "preview",
        }

        for format_key, content in processed_images.items():
            encrypted_payload = encrypted_variants.payloads[format_key]

            # Determine file extension:
            #   SVG originals  → .svg
            #   Raster originals use their actual encoded format
            #   WEBP variants  → .webp (full/preview)
            if format_key == "original":
                if output_filetype == "svg":
                    ext, stored_mime = "svg", "image/svg+xml"
                else:
                    ext, stored_mime = validate_raster_image(content)
            else:
                ext, stored_mime = validate_raster_image(content)
            file_key = f"{user_id}/{timestamp}_{unique_id}_{format_key}.{ext}"
            
            logger.info(f"{log_prefix} Uploading {format_key} version to S3 (chatfiles): {file_key}")
            
            # Upload to 'chatfiles' bucket
            upload_result = await task._s3_service.upload_file(
                bucket_key='chatfiles',
                file_key=file_key,
                content=encrypted_payload,
                content_type='application/octet-stream'
            )
            
            if not upload_result.get('url'):
                raise Exception(f"Failed to upload {format_key} image to S3")
            
            # Get dimensions for this format
            width, height = _get_image_dimensions(content)
            
            # Store file metadata with public format name.
            # "format" records the actual file type for the download endpoint to use
            # when setting Content-Type and the filename extension.
            public_format = format_mapping.get(format_key, format_key)
            files_metadata[public_format] = {
                "s3_key": file_key,
                "width": width,
                "height": height,
                "size_bytes": len(content),
                "format": ext,
                "mime_type": stored_mime,
                **encrypted_variants.metadata[format_key],
            }

        # 9. Prepare embed content for client-side storage
        # 
        # HYBRID ENCRYPTION MODEL:
        # - The embed CONTENT (below) is sent as PLAINTEXT TOON via WebSocket.
        #   The client encrypts it with the chat's master key before storing (standard flow).
        # - The AES key for S3 image decryption is included IN the embed content (plaintext).
        #   Since embed content is client-encrypted, the AES key is protected at rest.
        # - The Vault-wrapped AES key is stored separately for server-side LLM vision inference.
        #   The server can unwrap it via Vault to decrypt images when needed for vision LLMs.
        #
        # CLIENT FLOW:
        # 1. Client receives send_embed_data with plaintext TOON content
        # 2. Client encrypts content with chat master key and stores in IndexedDB
        # 3. To render image: client decodes TOON → extracts aes_key + s3_key →
        #    fetches encrypted blob from S3 → decrypts with AES-256-GCM → renders
        generated_at = datetime.now(timezone.utc).isoformat()
        
        # Build S3 base URL for the chatfiles bucket so the frontend can construct full URLs
        # Format: https://{bucket_name}.{region}.your-objectstorage.com
        chatfiles_bucket = get_bucket_name('chatfiles')
        s3_base_url = f"https://{chatfiles_bucket}.{task._s3_service.base_domain}"
        now_ts = int(datetime.now(timezone.utc).timestamp())
        original_content_type = files_metadata["original"]["mime_type"]
        output_filetype = files_metadata["original"]["format"]
        from backend.shared.python_utils.generated_media_graph import generated_image_filename
        filename = generated_image_filename(prompt, output_embed_id, output_filetype)
        provider = actual_model.split(" ", 1)[0]
        index_kwargs = dict(
            user_id=user_id,
            embed_id=output_embed_id,
            media_type="image",
            files_metadata=files_metadata,
            s3_base_url=s3_base_url,
            aes_key_b64=aes_key_b64,
            nonce_b64=nonce_b64,
            vault_wrapped_aes_key=encrypted_aes_key_vault,
            created_at=now_ts,
            content_hash_source=image_bytes if isinstance(image_bytes, bytes) else str(image_bytes).encode("utf-8"),
            original_filename=filename,
            content_type=original_content_type,
            log_prefix=log_prefix,
            provenance_metadata={
                "labeling": "xmp+c2pa" if output_filetype != "svg" else "account_metadata+preview_xmp_c2pa",
                "visual_watermark": False,
                "provider_watermarking": "provider-dependent",
            },
            existing_record_id=revision.upload_record_id if revision else None,
            retained_size_bytes=revision.retained_size_bytes if revision else 0,
        )
        # A revision re-points the image's one index row only after its version is sealed.
        if not revision and not await index_generated_asset(task, **index_kwargs):
            for meta in files_metadata.values():
                if isinstance(meta, dict) and meta.get("s3_key"):
                    try:
                        await task._s3_service.delete_file(bucket_key="chatfiles", file_key=meta["s3_key"])
                    except Exception as cleanup_exc:
                        logger.warning("%s Failed to clean generated image object: %s", log_prefix, cleanup_exc)
            raise RuntimeError("Failed to index generated image in account storage")
        
        embed_content = {
            "app_id": "images",
            "skill_id": skill_id,
            "type": "image",
            "status": "finished",
            "files": files_metadata,
            "s3_base_url": s3_base_url,                         # Base URL for constructing full S3 file URLs
            "aes_key": aes_key_b64,                             # Plaintext AES key for client-side S3 decryption
            "aes_nonce": nonce_b64,                             # GCM nonce shared across all image formats
            "vault_wrapped_aes_key": encrypted_aes_key_vault,  # For server-side LLM vision access
            "prompt": prompt,
            "model": display_model_id,
            "provider": provider,
            "filename": filename,
            "aspect_ratio": aspect_ratio,
            "output_filetype": output_filetype,                 # Actual "png", "jpg", "webp", or "svg"
            "generated_at": generated_at,
            # Input reference image embed IDs (non-empty only for image-to-image generation).
            # Used by the frontend to display thumbnails of the source images above the prompt.
            "input_embed_ids": reference_image_embed_ids or [],
            **(image_revision.revision_content_fields(revision) if revision else {}),
            # LLM vector author only: how many drafts were written and how the last one was judged.
            **(_vector_result_fields(authored, vector_engine) if authored else {}),
            "provenance": {
                "ai_generated": True,
                "labeling": "xmp+c2pa" if output_filetype != "svg" else "account_metadata+preview_xmp_c2pa",
                "visual_watermark": False,
                "provider_watermarking": "provider-dependent",
            },
        }
        
        # A script-made drawing is changed through its generator, which the chat stores
        # client-encrypted only: keep it server-readable for the processing window.
        if authored and authored.script:
            await remember_vector_script(task, embed_id=output_embed_id, script=authored.script, vault_key_id=vault_key_id)

        # 9b. Cache S3 file keys for server-side cleanup (S3 deletion on chat/embed deletion)
        # Since embed content is client-encrypted (zero-knowledge), the server can't extract
        # S3 keys from encrypted_content. We cache them here so that store_embed_handler
        # can persist them as server-accessible metadata on the Directus embed record.
        s3_file_keys = [
            {"bucket": "chatfiles", "key": meta["s3_key"]}
            for meta in files_metadata.values()
        ]
        
        if revision:
            s3_file_keys = await image_revision.cache_file_keys(task, target=revision, new_keys=s3_file_keys)
        try:
            client = await task._cache_service.client
            if client and not revision:
                s3_keys_cache_key = f"embed:{embed_id}:s3_file_keys"
                await client.set(s3_keys_cache_key, json.dumps(s3_file_keys), ex=3600)  # 1 hour TTL
                logger.info(f"{log_prefix} Cached {len(s3_file_keys)} S3 file keys for embed {embed_id}")
        except Exception as e:
            logger.warning(f"{log_prefix} Failed to cache S3 file keys for embed {embed_id}: {e}")
        
        # 5b. Charge credits (flat per-image fee) once everything fallible before
        # publication succeeded. For SVG, model_ref is "recraft/{model_id}" (step 4).
        if revision:
            # A change that lost a race, or an image without its stored marker, stays uncharged.
            await image_revision.assert_current_version(
                task._directus_service, revision, user_id=user_id, chat_id=str(chat_id),
            )
        charge_event_id = image_revision.billing_event_id(
            output_embed_id, revision.next_version if revision else 1, revision.change_id if revision else None,
        )
        credits_charged = await _charge_image_generation_credits(
            user_id=user_id, user_id_hash=hashed_user_id, app_id=app_id, skill_id=skill_id,
            model_ref=model_ref, chat_id=chat_id, message_id=message_id, log_prefix=log_prefix,
            team_id=arguments.get("team_id"), event_id=charge_event_id,
            metered_credits=metered_credits, metered_usage=metered_usage, strict=bool(revision),
        )

        # 10. Encode embed content as TOON for WebSocket delivery
        # TOON is the standard format used by the embed system for efficient encoding
        from toon_format import encode as toon_encode
        content_toon = toon_encode(embed_content)
        logger.info(f"{log_prefix} TOON-encoded embed content: {len(content_toon)} chars")
        
        # 11. Send embed data to client via WebSocket (standard client-encryption flow)
        # The client will:
        # 1. Receive plaintext TOON content
        # 2. Encrypt with chat master key (AES-256-GCM)
        # 3. Store encrypted in IndexedDB
        # 4. Send encrypted version back to server for Directus persistence
        # hashed_user_id already computed in step 5b (billing)
        
        # Use EmbedService.send_embed_data_to_client for standard WebSocket delivery
        from backend.core.api.app.services.embed_service import EmbedService
        embed_service = EmbedService(
            cache_service=task._cache_service,
            directus_service=task._directus_service,
            encryption_service=task._encryption_service
        )
        
        from backend.shared.python_utils.generated_media_graph import send_generated_media_child
        child_embed_id = output_embed_id
        if revision:
            try:
                await image_revision.publish_revision(
                    embed_service, target=revision, content=embed_content, s3_file_keys=s3_file_keys,
                    chat_id=str(chat_id), message_id=str(message_id), user_id=user_id,
                    user_id_hash=hashed_user_id, created_at=now_ts, log_prefix=log_prefix,
                )
            except RevisionRefused:
                # Refused before anything was sealed: give a Personal charge back.
                await image_revision.refund_refused_revision(
                    user_id=user_id, user_id_hash=hashed_user_id, credits=credits_charged,
                    app_id=app_id, skill_id=skill_id, event_id=charge_event_id,
                    team_id=arguments.get("team_id"), log_prefix=log_prefix,
                )
                raise
            await image_revision.finish_published_revision(
                task, target=revision, index=lambda: index_generated_asset(task, **index_kwargs), log_prefix=log_prefix,
            )
        else:
            await send_generated_media_child(
                embed_service,
                parent_embed_id=arguments.get("producer_embed_id") or embed_id,
                child_embed_id=child_embed_id,
                child_index=int(arguments.get("media_child_index") or 0),
                content=embed_content,
                chat_id=chat_id, message_id=message_id, user_id=user_id,
                user_id_hash=hashed_user_id, created_at=now_ts, log_prefix=log_prefix,
            )
        
        # 12. NOTE: embed_update event is NO LONGER published here.
        # The send_embed_data_to_client() call above (step 11) already delivers all content
        # the frontend needs (plaintext TOON for client-side encryption, status, metadata).
        # Publishing an additional embed_update causes the frontend to process the same embed
        # twice, resulting in "DUPLICATE DETECTED" warnings and redundant work.
        # The frontend's handleSendEmbedDataImpl handles the processing -> finished transition.

        # 13. Prepare result for API response
        # This is what gets returned via task polling and REST API
        rest_files_metadata = {
            format_name: {
                "width": meta["width"],
                "height": meta["height"],
                "size_bytes": meta["size_bytes"],
                "format": meta["format"],
                "mime_type": meta.get("mime_type") or _content_type_for_image_format(meta["format"]),
                "download_url": build_download_url(
                    base_url=PUBLIC_API_BASE_URL,
                    asset_id=embed_id,
                    variant=format_name,
                    token=create_download_token(asset_id=embed_id, user_id=user_id, variant=format_name),
                ),
                "download_expires_at": int(datetime.now(timezone.utc).timestamp()) + 900,
            }
            for format_name, meta in files_metadata.items()
        }
        result_data = {
            "embed_id": output_embed_id,
            "child_embed_id": child_embed_id,
            "child_embed_ids": [child_embed_id],
            "embed_ref": f"generated-images-{child_embed_id.replace('-', '')[:12]}",
            "type": "image",
            "status": "finished",
            "files": rest_files_metadata if external_request else {
                format_name: {
                    "width": meta["width"],
                    "height": meta["height"],
                    "size_bytes": meta["size_bytes"],
                    "format": meta["format"],
                }
                for format_name, meta in files_metadata.items()
            },
            "prompt": prompt,
            "model": display_model_id,
            "provider": provider,
            "filename": filename,
            "aspect_ratio": aspect_ratio,
            "output_filetype": output_filetype,
            "generated_at": generated_at,
            # Tells the chat model how a vector drawing was made and which requirements it still misses.
            **({key: value for key, value in _vector_result_fields(authored, vector_engine).items()
                if key != "vector_script"} if authored else {}),
            **({"team_id": arguments["team_id"]} if arguments.get("team_id") else {}),
            **(image_revision.revision_result_fields(revision) if revision else {}),
        }
        
        logger.info(f"{log_prefix} Image generation task completed successfully. Embed ID: {output_embed_id}")
        return result_data

    except RequiredRecoveryOutputError:
        raise
    except Exception as e:
        logger.error(f"{log_prefix} Image generation task failed: {e}", exc_info=True)
        if arguments.get("media_batch"):
            raise
        
        # Update the embed status to "error" so the frontend gets notified
        # and the user sees a failure message instead of a perpetual loading state.
        # We need embed_id, user_id, chat_id, message_id from the arguments (extracted in step 2-3).
        try:
            _embed_id = arguments.get("embed_id")
            _user_id = arguments.get("user_id")
            _chat_id = arguments.get("chat_id")
            _message_id = arguments.get("message_id")
            
            if _embed_id and _user_id and _chat_id and _message_id:
                from toon_format import encode as toon_encode
                from backend.core.api.app.services.embed_service import EmbedService
                
                _hashed_user_id = _hash_value(_user_id)
                
                # Build a concise, user-facing error message
                error_str = str(e)
                if isinstance(e, ReferenceImageUnavailable):
                    user_error_message = REFERENCE_UNAVAILABLE_MESSAGE
                elif isinstance(e, image_revision.RevisionNotSupported):
                    user_error_message = "This image cannot get a new version yet. Nothing was charged; please try again shortly."
                elif isinstance(e, image_revision.RevisionPreconditionFailed):
                    user_error_message = "The image changed while this change was drawn. Nothing was charged; please try again."
                elif "500 INTERNAL" in error_str or "ServerError" in error_str:
                    user_error_message = "The image generation provider is temporarily unavailable. Please try again."
                elif "overloaded" in error_str.lower() or "429" in error_str or "rate" in error_str.lower():
                    user_error_message = "The image generation service is currently overloaded. Please try again in a moment."
                elif "timeout" in error_str.lower() or "timed out" in error_str.lower():
                    user_error_message = "Image generation timed out. Please try again."
                else:
                    user_error_message = "Image generation failed. Please try again."
                
                error_content = {
                    "app_id": app_id,
                    "skill_id": skill_id,
                    "type": "image",
                    "status": "error",
                    "error": user_error_message,
                    "prompt": arguments.get("prompt", ""),
                    "model": arguments.get("full_model_reference", "unknown"),
                }
                
                content_toon = toon_encode(error_content)
                now_ts = int(datetime.now(timezone.utc).timestamp())
                
                # Ensure services are initialized (they may already be from the try block)
                try:
                    await task.initialize_core_services()
                except Exception:
                    pass  # Services may already be initialized
                
                embed_service = EmbedService(
                    cache_service=task._cache_service,  # type: ignore[arg-type]
                    directus_service=task._directus_service,  # type: ignore[arg-type]
                    encryption_service=task._encryption_service  # type: ignore[arg-type]
                )
                
                await embed_service.send_embed_data_to_client(
                    embed_id=_embed_id,
                    embed_type="app_skill_use",
                    content_toon=content_toon,
                    chat_id=str(_chat_id),
                    message_id=str(_message_id),
                    user_id=_user_id,
                    user_id_hash=_hashed_user_id,
                    status="error",
                    encryption_mode="client",
                    created_at=now_ts,
                    updated_at=now_ts,
                    log_prefix=f"{log_prefix} [ERROR_EMBED]",
                    check_cache_status=False
                )
                
                logger.info(f"{log_prefix} Sent error embed status for embed {_embed_id}: {user_error_message}")
            else:
                logger.warning(
                    f"{log_prefix} Cannot send error embed status - missing required arguments: "
                    f"embed_id={bool(_embed_id)}, user_id={bool(_user_id)}, "
                    f"chat_id={bool(_chat_id)}, message_id={bool(_message_id)}"
                )
        except Exception as embed_error:
            # Error notification is best-effort - don't mask the original exception
            logger.error(f"{log_prefix} Failed to send error embed status: {embed_error}", exc_info=True)
        
        # Re-raising allows Celery to mark the task as FAILED
        raise
    finally:
        # CRITICAL: Always cleanup services to close httpx client and prevent event loop issues
        await task.cleanup_services()


async def _encrypt_type_with_vault(task: BaseServiceTask, embed_type: str, vault_key_id: str) -> str:
    """
    Encrypt the embed type using Vault.
    
    For server-generated embeds, the type is Vault-encrypted rather than client-encrypted.
    The download endpoint knows to decrypt with Vault for these embeds.
    """
    encrypted_type, _ = await task._encryption_service.encrypt_with_user_key(
        embed_type, vault_key_id
    )
    if not encrypted_type:
        raise Exception("Failed to encrypt embed type with Vault")
    return encrypted_type
