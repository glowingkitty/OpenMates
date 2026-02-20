# backend/apps/images/skills/view_skill.py
#
# Skill that allows the AI to view an uploaded image directly.
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
#     5. Returns the image as a multimodal content list (image_url block)
#        so the MAIN inference model sees the image directly via tool result
#
#   The key architectural difference from the previous approach:
#     - Previously: skill called a sub-model (Gemini Flash) internally and
#       returned a text analysis string. The main model never saw the image.
#     - Now: skill returns a list of content blocks (text label + image_url).
#       The framework (llm_utils.py + provider adapters) passes this list
#       directly as the tool result to the main inference model.
#
#   Security:
#     - The vault_wrapped_aes_key can ONLY be unwrapped if the Vault token has
#       permission for the user's transit key — the server controls decryption.
#     - Plaintext image bytes exist only transiently in memory during this call.
#     - The plaintext aes_key is never logged or persisted by this skill.

import base64
import logging
import os
from typing import Any, Dict, List, Optional

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
        description="The embed_id of the uploaded image to view."
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
            "S3 object key for the image variant to view "
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
    """
    Response model for the images.view skill (for OpenAPI docs).

    At runtime, execute() returns a List of content blocks (not this model),
    which the framework forwards as a multimodal tool result to the main LLM.
    This model exists only to document the skill's output shape in the REST API.
    """
    success: bool = Field(default=False, description="Whether the image was loaded.")
    embed_id: Optional[str] = Field(None, description="The embed_id that was viewed.")
    error: Optional[str] = Field(None, description="Error message if loading failed.")


# ---------------------------------------------------------------------------
# Skill implementation
# ---------------------------------------------------------------------------

class ViewSkill(BaseSkill):
    """
    Skill for loading an uploaded image and returning it as a multimodal
    content block so the main inference model can see it directly.

    Unlike the old approach (which called Gemini Flash internally), this skill
    now returns the raw image bytes (base64-encoded) as an image_url content
    block. The framework's llm_utils.py passes the list through unchanged to
    the provider adapters, which convert the image_url block to the correct
    format for the active LLM (Anthropic image source, Google inlineData, etc.).
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
    ) -> List[Dict[str, Any]]:
        """
        Load an uploaded image and return it as a multimodal content list.

        Returns a list of content blocks that will become the tool result
        passed directly to the main inference model:
          [
            {"type": "text", "text": "Image: <filename>"},
            {"type": "image_url", "image_url": {"url": "data:image/webp;base64,...", "detail": "high"}}
          ]

        The framework (llm_utils.py) passes this list through unchanged.
        Provider adapters convert it to the LLM-specific format:
          - OpenAI/OpenRouter: image_url blocks pass through natively
          - Anthropic: converted to image source blocks in anthropic_shared.py
          - Google: converted to inlineData Parts in google_client.py

        Steps:
        1. Get the user's vault_key_id from kwargs if not provided.
        2. Unwrap the AES key via Vault Transit.
        3. Download the encrypted file from S3.
        4. Decrypt with AES-256-GCM.
        5. Return base64-encoded image as a content block list.

        Args:
            embed_id: Embed ID of the image.
            vault_wrapped_aes_key: Vault-wrapped AES key from embed content.
            s3_key: S3 object key for the encrypted file.
            s3_base_url: S3 bucket base URL.
            aes_nonce: Base64 AES-GCM nonce.
            query: The user's question about the image (not used here — the
                   main LLM processes it after seeing the image in the tool result).
            vault_key_id: Optional Vault key ID; falls back to kwargs['user_vault_key_id'].
            **kwargs: Additional context (user_id, user_vault_key_id, filename, etc.).

        Returns:
            List of content blocks for multimodal tool result, or a plain dict
            on error (for graceful degradation).
        """
        log_prefix = f"[images.view] [embed:{embed_id[:8]}...]"

        # --- Resolve vault_key_id ---
        resolved_vault_key_id = vault_key_id or kwargs.get("user_vault_key_id")
        if not resolved_vault_key_id:
            logger.error(f"{log_prefix} vault_key_id not available — cannot decrypt image")
            return [{"type": "text", "text": f"Error: Cannot view image {embed_id} — vault key ID not available."}]

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

            # --- Step 4: Encode as base64 for multimodal tool result ---
            image_b64 = base64.b64encode(plaintext_bytes).decode("utf-8")

            # Determine the label (filename if available, else embed_id)
            filename = kwargs.get("filename") or embed_id

            # --- Step 5: Return multimodal content list ---
            # The main LLM will see this image in the tool result and can analyse it
            # in context of the surrounding conversation and user query.
            logger.info(f"{log_prefix} Returning image as multimodal content block")
            return [
                {
                    "type": "text",
                    "text": f"Image: {filename}",
                },
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/webp;base64,{image_b64}",
                        "detail": "high",
                    },
                },
            ]

        except RuntimeError as e:
            logger.error(f"{log_prefix} Failed to decrypt/download image: {e}", exc_info=True)
            return [{"type": "text", "text": f"Error: Failed to access image {embed_id} — {e}"}]
        except Exception as e:
            logger.error(f"{log_prefix} Unexpected error during image load: {e}", exc_info=True)
            return [{"type": "text", "text": f"Error: Image loading failed for {embed_id} — {e}"}]
