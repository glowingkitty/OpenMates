# backend/apps/images/skills/view_skill.py
#
# Skill that loads an uploaded/generated image so the main LLM can see it.
#
# Architecture:
#   The LLM calls this skill with only an embed_id. The skill then:
#     1. Looks up the embed's encrypted content from the Redis cache
#     2. Decrypts the embed content using the user's Vault Transit key
#     3. Extracts vault_wrapped_aes_key, s3_key, s3_base_url, aes_nonce from
#        the decrypted embed content (these fields are never exposed to the LLM)
#     4. Unwraps the AES key via Vault Transit
#     5. Downloads the encrypted file from S3
#     6. Decrypts with AES-256-GCM
#     7. Returns the image as a multimodal content list (image_url block)
#        so the MAIN inference model sees the image directly via tool result
#
#   This design keeps all cryptographic and infrastructure details (S3 keys,
#   Vault-wrapped AES keys, nonces) entirely server-side. The LLM only needs
#   to know the embed_id to request viewing an image.
#
#   Security:
#     - The plaintext aes_key (used by the client) is never sent to the LLM.
#     - vault_wrapped_aes_key, s3_key, aes_nonce are resolved server-side,
#       not passed through the LLM context or tool call.
#     - Plaintext image bytes exist only transiently in memory during this call.

