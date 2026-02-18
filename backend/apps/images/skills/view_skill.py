# backend/apps/images/skills/view_skill.py
#
# Skill that allows the AI to analyse an uploaded image.
#
# Architecture:
#   When a user attaches an uploaded image to a chat message and asks the AI
#   about it, the AI processor extracts the embed's TOON content (which contains
#   the vault_wrapped_aes_key and S3 file keys) and calls this skill.
#
#   This skill:
#     1. Accepts the vault_wrapped_aes_key and s3_key from the embed metadata
#     2. Unwraps the AES key via Vault Transit (using the user's vault_key_id)
#     3. Downloads the encrypted file from S3
#     4. Decrypts with AES-256-GCM
#     5. Encodes the plaintext image bytes as base64
#     6. Passes the image to the AI model via multimodal vision
#
#   Security:
#     - The vault_wrapped_aes_key can ONLY be unwrapped if the Vault token has
#       permission for the user's transit key — the server controls decryption.
#     - Plaintext image bytes exist only transiently in memory during this call.
#     - The plaintext aes_key is never logged or persisted by this skill.

import base64
import logging
import os
from typing import Any, Dict, Optional

import httpx
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from pydantic import BaseModel, Field

from backend.apps.base_skill import BaseSkill

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pydantic models (auto-discovered by apps_api.py for OpenAPI docs)
# ---------------------------------------------------------------------------

class ViewRequest(BaseModel):
    """
    Request model for the images.view skill.
    The AI processor populates these fields from the uploaded image embed's
    TOON content when the user asks about an image they uploaded.
    """
    embed_id: str = Field(
        ...,
        description="The embed_id of the uploaded image to analyse."
    )
    vault_wrapped_aes_key: str = Field(
        ...,
        description=(
            "Vault Transit-wrapped AES key from the embed metadata. "
            "The skill unwraps this via Vault to decrypt the image."
        )
    )
    s3_key: str = Field(
        ...,
        description=(
            "S3 object key for the image variant to analyse "
            "(e.g. 'user-id/sha256.../original.bin')."
        )
    )
    s3_base_url: str = Field(
        ...,
        description="S3 base URL (e.g. 'https://chatfiles.nbg1.your-objectstorage.com')."
    )
    aes_nonce: str = Field(
        ...,
        description="Base64 AES-GCM nonce used when encrypting this file variant."
    )
    query: str = Field(
        ...,
        description="The user's question or instruction about the image."
    )
    vault_key_id: Optional[str] = Field(
        None,
        description=(
            "The user's Vault Transit key ID. If omitted, the skill tries "
            "to get it from user context."
        )
    )


class ViewResponse(BaseModel):
    """Response model for the images.view skill."""
    success: bool = Field(default=False, description="Whether the analysis completed.")
    analysis: Optional[str] = Field(None, description="The AI's analysis of the image.")
    embed_id: Optional[str] = Field(None, description="The embed_id that was analysed.")
    error: Optional[str] = Field(None, description="Error message if analysis failed.")


# ---------------------------------------------------------------------------
# Skill implementation
# ---------------------------------------------------------------------------

