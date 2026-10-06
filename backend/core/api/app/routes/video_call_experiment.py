"""First-party, ephemeral Gemini Live + fal video-call experiment.

This is a first-party client WebSocket, not a public developer API. Session
cookies (or user-bound short-lived WS tokens) and Origin are checked before any
provider connection. Audio, frames, transcripts, and generated clips stay in
memory for this call only; this route has no recording or storage path.
"""

from __future__ import annotations

import asyncio
import base64
from datetime import datetime, timezone
from decimal import Decimal, ROUND_CEILING
import hashlib
import json
import logging
import re
import time
import traceback
import uuid
from typing import Any

import aiohttp
import httpx
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect, status

from backend.core.api.app.routes.audio_realtime import _browser_request_is_allowed
from backend.core.api.app.routes.auth_ws import get_current_user_ws
from backend.core.api.app.utils.server_mode import is_payment_enabled
from backend.shared.providers.fal.h3_turbo import FalCompletedMediaError, FalJob, await_clip, cancel_clip, submit_clip

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/experiment")

GEMINI_URL = "wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent"
GEMINI_MODEL = "gemini-3.8-live"
MAX_SECONDS = 120
IDLE_VIDEO_SECONDS = 10
LOCK_TTL_SECONDS = MAX_SECONDS + 120
MAX_AUDIO_CHUNK = 128 * 1024
MAX_FRAME = 256 * 1024
MAX_PROMPT = 1800
USD_PER_CREDIT = Decimal("0.001")
MARKUP = Decimal("1.2")
INPUT_RATES = {"TEXT": Decimal("0.75"), "AUDIO": Decimal("3"), "IMAGE": Decimal("1"), "VIDEO": Decimal("1")}
OUTPUT_RATES = {"TEXT": Decimal("4.5"), "AUDIO": Decimal("12")}
PROMO_END = datetime(2026, 10, 16, tzinfo=timezone.utc)
VIDEO_RATE_PROMO = Decimal("0.015")
VIDEO_RATE_NORMAL = Decimal("0.025")
VIDEO_REQUEST_SECONDS = Decimal("5")
VIDEO_RESERVE_SECONDS = Decimal("5.7")
MIN_VOICE_HEADROOM = 20
FORBIDDEN_VIDEO_LANGUAGE = re.compile(r"\b(?:speak|speaks|says|dialogue|voiceover|lip[ -]?sync|talk|talking|captions?|subtitles?)\b|<d>", re.I)


def _video_rate(now: datetime | None = None) -> Decimal:
    return VIDEO_RATE_PROMO if (now or datetime.now(timezone.utc)) < PROMO_END else VIDEO_RATE_NORMAL


def _credits_for(cost_usd: Decimal) -> int:
    return int((cost_usd * MARKUP / USD_PER_CREDIT).to_integral_value(rounding=ROUND_CEILING))


def _decode_media(value: Any, *, max_bytes: int, jpeg: bool = False) -> bytes:
    if not isinstance(value, str) or len(value) > max_bytes * 4 // 3 + 8:
        raise ValueError("Media chunk size is invalid")
    try:
        data = base64.b64decode(value, validate=True)
    except (ValueError, base64.binascii.Error) as exc:
        raise ValueError("Media encoding is invalid") from exc
    if not data or len(data) > max_bytes or (jpeg and not (data.startswith(b"\xff\xd8") and data.endswith(b"\xff\xd9"))):
        raise ValueError("Media chunk is invalid")
    return data


