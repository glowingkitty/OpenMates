"""Bounded anonymous accounting for first-party ephemeral composer dictation."""

from __future__ import annotations

import math
import logging
import uuid
from typing import Any

from backend.apps.audio.pricing import calculate_realtime_transcription_credits
from backend.core.api.app.services.anonymous_free_usage_service import (
    AnonymousFreeUsageService,
)

logger = logging.getLogger(__name__)

GUEST_MAX_AUDIO_SECONDS = 120
GUEST_IDLE_SECONDS = 20
GUEST_WALL_SECONDS = GUEST_MAX_AUDIO_SECONDS + 60
GUEST_MAX_TRANSCRIPT_CHARACTERS = 24_000


class GuestTranscriptionDenied(RuntimeError):
    def __init__(self, code: str = "anonymous_usage_limit") -> None:
        super().__init__(
            "The free allowance cannot cover this recording. Create an account to continue."
        )
        self.code = code
        self.signup_required = code in {
            "anonymous_usage_limit",
            "budget_exhausted",
            "per_identity_exhausted",
            "inactive",
            "anonymous_unavailable",
        }


class _CorrectionCharge:
    def __init__(
        self,
        meter: "GuestTranscriptionMeter",
        operation_id: str,
        pricing: dict,
        quote: int,
    ) -> None:
        self.dispatched = False
        self.finalized_credits: int | None = None
        self.meter, self.operation_id, self.pricing, self.quote = (
            meter,
            operation_id,
            pricing,
            quote,
        )

    def mark_dispatched(self) -> None:
        self.dispatched = True

    async def finalize_unresolved(self) -> None:
        if self.finalized_credits is None:
            await self._finalize(self.quote if self.dispatched else 0)

    async def _finalize(self, actual: int) -> None:
        if self.finalized_credits is not None:
            if self.finalized_credits != actual:
                raise RuntimeError("Correction settlement changed after finalization")
            return
        await self.meter.service.finalize_charge(
            self.operation_id, actual_credits=actual
        )
        self.finalized_credits = actual

    async def settle(self, input_tokens: Any, output_tokens: Any) -> None:
        from backend.shared.python_utils.billing_utils import calculate_total_credits

        # A completed response with absent usage still consumes its conservative
        # quote. Dispatched unknown/failed responses finalize the same quote so
        # pending-reservation expiry cannot refund actual provider work.
        if (
            isinstance(input_tokens, int)
            and not isinstance(input_tokens, bool)
            and input_tokens >= 0
            and isinstance(output_tokens, int)
            and not isinstance(output_tokens, bool)
            and output_tokens >= 0
        ):
            actual = calculate_total_credits(
                pricing_config=self.pricing,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )
            if actual > self.quote:
                raise RuntimeError("Correction usage exceeded its conservative quote")
        else:
            actual = self.quote
        await self._finalize(actual)


