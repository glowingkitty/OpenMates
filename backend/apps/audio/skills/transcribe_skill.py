# backend/apps/audio/skills/transcribe_skill.py
#
# Audio transcription skill using Mistral Voxtral Mini (voxtral-mini-2602).
#
# Flow per request:
#   1. Fetch encrypted audio file from S3 using provided s3_base_url + s3_key.
#   2. Decrypt via AES-256-GCM using the plaintext aes_key + aes_nonce.
#   3. POST decrypted audio bytes to Mistral's transcription API.
#   4. Return the transcript text.
#
# Pricing: $0.003/min — cheapest Voxtral model, ideal for short voice messages.
# Model: voxtral-mini-2602 (alias: voxtral-mini-latest for the transcriptions endpoint)
#
# Architecture decision: Direct async execution (no Celery) — transcription of
# short voice clips is typically 1-5 seconds, and async I/O keeps it non-blocking.
# Same rationale as TranscriptSkill in videos app.

import logging
import base64
import io
import math
import hashlib
import httpx
from typing import Dict, Any, List, Optional, Tuple
from pydantic import BaseModel, Field

from backend.apps.base_skill import BaseSkill
from backend.core.api.app.utils.secrets_manager import SecretsManager

logger = logging.getLogger(__name__)

# Mistral API endpoint for audio transcriptions
MISTRAL_TRANSCRIPTION_URL = "https://api.mistral.ai/v1/audio/transcriptions"

# Model to use — voxtral-mini-2602 at $0.003/min is optimal for short recordings
VOXTRAL_MODEL = "voxtral-mini-2602"

# Timeout for Mistral API calls (seconds)
MISTRAL_API_TIMEOUT = 120


class TranscribeRequestItem(BaseModel):
    """
    Individual audio transcription request item.

    The audio file has already been uploaded to S3 encrypted (AES-256-GCM).
    This skill fetches + decrypts it before sending to Mistral.
    """
    s3_base_url: str = Field(..., description="S3 base URL for the encrypted audio file.")
    s3_key: str = Field(..., description="S3 object key for the encrypted audio file.")
    aes_key: str = Field(..., description="Base64-encoded plaintext AES-256 key.")
    aes_nonce: str = Field(..., description="Base64-encoded AES-GCM nonce.")
    vault_wrapped_aes_key: Optional[str] = Field(
        None, description="Vault Transit-wrapped AES key (unused in this skill, present for schema consistency)."
    )
    language: Optional[str] = Field(
        None, description="Optional ISO 639-1 language hint (e.g. 'en', 'de'). Improves accuracy."
    )
    filename: Optional[str] = Field(
        None, description="Original filename of the recording (used to detect audio format)."
    )


class TranscribeRequest(BaseModel):
    """
    Request model for the transcribe skill.
    Supports multiple recordings in a single request (processed in parallel).
    """
    requests: List[TranscribeRequestItem] = Field(
        ...,
        description="Array of transcription request objects. Each must contain S3 location + AES decryption keys."
    )


class TranscribeResult(BaseModel):
    """Result for a single audio transcription."""
    s3_key: str
    transcript: Optional[str] = None
    language: Optional[str] = None
    duration_seconds: Optional[float] = None
    error: Optional[str] = None


class TranscribeResponse(BaseModel):
    """Response model for the transcribe skill."""
    results: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="List of request results. Each entry contains 'id' and 'results' array."
    )
    provider: str = Field(
        default="Mistral Voxtral",
        description="The provider used for transcription."
    )
    error: Optional[str] = Field(None, description="Top-level error if processing completely failed.")
    ignore_fields_for_inference: Optional[List[str]] = Field(
        default_factory=lambda: ["type"],
        description="Fields excluded from LLM inference to reduce token usage."
    )