class UsageLedger:
    """Aggregate fractional provider cost; round once per cumulative balance."""

    def __init__(self) -> None:
        self.gemini_cost = Decimal(0)
        self.video_cost = Decimal(0)
        self.prompt_tokens = 0
        self.response_tokens = 0
        self.context_tokens = 0
        self.tool_use_prompt_tokens = 0
        self.tool_use_modalities: dict[str, int] = {}
        self.video_seconds = Decimal(0)
        self.video_estimated_seconds = Decimal(0)
        self.charged = 0
        self.checkpoint = 0
        self.pending_usage: dict[str, Any] | None = None

    @property
    def cost(self) -> Decimal:
        return self.gemini_cost + self.video_cost

    @property
    def accrued_credits(self) -> Decimal:
        return self.cost * MARKUP / USD_PER_CREDIT

    def stage_gemini(self, usage: dict[str, Any]) -> None:
        # Live may send interim usage before the final message for a turn.
        # Keep the largest report until turnComplete, then count that turn once.
        if not self.pending_usage or int(usage.get("totalTokenCount") or 0) >= int(self.pending_usage.get("totalTokenCount") or 0):
            self.pending_usage = usage

    def commit_gemini_turn(self) -> bool:
        usage = self.pending_usage
        self.pending_usage = None
        if not usage:
            return False
        prompt_details = usage.get("promptTokensDetails")
        response_details = usage.get("responseTokensDetails")
        prompt_tokens = int(usage.get("promptTokenCount") or 0)
        response_tokens = int(usage.get("responseTokenCount") or 0)
        tool_use_prompt_tokens = int(usage.get("toolUsePromptTokenCount") or 0)
        thoughts = int(usage.get("thoughtsTokenCount") or 0)
        if min(prompt_tokens, response_tokens, tool_use_prompt_tokens, thoughts) < 0:
            raise ValueError("Gemini reported negative usage")
        # Proto JSON omits empty repeated fields. Tool-only turns can have no
        # output tokens and therefore no responseTokensDetails at all. Only a
        # zero-token side may omit its breakdown; positive usage must remain
        # attributable to its modality before we can charge it correctly.
        if prompt_details is None and prompt_tokens == 0:
            prompt_details = []
        if response_details is None and response_tokens == 0:
            response_details = []
        if (
            not isinstance(prompt_details, list) or not isinstance(response_details, list)
            or (prompt_tokens > 0 and not prompt_details)
            or (response_tokens > 0 and not response_details)
        ):
            raise ValueError("Gemini did not provide modality-level usage")
        turn_modalities: dict[str, int] = {}
        turn_cost = Decimal(0)
        # Google exposes tool-use prompt tokens separately but does not state
        # whether they are already in promptTokensDetails. Retain them for
        # reconciliation; charging them again could double-bill a tool turn.
        for item in usage.get("toolUsePromptTokensDetails") or []:
            if isinstance(item, dict) and isinstance(item.get("modality"), str):
                modality = item["modality"].upper()
                count = int(item.get("tokenCount") or 0)
                if count < 0:
                    raise ValueError("Gemini reported negative tool usage")
                turn_modalities[modality] = turn_modalities.get(modality, 0) + count
        # Prompt tokens on each turn include the re-billed conversation context.
        for details, rates in ((prompt_details, INPUT_RATES), (response_details, OUTPUT_RATES)):
            for item in details:
                if not isinstance(item, dict):
                    raise ValueError("Gemini modality usage is invalid")
                modality = str(item.get("modality") or "").upper()
                count = int(item.get("tokenCount") or 0)
                if modality not in rates or count < 0:
                    raise ValueError("Gemini reported unknown modality usage")
                turn_cost += Decimal(count) * rates[modality] / Decimal(1_000_000)
        # Thinking tokens can be outside responseTokensDetails; output text rate
        # includes them. 3.8 Live normally emits no separate thought stream.
        if thoughts > 0:
            turn_cost += Decimal(thoughts) * OUTPUT_RATES["TEXT"] / Decimal(1_000_000)
        self.prompt_tokens += prompt_tokens
        self.response_tokens += response_tokens + thoughts
        self.tool_use_prompt_tokens += tool_use_prompt_tokens
        self.context_tokens += prompt_tokens
        for modality, count in turn_modalities.items():
            self.tool_use_modalities[modality] = self.tool_use_modalities.get(modality, 0) + count
        self.gemini_cost += turn_cost
        return True

    def add_accepted_video(self, seconds: Decimal, *, estimated: bool = False) -> None:
        self.video_seconds += seconds
        self.video_cost += seconds * _video_rate()
        if estimated:
            self.video_estimated_seconds += seconds

    def adjust_video_duration(self, delta: Decimal) -> None:
        self.video_seconds += delta
        self.video_cost += delta * _video_rate()

    def view(self, elapsed: float) -> dict[str, Any]:
        video_rate = _video_rate()
        return {
            "type": "usage",
            "elapsed_seconds": round(elapsed, 1),
            "credits_accrued": round(float(self.accrued_credits), 3),
            "credits_charged": self.charged,
            "audio_credits": round(float(self.gemini_cost * MARKUP / USD_PER_CREDIT), 3),
            "video_credits": round(float(self.video_cost * MARKUP / USD_PER_CREDIT), 3),
            "gemini_input_tokens": self.prompt_tokens,
            "gemini_output_tokens": self.response_tokens,
            "gemini_context_tokens": self.context_tokens,
            "gemini_tool_use_prompt_tokens": self.tool_use_prompt_tokens,
            "h3_generated_seconds": round(float(self.video_seconds), 3),
            "h3_estimated_seconds": round(float(self.video_estimated_seconds), 3),
            "audio_credits_per_minute": 27.6,
            "video_credits_per_minute": float(video_rate * Decimal(60) * MARKUP / USD_PER_CREDIT),
        }


