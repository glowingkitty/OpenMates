# backend/upload/services/s3_upload.py
#
# Lightweight S3 upload wrapper for the uploads microservice.
#
# Uses the same Hetzner S3-compatible storage as the core API's S3UploadService,
# but implemented here independently to keep the uploads service self-contained
# without pulling in the entire core API dependency graph.
#
# Credentials are fetched from the LOCAL HashiCorp Vault KV (on the uploads VM):
#   kv/data/providers/hetzner: s3_access_key, s3_secret_key, s3_region_name
#
# The local Vault is populated by vault-setup from SECRET__* env vars at startup.
# This service NEVER contacts the main Vault on the core server.
#
# Bucket: 'chatfiles' — same bucket used by AI-generated images.
# S3 key format: {user_id}/{content_hash}/{variant}.bin
#   e.g. user-uuid-123/sha256abc.../original.bin
#        user-uuid-123/sha256abc.../preview.bin

import logging
import os
from typing import Optional

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
import httpx

logger = logging.getLogger(__name__)


class UploadsS3Service:
    """
    S3 upload/download service for the uploads microservice.
    Initialised asynchronously via initialize() during app startup.
    Fetches credentials from the local Vault KV (not the main server Vault).
    """

    def __init__(self) -> None:
        # Local Vault on the uploads VM (same docker-compose network)
        self.vault_url = os.environ.get("VAULT_URL", "http://vault:8200")
        self.vault_token_path = "/vault-data/api.token"
        self.client = None
        self.region_name: Optional[str] = None
        self.endpoint_url: Optional[str] = None
        self.base_domain: Optional[str] = None
        # Per-environment bucket names — the upload service is shared across
        # dev and prod, so we initialise BOTH buckets at startup and select
        # the correct one per-request via get_bucket_for_env().
        self.bucket_name_prod: str = "openmates-chatfiles"
        self.bucket_name_dev: str = "dev-openmates-chatfiles"
        # Legacy: kept for callers that don't pass an env (defaults to prod for safety)
        self.bucket_name: Optional[str] = None

    def _load_vault_token(self) -> str:
        """Load the Vault API token from the shared token file (written by vault-setup)."""
        try:
            with open(self.vault_token_path, "r") as f:
                token = f.read().strip()
            if not token:
                raise RuntimeError("Vault token file is empty")
            return token
        except FileNotFoundError as e:
            logger.error(
                f"[S3Upload] Vault token file not found at {self.vault_token_path}. "
                f"Ensure the local vault-setup container has run successfully."
            )
            raise RuntimeError("Vault token file not found") from e

    async def _fetch_secret(self, path: str, key: str) -> Optional[str]:
        """Fetch a single secret from the local Vault KV."""
        token = self._load_vault_token()
        url = f"{self.vault_url}/v1/{path}"
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(url, headers={"X-Vault-Token": token})
                resp.raise_for_status()
                return resp.json()["data"]["data"].get(key)
        except Exception as e:
            logger.error(f"[S3Upload] Failed to fetch secret {path}/{key}: {e}", exc_info=True)
            raise

    async def initialize(self) -> None:
        """
        Fetch S3 credentials from local Vault and initialise the boto3 client.
        Called once during FastAPI app startup (lifespan).
        """
        logger.info("[S3Upload] Initialising S3 service (credentials from local Vault)...")

        access_key = await self._fetch_secret("kv/data/providers/hetzner", "s3_access_key")
        secret_key = await self._fetch_secret("kv/data/providers/hetzner", "s3_secret_key")
        region = await self._fetch_secret("kv/data/providers/hetzner", "s3_region_name")

        if not access_key or not secret_key:
            raise RuntimeError("[S3Upload] S3 credentials not found in local Vault")

        self.region_name = region or "nbg1"
        self.endpoint_url = f"https://{self.region_name}.your-objectstorage.com"

        from urllib.parse import urlparse
        self.base_domain = urlparse(self.endpoint_url).netloc

        # The upload service is shared across dev and prod environments.
        # Both bucket names are known at startup (no env-based selection here).
        # Per-request bucket selection uses get_bucket_for_env(target_env).
        # Legacy self.bucket_name defaults to prod for backward compatibility.
        self.bucket_name = self.bucket_name_prod

        config = Config(
            signature_version="s3v4",
            s3={"addressing_style": "path"},
            connect_timeout=30,
            read_timeout=30,
            retries={"max_attempts": 3},
        )

        self.client = boto3.client(
            "s3",
            endpoint_url=self.endpoint_url,
            region_name=self.region_name,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            config=config,
        )

        logger.info(
            f"[S3Upload] Initialised — bucket: {self.bucket_name}, "
            f"region: {self.region_name}, endpoint: {self.endpoint_url}"
        )

    def get_bucket_for_env(self, target_env: str = "prod") -> str:
        """
        Return the correct S3 bucket name for the given environment.

        The upload service is shared across dev and prod. Caddy injects
        X-Target-Env ("dev" or "prod") per request, which flows through to
        this method so uploads go to the correct bucket.

        Args:
            target_env: "dev" or "prod" (from X-Target-Env header).

        Returns:
            The bucket name for the specified environment.
        """
        if target_env == "dev":
            return self.bucket_name_dev
        return self.bucket_name_prod

    async def upload_file(
        self,
        s3_key: str,
        content: bytes,
        content_type: str = "application/octet-stream",
        target_env: str = "prod",
    ) -> str:
        """
        Upload encrypted file bytes to S3.

        Args:
            s3_key: Full S3 object key (e.g. "user-uuid/hash/original.bin").
            content: AES-GCM encrypted file bytes to store.
            content_type: MIME type for S3 metadata (informational only; all uploads
                          are stored as application/octet-stream since content is encrypted).
            target_env: "dev" or "prod" — selects the correct S3 bucket.

        Returns:
            The S3 object key (same as s3_key input) for storage in embed metadata.

        Raises:
            RuntimeError: If the client is not initialised or the upload fails.
        """
        if self.client is None:
            raise RuntimeError("[S3Upload] S3 client not initialised — call initialize() first")

        bucket = self.get_bucket_for_env(target_env)
        import asyncio

        def _put() -> None:
            self.client.put_object(
                Bucket=bucket,
                Key=s3_key,
                Body=content,
                ContentType="application/octet-stream",  # Always octet-stream since encrypted
                ACL="public-read",  # Required for direct browser fetches — matches core API's S3UploadService
            )

        try:
            await asyncio.to_thread(_put)
            logger.info(
                f"[S3Upload] Uploaded {len(content)} bytes → s3://{bucket}/{s3_key}"
            )
            return s3_key
        except ClientError as e:
            logger.error(
                f"[S3Upload] Upload failed for key {s3_key} (bucket={bucket}): {e}", exc_info=True
            )
            raise RuntimeError(f"S3 upload failed: {e}") from e

    async def check_file_exists(self, s3_key: str, target_env: str = "prod") -> bool:
        """
        Check whether an object exists in the S3 bucket without downloading it.

        Used to validate deduplication hits — a stored record may reference S3
        objects that were never actually uploaded (e.g. due to a prior bucket
        misconfiguration). If the head_object call returns 404 the record is stale.

        Args:
            s3_key: The S3 object key to check.
            target_env: "dev" or "prod" — selects the correct S3 bucket.

        Returns True if the object exists, False otherwise.
        Does NOT raise — any error (network, permissions) is treated as "not found"
        so the caller falls back to a fresh upload rather than returning a broken record.
        """
        if self.client is None:
            return False

        bucket = self.get_bucket_for_env(target_env)
        import asyncio

        def _head() -> bool:
            try:
                self.client.head_object(Bucket=bucket, Key=s3_key)
                return True
            except ClientError as e:
                error_code = e.response.get("Error", {}).get("Code", "")
                if error_code in ("404", "NoSuchKey"):
                    return False
                # Any other error (permissions, network): treat as not found
                logger.warning(f"[S3Upload] head_object error for {s3_key}: {e}")
                return False

        try:
            return await asyncio.to_thread(_head)
        except Exception as e:
            logger.warning(f"[S3Upload] check_file_exists failed for {s3_key}: {e}")
            return False

    def get_base_url(self, target_env: str = "prod") -> str:
        """
        Return the base URL for constructing full file URLs (for embed content).

        Args:
            target_env: "dev" or "prod" — selects the correct S3 bucket.
        """
        bucket = self.get_bucket_for_env(target_env)
        return f"https://{bucket}.{self.base_domain}"