class TranscribeSkill(BaseSkill):
    """
    Audio transcription skill using Mistral's Voxtral Mini model.

    Fetches encrypted audio from S3, decrypts it client-side, then sends
    the raw audio bytes to Mistral's /v1/audio/transcriptions endpoint.

    Model: voxtral-mini-2602
    Price: $0.003/min
    Max file: 1 GB, up to 3 hours
    Supported formats: mp3, wav, m4a, flac, ogg, webm (Mistral accepts audio/webm)

    Architecture:
    - Executes directly in app-audio (FastAPI container) via async/await.
    - No Celery tasks needed — voice clips are typically < 5 min and fast to process.
    - S3 fetch + AES decrypt runs in a thread pool (blocking I/O).
    - Mistral API call is async via httpx.
    """

    def __init__(
        self,
        app,
        app_id: str,
        skill_id: str,
        skill_name: str,
        skill_description: str,
        stage: str = "development",
        full_model_reference: Optional[str] = None,
        pricing_config: Optional[Dict[str, Any]] = None,
        celery_producer=None,
        skill_operational_defaults: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            app=app,
            app_id=app_id,
            skill_id=skill_id,
            skill_name=skill_name,
            skill_description=skill_description,
            stage=stage,
            full_model_reference=full_model_reference,
            pricing_config=pricing_config,
            celery_producer=celery_producer,
        )
        if skill_operational_defaults:
            logger.debug(f"TranscribeSkill '{self.skill_name}' received operational_defaults: {skill_operational_defaults}")

    def _detect_mime_type(self, filename: Optional[str], default: str = "audio/webm") -> str:
        """
        Detect MIME type from filename extension.

        Mistral supports: mp3, wav, m4a, flac, ogg, webm.
        Chrome/Firefox default to audio/webm which Mistral accepts.

        Args:
            filename: Original filename of the recording (may be None).
            default: Fallback MIME type if extension cannot be determined.

        Returns:
            MIME type string for the multipart upload.
        """
        if not filename:
            return default
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        mime_map = {
            "webm": "audio/webm",
            "mp3": "audio/mpeg",
            "wav": "audio/wav",
            "m4a": "audio/mp4",
            "mp4": "audio/mp4",
            "flac": "audio/flac",
            "ogg": "audio/ogg",
        }
        return mime_map.get(ext, default)

    def _decrypt_audio(
        self,
        encrypted_bytes: bytes,
        aes_key_b64: str,
        aes_nonce_b64: str,
    ) -> bytes:
        """
        Decrypt AES-256-GCM encrypted audio bytes.

        The upload server encrypts files with AES-256-GCM before storing in S3.
        This method performs the symmetric decryption using the plaintext key
        returned by the upload server (stored in the embed node attrs).

        Args:
            encrypted_bytes: Raw encrypted bytes from S3 (nonce prepended or separate?).
            aes_key_b64: Base64-encoded 32-byte AES-256 key.
            aes_nonce_b64: Base64-encoded 12-byte AES-GCM nonce.

        Returns:
            Decrypted audio bytes ready for Mistral.

        Raises:
            ValueError: If decryption fails due to wrong key/nonce or corrupted data.
        """
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM

            key = base64.b64decode(aes_key_b64)
            nonce = base64.b64decode(aes_nonce_b64)
            aesgcm = AESGCM(key)
            decrypted = aesgcm.decrypt(nonce, encrypted_bytes, None)
            return decrypted
        except Exception as e:
            logger.error(f"[TranscribeSkill] AES-GCM decryption failed: {e}", exc_info=True)
            raise ValueError(f"Audio decryption failed: {e}") from e

    async def _fetch_and_decrypt_audio(
        self,
        s3_base_url: str,
        s3_key: str,
        aes_key_b64: str,
        aes_nonce_b64: str,
    ) -> bytes:
        """
        Fetch encrypted audio from S3 and decrypt it.

        The S3 URL is constructed as: {s3_base_url}/{s3_key}
        The fetch is done with httpx (async); decryption runs synchronously
        but is fast enough (milliseconds for typical voice clips) to run inline.

        Args:
            s3_base_url: Base URL of the S3 bucket (e.g. 'https://s3.eu-central-1.wasabisys.com/bucket').
            s3_key: Object key in the bucket (e.g. 'uploads/uuid/original.webm.enc').
            aes_key_b64: Base64-encoded AES-256 key.
            aes_nonce_b64: Base64-encoded AES-GCM nonce.

        Returns:
            Decrypted audio bytes.

        Raises:
            httpx.HTTPError: If the S3 fetch fails.
            ValueError: If decryption fails.
        """
        url = f"{s3_base_url.rstrip('/')}/{s3_key}"
        logger.debug(f"[TranscribeSkill] Fetching audio from S3: {s3_key}")

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.get(url)
            response.raise_for_status()
            encrypted_bytes = response.content

        logger.debug(f"[TranscribeSkill] Fetched {len(encrypted_bytes)} encrypted bytes from S3")

        # Decrypt synchronously (fast for audio files, no need for thread pool)
        decrypted = self._decrypt_audio(encrypted_bytes, aes_key_b64, aes_nonce_b64)
        logger.debug(f"[TranscribeSkill] Decrypted audio: {len(decrypted)} bytes")
        return decrypted

    async def _transcribe_with_mistral(
        self,
        audio_bytes: bytes,
        filename: str,
        mime_type: str,
        language: Optional[str],
        mistral_api_key: str,
    ) -> Dict[str, Any]:
        """
        Send audio bytes to Mistral's transcription API and return the result.

        Uses multipart/form-data upload (same as Whisper-compatible APIs).
        The voxtral-mini-2602 model supports multiple languages and returns
        plain text transcription by default.

        Args:
            audio_bytes: Decrypted audio file bytes.
            filename: Filename to send in multipart (affects format detection by Mistral).
            mime_type: MIME type of the audio (e.g. 'audio/webm').
            language: Optional ISO 639-1 language code hint.
            mistral_api_key: Mistral API key from Vault secrets.

        Returns:
            Dict with 'text' (transcript string) and optionally 'language', 'duration'.

        Raises:
            httpx.HTTPError: If the API call fails with a non-2xx status.
        """
        logger.info(f"[TranscribeSkill] Sending {len(audio_bytes)} bytes to Mistral Voxtral ({VOXTRAL_MODEL})")

        files = {
            "file": (filename, io.BytesIO(audio_bytes), mime_type),
        }
        data = {
            "model": VOXTRAL_MODEL,
        }
        if language:
            data["language"] = language

        headers = {
            "Authorization": f"Bearer {mistral_api_key}",
        }

        async with httpx.AsyncClient(timeout=MISTRAL_API_TIMEOUT) as client:
            response = await client.post(
                MISTRAL_TRANSCRIPTION_URL,
                headers=headers,
                files=files,
                data=data,
            )

        if response.status_code != 200:
            error_text = response.text[:500]
            logger.error(
                f"[TranscribeSkill] Mistral API error {response.status_code}: {error_text}"
            )
            raise httpx.HTTPStatusError(
                f"Mistral API returned {response.status_code}: {error_text}",
                request=response.request,
                response=response,
            )

        result = response.json()
        logger.info(
            f"[TranscribeSkill] Transcription complete. "
            f"Text length: {len(result.get('text', ''))}, "
            f"detected language: {result.get('language', 'unknown')}"
        )
        return result

    async def _process_single_transcribe_request(
        self,
        req: Dict[str, Any],
        request_id: Any,
        secrets_manager: SecretsManager,
    ) -> Tuple[Any, List[Dict[str, Any]], Optional[str]]:
        """
        Process a single audio transcription request.

        Steps:
          1. Extract S3 location + AES keys from request.
          2. Fetch Mistral API key from Vault.
          3. Fetch encrypted audio from S3 and decrypt.
          4. Send to Mistral Voxtral for transcription.
          5. Return structured result.

        Args:
            req: Request dict with s3_base_url, s3_key, aes_key, aes_nonce, language, filename.
            request_id: The id of this request (for matching in response).
            secrets_manager: Injected secrets manager for Vault access.

        Returns:
            Tuple of (request_id, results_list, error_string_or_none).
        """
        s3_base_url = req.get("s3_base_url", "")
        s3_key = req.get("s3_key", "")
        aes_key = req.get("aes_key", "")
        aes_nonce = req.get("aes_nonce", "")
        language = req.get("language") or None
        filename = req.get("filename") or "recording.webm"

        # Validate required fields
        if not s3_base_url or not s3_key or not aes_key or not aes_nonce:
            return (request_id, [], "Missing required fields: s3_base_url, s3_key, aes_key, aes_nonce")

        try:
            # Step 1: Get Mistral API key from Vault
            mistral_api_key = await secrets_manager.get_secret(
                secret_path="kv/data/providers/mistral",
                secret_key="api_key"
            )
            if not mistral_api_key:
                logger.error("[TranscribeSkill] Mistral API key not found in Vault")
                return (request_id, [], "Mistral API key not configured")

            # Step 2: Fetch and decrypt audio from S3
            audio_bytes = await self._fetch_and_decrypt_audio(
                s3_base_url=s3_base_url,
                s3_key=s3_key,
                aes_key_b64=aes_key,
                aes_nonce_b64=aes_nonce,
            )

            # Step 3: Determine MIME type from filename
            mime_type = self._detect_mime_type(filename)

            # Step 4: Transcribe via Mistral Voxtral
            mistral_result = await self._transcribe_with_mistral(
                audio_bytes=audio_bytes,
                filename=filename,
                mime_type=mime_type,
                language=language,
                mistral_api_key=mistral_api_key,
            )

            # Step 5: Build result
            transcript_text = mistral_result.get("text", "").strip()
            detected_language = mistral_result.get("language")
            duration_seconds = mistral_result.get("duration")

            result_entry = {
                "type": "transcription_result",
                "s3_key": s3_key,
                "transcript": transcript_text,
                "language": detected_language or language,
                "duration_seconds": duration_seconds,
            }

            logger.debug(
                f"[TranscribeSkill] Request {request_id} complete: "
                f"{len(transcript_text)} chars, language={detected_language}"
            )
            return (request_id, [result_entry], None)

        except ValueError as e:
            # Decryption errors
            logger.error(f"[TranscribeSkill] Decryption error for request {request_id}: {e}")
            return (request_id, [], f"Decryption error: {e}")

        except httpx.HTTPStatusError as e:
            logger.error(f"[TranscribeSkill] Mistral API error for request {request_id}: {e}")
            return (request_id, [], f"Transcription API error: {e}")

        except httpx.RequestError as e:
            logger.error(f"[TranscribeSkill] Network error for request {request_id}: {e}", exc_info=True)
            return (request_id, [], f"Network error: {e}")

        except Exception as e:
            logger.error(f"[TranscribeSkill] Unexpected error for request {request_id}: {e}", exc_info=True)
            return (request_id, [], f"Unexpected error: {e}")

    async def execute(
        self,
        requests: List[Dict[str, Any]],
        secrets_manager: Optional[SecretsManager] = None,
        user_id: Optional[str] = None,
        **kwargs,
    ) -> TranscribeResponse:
        """
        Execute the audio transcription skill.

        Processes all requests in parallel (asyncio.gather) for best performance.
        Each request fetches+decrypts its own audio file and calls Mistral independently.

        After successful transcription, charges credits based on audio duration:
          - 3 credits per minute (Mistral Voxtral Mini costs $0.003/min ≈ 3 credits)
          - 1-minute minimum (recordings < 1 min always cost 3 credits)
          - Total = max(1, ceil(total_duration_seconds / 60)) * 3

        Args:
            requests: Array of transcription request objects (see TranscribeRequest model).
            secrets_manager: SecretsManager instance injected by the app.
            user_id: The authenticated user's ID (injected by BaseApp route handler).

        Returns:
            TranscribeResponse with grouped results per request ID.

        Execution Flow:
        ---------------
        1. Request received in FastAPI route (app-audio container).
        2. This async method is called directly (no Celery dispatch).
        3. S3 fetch + Mistral API calls use async httpx (non-blocking).
        4. Credits charged based on total transcribed duration.
        5. Results returned directly to caller.
        """
        # Get or create SecretsManager using BaseSkill helper
        secrets_manager, error_response = await self._get_or_create_secrets_manager(
            secrets_manager=secrets_manager,
            skill_name="TranscribeSkill",
            error_response_factory=lambda msg: TranscribeResponse(results=[], error=msg),
            logger=logger,
        )
        if error_response:
            return error_response

        # Convert Pydantic models to dicts if needed
        requests_as_dicts: List[Dict[str, Any]] = []
        for req in requests:
            if isinstance(req, TranscribeRequestItem):
                requests_as_dicts.append(req.model_dump())
            elif isinstance(req, dict):
                requests_as_dicts.append(req)
            else:
                requests_as_dicts.append(dict(req))

        # Validate using BaseSkill helper
        validated_requests, error = self._validate_requests_array(
            requests=requests_as_dicts,
            required_field="s3_key",
            field_display_name="s3_key",
            empty_error_message="No transcription requests provided. 'requests' array must contain at least one item.",
            logger=logger,
        )
        if error:
            return TranscribeResponse(results=[], error=error)

        # Process all requests in parallel using BaseSkill helper
        results = await self._process_requests_in_parallel(
            requests=validated_requests,
            process_single_request_func=self._process_single_transcribe_request,
            logger=logger,
            secrets_manager=secrets_manager,
        )

        # Group results by request ID
        grouped_results, errors = self._group_results_by_request_id(
            results=results,
            requests=validated_requests,
            logger=logger,
        )

        # Build response
        response = self._build_response_with_errors(
            response_class=TranscribeResponse,
            grouped_results=grouped_results,
            errors=errors,
            provider="Mistral Voxtral",
            logger=logger,
        )

        success_count = sum(1 for g in grouped_results if g.get("results"))
        logger.info(
            f"[TranscribeSkill] Completed: {success_count}/{len(validated_requests)} succeeded, "
            f"{len(errors)} failed"
        )

        # --- Billing ---
        # Charge 3 credits/min (minimum 1 minute) for each successfully transcribed audio.
        # Pricing rationale: Mistral Voxtral Mini costs $0.003/min ≈ 1 credit; 3x markup applied.
        # The 1-minute minimum ensures very short clips are still charged fairly.
        # Billing is non-fatal: failures are logged but do not break the transcription response.
        if user_id and grouped_results:
            try:
                user_id_hash = hashlib.sha256(user_id.encode()).hexdigest()
                # Sum duration_seconds across all successful transcription results
                total_duration_seconds: float = 0.0
                for group in grouped_results:
                    for result_item in group.get("results", []):
                        if isinstance(result_item, dict) and not result_item.get("error"):
                            duration = result_item.get("duration_seconds")
                            if duration and isinstance(duration, (int, float)) and duration > 0:
                                total_duration_seconds += duration

                if total_duration_seconds > 0 and success_count > 0:
                    # Round up to nearest minute, enforce 1-minute minimum per request
                    total_minutes = max(success_count, math.ceil(total_duration_seconds / 60))
                    credits_to_charge = total_minutes * 3
                    logger.info(
                        f"[TranscribeSkill] Charging {credits_to_charge} credits for user "
                        f"{user_id_hash[:8]}... ({total_duration_seconds:.1f}s total, "
                        f"{total_minutes} billed minutes × 3 credits)"
                    )
                    await self.app.charge_user_credits(
                        user_id=user_id,
                        user_id_hash=user_id_hash,
                        credits_to_charge=credits_to_charge,
                        skill_id=self.skill_id,
                        app_id=self.app_id,
                        usage_details={
                            "duration_seconds": total_duration_seconds,
                            "billed_minutes": total_minutes,
                            "requests_transcribed": success_count,
                        }
                    )
                elif success_count > 0:
                    # Duration not returned by Mistral — apply 1-minute minimum per successful request
                    credits_to_charge = success_count * 3
                    logger.warning(
                        f"[TranscribeSkill] No duration returned from Mistral for {success_count} request(s). "
                        f"Applying 1-minute minimum: {credits_to_charge} credits."
                    )
                    await self.app.charge_user_credits(
                        user_id=user_id,
                        user_id_hash=user_id_hash,
                        credits_to_charge=credits_to_charge,
                        skill_id=self.skill_id,
                        app_id=self.app_id,
                        usage_details={
                            "duration_seconds": 0,
                            "billed_minutes": success_count,
                            "requests_transcribed": success_count,
                            "note": "duration unavailable — 1-minute minimum applied",
                        }
                    )
            except Exception as billing_error:
                # Billing failure must never break transcription — log and continue
                logger.error(
                    f"[TranscribeSkill] Credit charge failed (non-fatal): {billing_error}",
                    exc_info=True
                )

        return response