async def _authoritative_credits(websocket: WebSocket, user_id: str) -> int:
    """Cache projection with encrypted Directus fallback; fail admission closed."""
    cache = websocket.app.state.cache_service
    projection = await cache.get_billing_projection(user_id)
    if projection is not None and isinstance(projection.get("credits"), int):
        return projection["credits"]
    rows = await websocket.app.state.directus_service.get_items(
        "directus_users",
        params={"filter[id][_eq]": user_id, "fields": "id,vault_key_id,encrypted_credit_balance", "limit": 1},
        no_cache=True,
        admin_required=True,
        raise_on_error=True,
    )
    if not isinstance(rows, list) or not rows:
        raise RuntimeError("Billing balance unavailable")
    key_id = rows[0].get("vault_key_id")
    encrypted = rows[0].get("encrypted_credit_balance")
    if not isinstance(key_id, str) or not isinstance(encrypted, str):
        raise RuntimeError("Billing balance unavailable")
    plaintext = await websocket.app.state.encryption_service.decrypt_with_user_key(encrypted, key_id)
    if plaintext is None:
        raise RuntimeError("Billing balance unavailable")
    credits = int(plaintext)
    await cache.set_billing_projection(
        user_id, credits=credits, encrypted_balance=encrypted, vault_key_id=key_id,
    )
    return credits


async def _session_still_valid(websocket: WebSocket, auth_data: dict[str, Any]) -> bool:
    """Recheck the durable session authority during an open paid connection."""
    from backend.core.api.app.services.pair_session_deadline import get_pair_deadline_hash
    from backend.core.api.app.services.session_security_state import get_session_state_cached

    now = int(time.time())
    for deadline in (auth_data.get("session_expires_at"), auth_data.get("pair_expires_at")):
        if deadline is not None:
            try:
                if int(deadline) <= now:
                    return False
            except (TypeError, ValueError):
                return False
    digest = auth_data.get("session_hash")
    if not isinstance(digest, str) or not digest:
        return False
    try:
        state = await get_session_state_cached(
            websocket.app.state.directus_service,
            websocket.app.state.cache_service,
            digest,
            user_id=auth_data["user_id"],
            allow_risk=False,
        )
        if not state:
            return False
        if auth_data.get("pair_expires_at") is not None:
            pair_deadline = await get_pair_deadline_hash(
                websocket.app.state.directus_service,
                websocket.app.state.cache_service,
                digest,
            )
            if pair_deadline is None or pair_deadline <= now:
                return False
        return True
    except Exception:
        return False


async def _acquire_lock(websocket: WebSocket, user_hash: str) -> tuple[Any, str, str]:
    key = f"experiment:videocall:active:{user_hash}"
    token = uuid.uuid4().hex
    client = await websocket.app.state.cache_service.client
    if not client or not await client.set(key, token, nx=True, ex=LOCK_TTL_SECONDS):
        raise RuntimeError("A call is already active or admission is unavailable")
    return client, key, token


async def _release_lock(client: Any, key: str, token: str) -> None:
    try:
        value = await client.get(key)
        if (value.decode() if isinstance(value, bytes) else value) == token:
            await client.delete(key)
    except Exception:
        logger.warning("Video-call lock release failed", exc_info=True)


async def _finish_accepted_job(task: asyncio.Task[None]) -> None:
    """Preserve an accepted job's settlement through request cancellation."""
    cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
            asyncio.current_task().uncancel()
    await task
    if cancelled:
        raise asyncio.CancelledError


def _billing(websocket: WebSocket) -> Any:
    # BillingService imports the wider task graph; defer it for route import.
    from backend.core.api.app.services.billing_service import BillingService

    return BillingService(
        websocket.app.state.cache_service,
        websocket.app.state.directus_service,
        websocket.app.state.encryption_service,
        websocket.app.state.server_stats_service,
    )