class ViewSkill(BaseSkill):
    """
    Skill for analysing uploaded images using the AI model's vision capabilities.

    This skill is invoked when a user asks the AI about an image they uploaded
    to the chat. It fetches and decrypts the image from S3, then passes it to
    the multimodal AI model for analysis.

    Unlike the generate/generate_draft skills (which are async Celery tasks),
    this skill executes synchronously and returns the analysis result directly.
    """

    # Vault token path — same as other services that read Vault secrets
    VAULT_TOKEN_PATH: str = "/vault-data/api.token"

    def _load_vault_token(self) -> str:
        """Load the Vault service token from the mounted token file."""
        with open(self.VAULT_TOKEN_PATH, "r") as f:
            token = f.read().strip()
        if not token:
            raise RuntimeError("Vault token file is empty")
        return token

    async def _unwrap_aes_key(self, vault_wrapped_aes_key: str, vault_key_id: str) -> bytes:
        """
        Unwrap the Vault Transit-wrapped AES key to recover the plaintext key bytes.

        Args:
            vault_wrapped_aes_key: Base64 Vault-wrapped ciphertext from embed metadata.
            vault_key_id: The user's Vault Transit key ID.

        Returns:
            Raw AES key bytes (32 bytes for AES-256).

        Raises:
            RuntimeError: If Vault transit decryption fails.
        """
        vault_url = os.environ.get("VAULT_URL", "http://vault:8200")
        token = self._load_vault_token()

        decrypt_url = f"{vault_url}/v1/transit/decrypt/{vault_key_id}"
        payload = {"ciphertext": vault_wrapped_aes_key}

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                decrypt_url,
                json=payload,
                headers={"X-Vault-Token": token},
            )

        if resp.status_code != 200:
            raise RuntimeError(
                f"Vault transit decrypt failed for key {vault_key_id}: "
                f"HTTP {resp.status_code} — {resp.text[:200]}"
            )

        # Vault returns the plaintext as base64
        plaintext_b64 = resp.json()["data"]["plaintext"]
        return base64.b64decode(plaintext_b64)

    async def _download_from_s3(self, s3_base_url: str, s3_key: str) -> bytes:
        """
        Download an encrypted file from S3.

        Args:
            s3_base_url: Base URL of the S3 bucket.
            s3_key: Object key within the bucket.

        Returns:
            Encrypted file bytes.

        Raises:
            RuntimeError: If the download fails.
        """
        full_url = f"{s3_base_url.rstrip('/')}/{s3_key}"
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.get(full_url)

        if resp.status_code != 200:
            raise RuntimeError(
                f"S3 download failed for {s3_key}: HTTP {resp.status_code}"
            )

        return resp.content

    async def execute(
        self,
        embed_id: str,
        vault_wrapped_aes_key: str,
        s3_key: str,
        s3_base_url: str,
        aes_nonce: str,
        query: str,
        vault_key_id: Optional[str] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """
        Analyse an uploaded image.

        Steps:
        1. Get the user's vault_key_id from kwargs if not provided.
        2. Unwrap the AES key via Vault Transit.
        3. Download the encrypted file from S3.
        4. Decrypt with AES-256-GCM.
        5. Pass base64-encoded image to the AI model.

        Args:
            embed_id: Embed ID of the image.
            vault_wrapped_aes_key: Vault-wrapped AES key from embed content.
            s3_key: S3 object key for the encrypted file.
            s3_base_url: S3 bucket base URL.
            aes_nonce: Base64 AES-GCM nonce.
            query: The user's question about the image.
            vault_key_id: Optional Vault key ID; falls back to kwargs['user_vault_key_id'].
            **kwargs: Additional context (user_id, user_vault_key_id, etc.).

        Returns:
            ViewResponse-compatible dict.
        """
        log_prefix = f"[images.view] [embed:{embed_id[:8]}...]"

        # --- Resolve vault_key_id ---
        resolved_vault_key_id = vault_key_id or kwargs.get("user_vault_key_id")
        if not resolved_vault_key_id:
            logger.error(f"{log_prefix} vault_key_id not available — cannot decrypt image")
            return ViewResponse(
                success=False,
                embed_id=embed_id,
                error="Cannot decrypt image: vault key ID not available",
            ).dict()

        try:
            # --- Step 1: Unwrap AES key via Vault ---
            logger.info(f"{log_prefix} Unwrapping AES key via Vault transit key {resolved_vault_key_id}")
            aes_key_bytes = await self._unwrap_aes_key(vault_wrapped_aes_key, resolved_vault_key_id)

            # --- Step 2: Download encrypted file from S3 ---
            logger.info(f"{log_prefix} Downloading encrypted image from S3: {s3_key}")
            encrypted_bytes = await self._download_from_s3(s3_base_url, s3_key)

            # --- Step 3: Decrypt with AES-256-GCM ---
            nonce_bytes = base64.b64decode(aes_nonce)
            aesgcm = AESGCM(aes_key_bytes)
            plaintext_bytes = aesgcm.decrypt(nonce_bytes, encrypted_bytes, None)
            logger.info(f"{log_prefix} Decrypted image: {len(plaintext_bytes)} bytes")

            # --- Step 4: Encode as base64 for multimodal AI call ---
            image_b64 = base64.b64encode(plaintext_bytes).decode("utf-8")

            # --- Step 5: Call AI model with image ---
            # The base skill's execute_with_vision helper (if available) handles the
            # multimodal prompt. Fall back to the standard execute approach.
            analysis_result = await self._analyse_with_vision(
                image_b64=image_b64,
                query=query,
                log_prefix=log_prefix,
                **kwargs,
            )

            return ViewResponse(
                success=True,
                analysis=analysis_result,
                embed_id=embed_id,
            ).dict()

        except RuntimeError as e:
            logger.error(f"{log_prefix} Failed to decrypt/download image: {e}", exc_info=True)
            return ViewResponse(
                success=False,
                embed_id=embed_id,
                error=f"Failed to access image: {e}",
            ).dict()
        except Exception as e:
            logger.error(f"{log_prefix} Unexpected error during image analysis: {e}", exc_info=True)
            return ViewResponse(
                success=False,
                embed_id=embed_id,
                error=f"Image analysis failed: {e}",
            ).dict()

    async def _analyse_with_vision(
        self,
        image_b64: str,
        query: str,
        log_prefix: str,
        **kwargs: Any,
    ) -> str:
        """
        Pass the base64-encoded image to the AI model for analysis.

        The AI processor (base_skill) handles provider selection and API calls.
        We construct a multimodal message with the image inline as base64.

        Returns:
            The AI model's text response analysing the image.
        """
        # Build multimodal content: text query + inline image
        # This format is compatible with OpenAI/Anthropic vision APIs via the base skill.
        multimodal_content = [
            {
                "type": "text",
                "text": query,
            },
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/webp;base64,{image_b64}",
                    "detail": "high",
                },
            },
        ]

        # Use the inherited provider calling mechanism from BaseSkill.
        # The model is configured via app.yml (full_model_reference for this skill).
        response = await self.call_provider(
            messages=[{"role": "user", "content": multimodal_content}],
            system_prompt=(
                "You are an expert image analyst. Analyse the provided image carefully "
                "and respond to the user's query with accurate, detailed observations. "
                "Describe what you see, identify relevant details, and answer any specific "
                "questions about the image content."
            ),
            **kwargs,
        )

        logger.info(f"{log_prefix} Vision analysis complete")
        return response