import base64
import json as json_lib
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
    The LLM only needs to provide the embed_id — all cryptographic and
    storage details are resolved server-side from the embed cache.
    """
    embed_id: str = Field(
        ...,
        description="The embed_id of the image to load into the conversation."
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
    Skill for loading an image and returning it as a multimodal content block
    so the main inference model can see it directly.

    The LLM calls this with only embed_id. The skill resolves all crypto and
    storage details server-side by looking up the embed from the Redis cache
    and decrypting its content via Vault Transit.

    Returns the raw image bytes (base64-encoded) as an image_url content block.
    The framework's llm_utils.py passes the list through unchanged to the
    provider adapters, which convert the image_url block to the correct format
    for the active LLM (Anthropic image source, Google inlineData, etc.).
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

    async def _lookup_embed_content(
        self, embed_id: str, user_vault_key_id: str
    ) -> Dict[str, Any]:
        """
        Look up an embed's decrypted content from the Redis cache.

        The embed is stored in Redis at key ``embed:{embed_id}`` as a JSON dict
        with an ``encrypted_content`` field that holds a Vault Transit-encrypted
        TOON string. This method decrypts the content using the user's Vault key
        and decodes the TOON to return the raw content dict.

        Args:
            embed_id: The embed ID to look up.
            user_vault_key_id: The user's Vault Transit key ID for decryption.

        Returns:
            Decoded embed content dict (contains vault_wrapped_aes_key, s3_base_url,
            files, aes_nonce, etc.).

        Raises:
            RuntimeError: If the embed is not found in cache, has no encrypted
                content, or decryption/decoding fails.
        """
        import redis.asyncio as aioredis
        from toon_format import decode as toon_decode
        from urllib.parse import quote as url_quote

        log_prefix = f"[images.view] [embed:{embed_id[:8]}...]"

        # Connect to Redis (same instance used by all backend services)
        redis_password = os.environ.get("DRAGONFLY_PASSWORD", "")
        redis_url = f"redis://default:{url_quote(redis_password, safe='')}@cache:6379/0"
        redis_client = aioredis.from_url(redis_url, decode_responses=True)

        try:
            cache_key = f"embed:{embed_id}"
            embed_json = await redis_client.get(cache_key)
            if not embed_json:
                raise RuntimeError(
                    f"Embed {embed_id} not found in cache — it may have expired "
                    f"(24h TTL). Please ask the user to re-upload the image."
                )

            embed_data = json_lib.loads(embed_json)
            encrypted_content = embed_data.get("encrypted_content")
            if not encrypted_content:
                raise RuntimeError(
                    f"Embed {embed_id} has no encrypted_content in cache"
                )

            # Decrypt the content using Vault Transit (same as EncryptionService.decrypt_with_user_key)
            vault_url = os.environ.get("VAULT_URL", "http://vault:8200")
            token = self._load_vault_token()

            decrypt_url = f"{vault_url}/v1/transit/decrypt/{user_vault_key_id}"
            payload = {"ciphertext": encrypted_content}

            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    decrypt_url,
                    json=payload,
                    headers={"X-Vault-Token": token},
                )

            if resp.status_code != 200:
                raise RuntimeError(
                    f"Vault transit decrypt failed for embed content: "
                    f"HTTP {resp.status_code} — {resp.text[:200]}"
                )

            plaintext_b64 = resp.json()["data"]["plaintext"]
            plaintext_toon = base64.b64decode(plaintext_b64).decode("utf-8")

            # Decode TOON to get the content dict
            decoded = toon_decode(plaintext_toon)
            if not isinstance(decoded, dict):
                raise RuntimeError(
                    f"Embed {embed_id} TOON content decoded to "
                    f"{type(decoded).__name__}, expected dict"
                )

            logger.info(
                f"{log_prefix} Successfully looked up embed from cache "
                f"(keys: {list(decoded.keys())})"
            )
            return decoded

        finally:
            await redis_client.aclose()

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
        **kwargs: Any,
    ) -> List[Dict[str, Any]]:
        """
        Load an image and return it as a multimodal content list.

        The LLM only provides embed_id. All cryptographic and storage details
        (vault_wrapped_aes_key, s3_key, s3_base_url, aes_nonce) are resolved
        server-side by looking up the embed from the Redis cache.

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
        1. Get user_vault_key_id from kwargs (injected by the pipeline).
        2. Look up embed content from Redis cache (decrypt via Vault Transit).
        3. Extract vault_wrapped_aes_key, s3_base_url, s3_key, aes_nonce from content.
        4. Unwrap the AES key via Vault Transit.
        5. Download the encrypted file from S3.
        6. Decrypt with AES-256-GCM.
        7. Return base64-encoded image as a content block list.

        Args:
            embed_id: Embed ID of the image.
            **kwargs: Context injected by the pipeline (user_vault_key_id, user_id, etc.).

        Returns:
            List of content blocks for multimodal tool result, or a text error
            block on failure (for graceful degradation).
        """
        log_prefix = f"[images.view] [embed:{embed_id[:8]}...]"

        # --- Step 1: Resolve user_vault_key_id from pipeline context ---
        user_vault_key_id = kwargs.get("user_vault_key_id")
        if not user_vault_key_id:
            logger.error(f"{log_prefix} user_vault_key_id not available — cannot look up embed")
            return [{"type": "text", "text": f"Error: Cannot view image {embed_id} — vault key ID not available."}]

        try:
            # --- Step 2: Look up embed content from Redis cache ---
            logger.info(f"{log_prefix} Looking up embed content from cache")
            embed_content = await self._lookup_embed_content(embed_id, user_vault_key_id)

            # --- Step 3: Extract required fields from embed content ---
            vault_wrapped_aes_key = embed_content.get("vault_wrapped_aes_key")
            s3_base_url = embed_content.get("s3_base_url")
            aes_nonce = embed_content.get("aes_nonce")
            files = embed_content.get("files", {})
            filename = embed_content.get("filename") or embed_id

            if not vault_wrapped_aes_key:
                raise RuntimeError("Embed content missing vault_wrapped_aes_key")
            if not s3_base_url:
                raise RuntimeError("Embed content missing s3_base_url")
            if not aes_nonce:
                raise RuntimeError("Embed content missing aes_nonce")

            # Prefer the "full" variant (good quality, reasonable size for LLM vision).
            # Fall back to "original" if "full" is not available.
            s3_key = None
            for variant_name in ("full", "original", "preview"):
                variant = files.get(variant_name)
                if variant and variant.get("s3_key"):
                    s3_key = variant["s3_key"]
                    logger.info(f"{log_prefix} Using '{variant_name}' variant: {s3_key}")
                    break

            if not s3_key:
                raise RuntimeError(
                    f"Embed content has no file variants with s3_key "
                    f"(available: {list(files.keys())})"
                )

            # --- Step 4: Unwrap AES key via Vault Transit ---
            logger.info(f"{log_prefix} Unwrapping AES key via Vault transit key {user_vault_key_id}")
            aes_key_bytes = await self._unwrap_aes_key(vault_wrapped_aes_key, user_vault_key_id)

            # --- Step 5: Download encrypted file from S3 ---
            logger.info(f"{log_prefix} Downloading encrypted image from S3: {s3_key}")
            encrypted_bytes = await self._download_from_s3(s3_base_url, s3_key)

            # --- Step 6: Decrypt with AES-256-GCM ---
            nonce_bytes = base64.b64decode(aes_nonce)
            aesgcm = AESGCM(aes_key_bytes)
            plaintext_bytes = aesgcm.decrypt(nonce_bytes, encrypted_bytes, None)
            logger.info(f"{log_prefix} Decrypted image: {len(plaintext_bytes)} bytes")

            # --- Step 7: Encode and return as multimodal content list ---
            image_b64 = base64.b64encode(plaintext_bytes).decode("utf-8")

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
            logger.error(f"{log_prefix} Failed to load image: {e}", exc_info=True)
            return [{"type": "text", "text": f"Error: Failed to access image {embed_id} — {e}"}]
        except Exception as e:
            logger.error(f"{log_prefix} Unexpected error during image load: {e}", exc_info=True)
            return [{"type": "text", "text": f"Error: Image loading failed for {embed_id} — {e}"}]