async def _charge(websocket: WebSocket, ledger: UsageLedger, *, user_id: str, user_hash: str, call_id: str) -> None:
    due = _credits_for(ledger.cost) - ledger.charged
    if due <= 0:
        return
    result = await _billing(websocket).charge_user_credits(
        user_id=user_id,
        user_id_hash=user_hash,
        credits_to_deduct=due,
        app_id="ai",
        skill_id="video_call",
        idempotency_key=f"video-call:{call_id}:{ledger.checkpoint + 1}",
        require_full_charge=True,
        usage_details={
            "usage_type": "video_call_experiment",
            "model": GEMINI_MODEL,
            "video_model": "minimax/h3-max-turbo/image-to-video",
            "provider_cost_usd": float(ledger.cost),
            "charged_credits": due,
            "gemini_input_tokens": ledger.prompt_tokens,
            "gemini_output_tokens": ledger.response_tokens,
            "gemini_tool_use_prompt_tokens": ledger.tool_use_prompt_tokens,
            "gemini_tool_use_modalities": ledger.tool_use_modalities,
            "h3_generated_seconds": float(ledger.video_seconds),
            "h3_estimated_seconds": float(ledger.video_estimated_seconds),
        },
    )
    ledger.checkpoint += 1
    ledger.charged += int(result.get("charged_credits", due))


async def _settle_final_usage(websocket: WebSocket, ledger: UsageLedger, *, user_id: str, user_hash: str, call_id: str) -> None:
    try:
        ledger.commit_gemini_turn()
    except Exception:
        logger.exception("Video-call final Gemini usage was invalid")
    try:
        await _charge(websocket, ledger, user_id=user_id, user_hash=user_hash, call_id=call_id)
    except Exception:
        logger.exception("Video-call final settlement failed")


def _decode_gemini_event(message: aiohttp.WSMessage) -> dict[str, Any]:
    """Google Live sends UTF-8 JSON in binary as well as text frames."""
    if message.type not in (aiohttp.WSMsgType.TEXT, aiohttp.WSMsgType.BINARY):
        # Frame metadata is safe to log; provider payloads can contain audio,
        # transcripts or credentials and must never reach these diagnostics.
        close_code = message.data if message.type == aiohttp.WSMsgType.CLOSE and isinstance(message.data, int) else None
        logger.warning("Gemini Live ended with frame=%s close_code=%s", message.type.name, close_code)
        raise RuntimeError("Gemini Live disconnected")
    event = json.loads(message.data)
    if not isinstance(event, dict):
        raise ValueError("Invalid Gemini Live event")
    return event


def _gemini_setup() -> dict[str, Any]:
    return {
        "setup": {
            "model": f"models/{GEMINI_MODEL}",
            "generationConfig": {"responseModalities": ["AUDIO"], "mediaResolution": "MEDIA_RESOLUTION_LOW"},
            "systemInstruction": {"parts": [{"text": (
                "You are a warm live voice companion. Speak naturally and concisely. "
                "Use generate_visual_clip only for a concrete visual scene the user wants to see. "
                "You may issue that visual tool while speaking; do not wait for it. "
                "The video prompt must describe visual motion and ambient sound only: no spoken "
                "dialogue, lip sync, voiceover, captions, or music. Your own live voice supplies speech. "
                "Never include URLs or private data in a video prompt. If visuals stop, continue voice." 
            )}]},
            "tools": [{"functionDeclarations": [{
                "name": "generate_visual_clip",
                "description": "Asynchronously create one 5-second scene matching the user's current visual request; voice continues.",
                "behavior": "NON_BLOCKING",
                "parameters": {"type": "OBJECT", "properties": {"prompt": {"type": "STRING", "description": "Visual action and ambience only. No speech or dialogue."}}, "required": ["prompt"]},
            }]}],
            "inputAudioTranscription": {},
            "outputAudioTranscription": {},
            "contextWindowCompression": {"triggerTokens": 8000, "slidingWindow": {"targetTokens": 4000}},
        }
    }


def _tool_response(call: dict[str, Any], result: str) -> dict[str, Any]:
    return {"toolResponse": {"functionResponses": [{
        "id": call.get("id"), "name": "generate_visual_clip",
        "response": {"result": result, "scheduling": "SILENT"},
    }]}}