class GuestTranscriptionMeter:
    def __init__(self, websocket: Any) -> None:
        self.websocket = websocket
        self.service = AnonymousFreeUsageService(
            directus_service=websocket.app.state.directus_service,
            cache_service=websocket.app.state.cache_service,
            require_distributed_lock=True,
        )
        self.request_id = "audio-guest:" + uuid.uuid4().hex
        self.audio_charge_id = self.request_id + ":pcm"
        self.audio_reserved = 0
        self.sequence = 0
        self.locks: list[tuple[Any, str, str]] = []

    async def admit(self) -> None:
        from backend.core.api.app.routes.anonymous import _anonymous_client_ip
        from backend.core.api.app.utils.server_mode import validate_request_domain

        # First-party browser surface; no account chat/file/workflow authority.
        if validate_request_domain(self.websocket)[1]:
            raise GuestTranscriptionDenied("anonymous_unavailable")
        anonymous_id = self.websocket.query_params.get("anonymous_id")
        if not isinstance(anonymous_id, str) or not 1 <= len(anonymous_id) <= 128:
            raise GuestTranscriptionDenied("invalid_anonymous_id")
        ip = _anonymous_client_ip(self.websocket)
        identity = self.service.request_identity(anonymous_id, ip)
        # Both rate buckets are needed: a new caller-controlled ID cannot reset IP admission.
        for bucket in (
            "local:" + identity,
            "ip:" + self.service.request_identity(None, ip),
        ):
            if not await self.service.consume_local_rate_limit(
                "audio:" + bucket, max_requests=6
            ):
                raise GuestTranscriptionDenied("rate_limited")
        client = await self.websocket.app.state.cache_service.client
        if not client:
            raise RuntimeError("Anonymous admission unavailable")
        for bucket in (
            "local:" + identity,
            "ip:" + self.service.request_identity(None, ip),
        ):
            digest = self.service.request_identity(None, "audio-lock:" + bucket)
            key, token = "audio:guest:active:" + digest, uuid.uuid4().hex
            if not await client.set(key, token, nx=True, ex=GUEST_WALL_SECONDS + 60):
                raise GuestTranscriptionDenied("recording_active")
            self.locks.append((client, key, token))
        admission = await self.service.open_request(
            request_id=self.request_id, anonymous_id=anonymous_id, ip_address=ip
        )
        if not admission.accepted:
            raise GuestTranscriptionDenied(admission.reason or "anonymous_usage_limit")
        await self.reserve_audio(0.001)

    async def reserve_audio(self, seconds: float) -> None:
        if not math.isfinite(seconds) or seconds > GUEST_MAX_AUDIO_SECONDS:
            raise GuestTranscriptionDenied("recording_limit")
        target = calculate_realtime_transcription_credits(duration_seconds=seconds)
        additional = target - self.audio_reserved
        if additional <= 0:
            return
        operation_id = self.request_id + f":pcm:{self.audio_reserved}"
        result = await self.service.reserve_operation(
            parent_request_id=self.request_id,
            operation_id=operation_id,
            charge_id=self.audio_charge_id,
            quoted_credits=additional,
        )
        if not result.accepted:
            raise GuestTranscriptionDenied(result.reason or "anonymous_usage_limit")
        self.audio_reserved = target

    async def settle_ambiguous_audio(self) -> None:
        if self.audio_reserved:
            await self.service.finalize_charge(
                self.audio_charge_id, actual_credits=self.audio_reserved
            )

    async def settle_audio(self, seconds: float) -> None:
        if self.audio_reserved:
            actual = calculate_realtime_transcription_credits(duration_seconds=seconds)
            if actual > self.audio_reserved:
                # Never charge beyond admitted work or refund an inconsistent provider report.
                raise RuntimeError("Audio usage exceeded admitted PCM")
            await self.service.finalize_charge(
                self.audio_charge_id, actual_credits=actual
            )

    async def reserve_correction(
        self, model: str, input_bytes: int, output_tokens: int
    ) -> _CorrectionCharge:
        from backend.core.api.app.utils.config_manager import ConfigManager
        from backend.shared.python_utils.billing_utils import calculate_total_credits
        from backend.shared.providers.gemini_transcript_correction import (
            GEMINI_CORRECTION_MODEL,
        )
        from backend.shared.providers.transcript_correction import (
            MERCURY_CORRECTION_MODEL,
        )

        providers = {
            GEMINI_CORRECTION_MODEL: "google",
            MERCURY_CORRECTION_MODEL: "inception",
        }
        if (
            model not in providers
            or input_bytes > 32_000
            or not 1 <= output_tokens <= 2048
        ):
            raise GuestTranscriptionDenied("correction_limit")
        config = (
            getattr(self.websocket.app.state, "config_manager", None) or ConfigManager()
        )
        pricing = config.get_model_pricing(providers[model], model)
        if not pricing or not pricing.get(
            "tokens", pricing.get("pricing", {}).get("tokens")
        ):
            raise RuntimeError("Correction pricing unavailable")
        # UTF-8 bytes conservatively bound input tokens; wrapper adds schema/framing bytes.
        quote = calculate_total_credits(
            pricing_config=pricing,
            input_tokens=input_bytes,
            output_tokens=output_tokens,
        )
        if quote < 1:
            raise RuntimeError("Correction quote unavailable")
        self.sequence += 1
        operation_id = self.request_id + f":correction:{self.sequence}"
        result = await self.service.reserve_operation(
            parent_request_id=self.request_id,
            operation_id=operation_id,
            charge_id=operation_id,
            quoted_credits=quote,
        )
        if not result.accepted:
            raise GuestTranscriptionDenied(result.reason or "anonymous_usage_limit")
        return _CorrectionCharge(self, operation_id, pricing, quote)

    async def release_locks(self) -> None:
        for client, key, token in reversed(self.locks):
            # Atomic owner check avoids deleting a renewed lease from another request.
            try:
                await client.eval(
                    "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end",
                    1,
                    key,
                    token,
                )
            except Exception:
                logger.warning(
                    "Failed to release guest recording admission lock", exc_info=True
                )
        self.locks.clear()