@router.websocket("/videocall")
async def video_call(websocket: WebSocket, auth_data: dict[str, Any] | None = Depends(get_current_user_ws)) -> None:
    if auth_data is None:
        return
    if not await _browser_request_is_allowed(websocket, auth_data):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Origin not allowed")
        return
    user_id = auth_data["user_id"]
    user_hash = hashlib.sha256(user_id.encode()).hexdigest()
    lock_client: Any = None
    lock_key = lock_token = ""
    if is_payment_enabled():
        try:
            if await _authoritative_credits(websocket, user_id) < MIN_VOICE_HEADROOM:
                raise RuntimeError("Insufficient credits")
        except Exception:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Credit admission unavailable")
            return
    try:
        lock_client, lock_key, lock_token = await _acquire_lock(websocket, user_hash)
    except Exception:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Call admission unavailable")
        return

    try:
        await websocket.accept()
    except Exception:
        await _release_lock(lock_client, lock_key, lock_token)
        raise
    started = time.monotonic()
    call_id = uuid.uuid4().hex
    ledger = UsageLedger()
    last_visual_instruction: float | None = None
    visuals_allowed = True
    billing_fault = False
    active_video: asyncio.Task[None] | None = None
    active_job: FalJob | None = None
    visual_prompt: str | None = None
    latest_tool_call_id: str | None = None
    segment_epoch = 0
    continuation_jpeg: bytes | None = None
    continuation_for_clip: str | None = None
    latest_clip_id: str | None = None
    video_serial = 0
    audio_bytes = 0
    last_frame_at = 0.0
    provider_send_lock = asyncio.Lock()
    socket_send_lock = asyncio.Lock()
    billing_lock = asyncio.Lock()
    disconnected = False

    async def send(event: dict[str, Any]) -> None:
        if not disconnected:
            async with socket_send_lock:
                await websocket.send_json(event)

    async def send_provider(provider: aiohttp.ClientWebSocketResponse, event: dict[str, Any]) -> None:
        async with provider_send_lock:
            await provider.send_json(event)

    async def usage_update() -> None:
        await send(ledger.view(time.monotonic() - started))

    async def settle() -> None:
        async with billing_lock:
            await _charge(websocket, ledger, user_id=user_id, user_hash=user_hash, call_id=call_id)
        await usage_update()

    async def require_headroom(credits: int) -> None:
        pending = max(0, _credits_for(ledger.cost) - ledger.charged)
        if is_payment_enabled() and await _authoritative_credits(websocket, user_id) < credits + pending:
            raise RuntimeError("Insufficient credits")

    try:
        google_key, fal_key = await asyncio.gather(
            websocket.app.state.secrets_manager.get_secret("kv/data/providers/google_ai_studio", "api_key"),
            websocket.app.state.secrets_manager.get_secret("kv/data/providers/fal", "api_key"),
        )
        if not google_key or not fal_key:
            raise RuntimeError("Video call is unavailable")
        async with httpx.AsyncClient(timeout=httpx.Timeout(20, read=80), follow_redirects=False) as fal_client:
            timeout = aiohttp.ClientTimeout(total=None, sock_connect=10)
            async with aiohttp.ClientSession(timeout=timeout) as http_session:
                async with http_session.ws_connect(
                    GEMINI_URL, headers={"x-goog-api-key": google_key}, heartbeat=15,
                    max_msg_size=3 * 1024 * 1024,
                ) as gemini:
                    await send_provider(gemini, _gemini_setup())
                    setup_reply = _decode_gemini_event(await asyncio.wait_for(gemini.receive(), timeout=10))
                    if "setupComplete" not in setup_reply:
                        raise RuntimeError("Gemini Live setup failed")
                    started = time.monotonic()
                    await send({
                        "type": "ready", "model": GEMINI_MODEL,
                        "input_sample_rate": 16000, "output_sample_rate": 24000,
                        "max_duration_seconds": MAX_SECONDS,
                        "audio_credits_per_minute": 27.6,
                        "video_credits_per_minute": float(_video_rate() * Decimal(60) * MARKUP / USD_PER_CREDIT),
                    })
                    last_auth_check = 0.0

                    async def visual_chain(epoch: int) -> None:
                        nonlocal active_job, continuation_jpeg, continuation_for_clip, latest_clip_id, video_serial, billing_fault, visual_prompt
                        # A new Gemini visual instruction replaces visual_prompt
                        # while a clip is generating. The next iteration uses it.
                        while (
                            visuals_allowed and epoch == segment_epoch
                            and last_visual_instruction is not None
                            and time.monotonic() - last_visual_instruction < IDLE_VIDEO_SECONDS
                            and time.monotonic() - started < MAX_SECONDS
                        ):
                            job: FalJob | None = None
                            try:
                                await require_headroom(_credits_for(_video_rate() * VIDEO_RESERVE_SECONDS) + MIN_VOICE_HEADROOM)
                                prompt = visual_prompt
                                if not prompt or epoch != segment_epoch or not visuals_allowed:
                                    return
                                # Server-extracted final frame is preferred. A
                                # matching browser frame is a bounded fallback.
                                image = continuation_jpeg if continuation_for_clip == latest_clip_id else None
                                continuation_jpeg = None
                                continuation_for_clip = None
                                video_serial += 1
                                clip_id = str(video_serial)
                                safe_prompt = "Visual motion and ambient scene sound only. No dialogue, speech, lip sync, captions, voiceover, or music. " + prompt
                                job = await submit_clip(fal_client, key=fal_key, prompt=safe_prompt, image_jpeg=image)
                                active_job = job
                                if epoch != segment_epoch or not visuals_allowed:
                                    await cancel_clip(fal_client, key=fal_key, job=job)
                                else:
                                    await send({"type": "video.queued", "clip_id": clip_id})
                                clip = await await_clip(fal_client, key=fal_key, job=job)
                                # Failed/cancelled jobs have no reported generated
                                # seconds. Completed output is billed once, even
                                # when the user stopped during processing.
                                measured = clip.reported_duration or clip.measured_duration
                                duration = Decimal(str(measured)) if measured and 0 < measured < 30 else VIDEO_REQUEST_SECONDS
                                ledger.add_accepted_video(duration, estimated=measured is None)
                                try:
                                    await settle()
                                except Exception:
                                    billing_fault = True
                                    raise
                                if epoch != segment_epoch or not visuals_allowed or time.monotonic() - started >= MAX_SECONDS:
                                    return
                                if last_visual_instruction is None or time.monotonic() - last_visual_instruction >= IDLE_VIDEO_SECONDS:
                                    return
                                latest_clip_id = clip_id
                                # This is the generated last frame, not the
                                # frame sampled for Gemini playback feedback.
                                continuation_jpeg = clip.last_frame_jpeg
                                continuation_for_clip = clip_id if clip.last_frame_jpeg else None
                                await send({
                                    "type": "video.ready", "clip_id": clip_id,
                                    "data": base64.b64encode(clip.data).decode("ascii"),
                                    "duration_seconds": float(duration),
                                    "duration_estimated": measured is None,
                                })
                                if continuation_jpeg is None:
                                    # Browser extracts this same clip's final
                                    # frame before playback finishes.
                                    for _ in range(5):
                                        if continuation_for_clip == clip_id or epoch != segment_epoch:
                                            break
                                        await asyncio.sleep(0.2)
                                    if continuation_for_clip != clip_id:
                                        if epoch == segment_epoch:
                                            visual_prompt = None
                                        return
                                # Fal can finish faster than playback. Schedule
                                # the next job near this clip's end so at most
                                # the current clip and one upcoming clip exist.
                                await asyncio.sleep(max(0.0, float(duration) - 1.0))
                            except FalCompletedMediaError as exc:
                                duration = Decimal(str(exc.reported_duration)) if exc.reported_duration else VIDEO_REQUEST_SECONDS
                                ledger.add_accepted_video(duration, estimated=exc.reported_duration is None)
                                try:
                                    await settle()
                                except Exception:
                                    billing_fault = True
                                    logger.exception("Completed fal job billing failed")
                                if epoch == segment_epoch:
                                    visual_prompt = None
                                if epoch == segment_epoch and visuals_allowed:
                                    try:
                                        await send({"type": "error", "code": "video_unavailable", "message": "Visual generation completed, but the clip could not be delivered. Voice can continue."})
                                    except Exception:
                                        pass
                                return
                            except Exception as exc:
                                logger.warning("Video generation ended with %s", type(exc).__name__)
                                if epoch == segment_epoch:
                                    visual_prompt = None
                                if epoch == segment_epoch and visuals_allowed:
                                    try:
                                        await send({"type": "error", "code": "video_unavailable", "message": "Visual generation failed; voice can continue."})
                                    except Exception:
                                        pass
                                return  # no transparent retry of a paid request
                            finally:
                                active_job = None

                    client_receive = asyncio.create_task(websocket.receive_text())
                    provider_receive = asyncio.create_task(gemini.receive())
                    try:
                        while True:
                            now = time.monotonic()
                            if billing_fault:
                                raise RuntimeError("Video-call billing could not settle")
                            if now - last_auth_check >= 5:
                                if not await _session_still_valid(websocket, auth_data):
                                    raise RuntimeError("Session expired or revoked")
                                last_auth_check = now
                            if now - started >= MAX_SECONDS:
                                await send({"type": "ended", "reason": "time_limit"})
                                break
                            if visuals_allowed and last_visual_instruction is not None and now - last_visual_instruction >= IDLE_VIDEO_SECONDS:
                                visuals_allowed = False
                                segment_epoch += 1
                                visual_prompt = None
                                latest_tool_call_id = None
                                if active_job is not None:
                                    await cancel_clip(fal_client, key=fal_key, job=active_job)
                                await send({"type": "video.stopped", "reason": "idle"})
                            if visuals_allowed and visual_prompt and (active_video is None or active_video.done()):
                                # A stopped segment may still be settling when
                                # the user explicitly re-enables visuals.
                                active_video = asyncio.create_task(visual_chain(segment_epoch))
                            # Fail closed as projected balance is consumed. This
                            # catches quiet/long turns before another fal submit.
                            await require_headroom(MIN_VOICE_HEADROOM)
                            done, _ = await asyncio.wait(
                                {client_receive, provider_receive}, timeout=1,
                                return_when=asyncio.FIRST_COMPLETED,
                            )
                            if client_receive in done:
                                incoming = json.loads(client_receive.result())
                                if not isinstance(incoming, dict):
                                    raise ValueError("Invalid call event")
                                event_type = incoming.get("type")
                                if event_type == "mic_audio":
                                    data = _decode_media(incoming.get("data"), max_bytes=MAX_AUDIO_CHUNK)
                                    if len(data) % 2:
                                        raise ValueError("PCM audio is invalid")
                                    audio_bytes += len(data)
                                    if audio_bytes > (time.monotonic() - started + 2) * 32000:
                                        raise ValueError("Audio stream exceeds real-time rate")
                                    await send_provider(gemini, {"realtimeInput": {"audio": {"data": incoming["data"], "mimeType": "audio/pcm;rate=16000"}}})
                                elif event_type == "video_frame":
                                    if not visuals_allowed or latest_clip_id is None:
                                        client_receive = asyncio.create_task(websocket.receive_text())
                                        continue
                                    frame_at = time.monotonic()
                                    if frame_at - last_frame_at < 0.9:
                                        raise ValueError("Video frames exceed allowed rate")
                                    data = _decode_media(incoming.get("data"), max_bytes=MAX_FRAME, jpeg=True)
                                    last_frame_at = frame_at
                                    await send_provider(gemini, {"realtimeInput": {"video": {"data": base64.b64encode(data).decode("ascii"), "mimeType": "image/jpeg"}}})
                                elif event_type == "continuation_frame":
                                    if visuals_allowed and continuation_jpeg is None and incoming.get("source") == "continuation" and incoming.get("clip_id") == latest_clip_id:
                                        continuation_jpeg = _decode_media(incoming.get("data"), max_bytes=MAX_FRAME, jpeg=True)
                                        continuation_for_clip = latest_clip_id
                                elif event_type == "stop_visuals":
                                    visuals_allowed = False
                                    segment_epoch += 1
                                    visual_prompt = None
                                    latest_tool_call_id = None
                                    continuation_jpeg = None
                                    continuation_for_clip = None
                                    latest_clip_id = None
                                    if active_job is not None:
                                        await cancel_clip(fal_client, key=fal_key, job=active_job)
                                    await send({"type": "video.stopped", "reason": "user"})
                                elif event_type == "allow_visuals":
                                    visuals_allowed = True
                                    last_visual_instruction = None
                                    segment_epoch += 1
                                    visual_prompt = None
                                    latest_tool_call_id = None
                                    continuation_jpeg = None
                                    continuation_for_clip = None
                                    latest_clip_id = None
                                elif event_type == "hangup":
                                    await send({"type": "ended", "reason": "user"})
                                    break
                                else:
                                    raise ValueError("Unknown call event")
                                client_receive = asyncio.create_task(websocket.receive_text())
                            if provider_receive in done:
                                msg = provider_receive.result()
                                event = _decode_gemini_event(msg)
                                usage = event.get("usageMetadata")
                                if isinstance(usage, dict):
                                    ledger.stage_gemini(usage)
                                content = event.get("serverContent") or {}
                                if isinstance(content, dict):
                                    if content.get("interrupted"):
                                        await send({"type": "audio.interrupted"})
                                    for key, role in (("inputTranscription", "user"), ("outputTranscription", "model")):
                                        transcript = content.get(key)
                                        if isinstance(transcript, dict) and isinstance(transcript.get("text"), str):
                                            await send({"type": "transcript", "role": role, "text": transcript["text"][:2000], "final": role == "user" or bool(content.get("turnComplete"))})
                                    turn = content.get("modelTurn") or {}
                                    for part in turn.get("parts") or []:
                                        if isinstance(part, dict):
                                            inline = part.get("inlineData") or {}
                                            if isinstance(inline, dict) and isinstance(inline.get("data"), str) and str(inline.get("mimeType") or "").startswith("audio/"):
                                                await send({"type": "audio_chunk", "data": inline["data"]})
                                    if content.get("turnComplete") and ledger.commit_gemini_turn():
                                        await settle()
                                    if content.get("turnComplete"):
                                        await send({"type": "transcript", "role": "model", "text": "", "final": True})
                                cancelled_calls = (event.get("toolCallCancellation") or {}).get("ids") or []
                                if latest_tool_call_id and latest_tool_call_id in cancelled_calls:
                                    segment_epoch += 1
                                    visual_prompt = None
                                    last_visual_instruction = None
                                    latest_tool_call_id = None
                                    continuation_jpeg = None
                                    continuation_for_clip = None
                                    latest_clip_id = None
                                    if active_job is not None:
                                        await cancel_clip(fal_client, key=fal_key, job=active_job)
                                    await send({"type": "video.stopped", "reason": "model"})
                                for call in (event.get("toolCall") or {}).get("functionCalls") or []:
                                    if not isinstance(call, dict) or call.get("name") != "generate_visual_clip":
                                        continue
                                    args = call.get("args") or {}
                                    prompt = args.get("prompt") if isinstance(args, dict) else None
                                    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > MAX_PROMPT or "http://" in prompt or "https://" in prompt or FORBIDDEN_VIDEO_LANGUAGE.search(prompt):
                                        await send_provider(gemini, _tool_response(call, "invalid visual instruction"))
                                    elif not visuals_allowed or (last_visual_instruction is not None and time.monotonic() - last_visual_instruction >= IDLE_VIDEO_SECONDS):
                                        await send_provider(gemini, _tool_response(call, "visuals are stopped; continue voice"))
                                    else:
                                        last_visual_instruction = time.monotonic()
                                        visual_prompt = prompt.strip()
                                        latest_tool_call_id = str(call.get("id")) if call.get("id") is not None else None
                                        await send_provider(gemini, _tool_response(call, "visual direction accepted; voice may continue"))
                                        if active_video is None or active_video.done():
                                            active_video = asyncio.create_task(visual_chain(segment_epoch))
                                provider_receive = asyncio.create_task(gemini.receive())
                    finally:
                        # Fence every late result before waiting for accepted
                        # work to settle; never start another clip after exit.
                        visuals_allowed = False
                        segment_epoch += 1
                        visual_prompt = None
                        disconnected = True
                        client_receive.cancel()
                        provider_receive.cancel()
                        await asyncio.gather(client_receive, provider_receive, return_exceptions=True)
                        if active_video is not None:
                            if active_job is not None:
                                await cancel_clip(fal_client, key=fal_key, job=active_job)
                            # A completed provider job may still be spend-bearing.
                            # Observe its bounded outcome before unlocking.
                            await _finish_accepted_job(active_video)
    except WebSocketDisconnect:
        disconnected = True
    except asyncio.CancelledError:
        disconnected = True
        raise
    except Exception as exc:
        frames = traceback.extract_tb(exc.__traceback__)
        origin = frames[-1] if frames else None
        # Function/line identify the validation branch without logging the
        # exception text, provider payload, transcript or captured media.
        logger.warning("Video call ended with %s at %s:%s", type(exc).__name__, origin.name if origin else "unknown", origin.lineno if origin else 0)
        try:
            # Media cleanup fences background sends before this handler. A
            # connected caller must still receive the terminal call error.
            async with socket_send_lock:
                await websocket.send_json({"type": "error", "code": "call_unavailable", "message": "Call unavailable. Your call has ended."})
        except Exception:
            pass
    finally:
        await _settle_final_usage(websocket, ledger, user_id=user_id, user_hash=user_hash, call_id=call_id)
        await _release_lock(lock_client, lock_key, lock_token)
        try:
            await websocket.close()
        except Exception:
            pass
