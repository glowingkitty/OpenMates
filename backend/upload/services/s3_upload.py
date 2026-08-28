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

import asyncio
import hashlib
import logging
import os
from typing import NamedTuple, Optional
from urllib.parse import urlparse

import boto3
from botocore.config import Config
from botocore.exceptions import (
    ClientError,
    ConnectionClosedError,
    ConnectTimeoutError,
    EndpointConnectionError,
    HTTPClientError,
    ReadTimeoutError,
)
import httpx

from backend.shared.python_utils.object_storage_regions import (
    RETRYABLE_STORAGE_ERROR_CODES,
    endpoint_for_region,
    is_retryable_storage_error,
    parse_storage_regions,
    resolve_regional_bucket_name,
)

logger = logging.getLogger(__name__)


class StoredS3Object(NamedTuple):
    """Internal upload result with the region that accepted the ciphertext."""

    key: str
    region: str


RETRYABLE_UPLOAD_ERROR_CODES = set(RETRYABLE_STORAGE_ERROR_CODES)
RETRYABLE_UPLOAD_TRANSPORT_ERRORS = (
    ConnectionClosedError,
    ConnectTimeoutError,
    EndpointConnectionError,
    HTTPClientError,
    ReadTimeoutError,
)


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
        self.region_clients = {}
        self.configured_regions: tuple[str, ...] = ()
        self.region_name: Optional[str] = None
        self.endpoint_url: Optional[str] = None
        self.base_domain: Optional[str] = None
        # Per-environment bucket names for chat files — the upload service is shared
        # across dev and prod, so we initialise BOTH buckets at startup and select
        # the correct one per-request via get_bucket_for_env().
        self.bucket_name_prod: str = "openmates-chatfiles"
        self.bucket_name_dev: str = "dev-openmates-chatfiles"
        # Per-environment bucket names for private, AES-256-GCM encrypted profile images.
        # Bytes are encrypted before upload; decrypted server-side on GET /v1/users/{id}/profile-image.
        self.profile_private_bucket_name_prod: str = "openmates-profile-images-private"
        self.profile_private_bucket_name_dev: str = "dev-openmates-profile-images-private"
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
        configured_regions = parse_storage_regions(os.getenv("S3_REGIONS"))
        self.configured_regions = configured_regions
        if self.region_name not in configured_regions:
            raise ValueError("Active S3 region must be present in S3_REGIONS")
        self.endpoint_url = endpoint_for_region(self.region_name)

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

        self.region_clients = {
            configured_region: boto3.client(
                "s3",
                endpoint_url=endpoint_for_region(configured_region),
                region_name=configured_region,
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                config=config,
            )
            for configured_region in configured_regions
        }
        self.client = self.region_clients[self.region_name]

        logger.info(
            f"[S3Upload] Initialised — bucket: {self.bucket_name}, "
            f"region: {self.region_name}, endpoint: {self.endpoint_url}"
        )

        # ARCHITECTURE: All buckets are PRIVATE.
        # Encrypted blobs are served via API proxy or presigned URLs generated by the API.
        #
        # Chatfiles: ACL 'private' — encrypted blobs, served via presigned URLs for
        # client-side AES-GCM decryption (GET /v1/embeds/presigned-url).
        #
        # Profile images (private bucket): ACL 'private' — bytes are AES-256-GCM
        # encrypted before upload. Served via GET /v1/users/{id}/profile-image
        # (authenticated API proxy that decrypts server-side).
        for bucket_name in (
            self.get_bucket_for_env("dev"),
            self.get_bucket_for_env("prod"),
        ):
            try:
                self.client.put_bucket_acl(Bucket=bucket_name, ACL="private")
                logger.info(f"[S3Upload] Set private ACL on chatfiles bucket '{bucket_name}'")
            except ClientError as acl_e:
                logger.warning(
                    f"[S3Upload] Failed to set private ACL on chatfiles bucket '{bucket_name}': {acl_e}."
                )

        # New private profile-images buckets — encrypted bytes, no anonymous access.
        for bucket_name in (
            self.get_profile_private_bucket_for_env("dev"),
            self.get_profile_private_bucket_for_env("prod"),
        ):
            try:
                self.client.put_bucket_acl(Bucket=bucket_name, ACL="private")
                logger.info(f"[S3Upload] Set private ACL on private profile bucket '{bucket_name}'")
            except ClientError as acl_e:
                logger.warning(
                    f"[S3Upload] Failed to set private ACL on private profile bucket '{bucket_name}': {acl_e}."
                )

    def get_bucket_for_env(self, target_env: str = "prod", *, region: str | None = None) -> str:
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
        legacy_bucket = self.bucket_name_dev if target_env == "dev" else self.bucket_name_prod
        selected_region = region or self.region_name
        if not selected_region:
            raise RuntimeError("[S3Upload] Active S3 region is not configured")
        return resolve_regional_bucket_name(legacy_bucket, selected_region)

    def _candidate_upload_regions(self, preferred_region: str | None = None) -> tuple[str, ...]:
        configured_regions = self.configured_regions or tuple(self.region_clients)
        selected_preference = preferred_region or self.region_name
        if not selected_preference:
            return tuple(configured_regions)
        return (selected_preference,) + tuple(
            region for region in configured_regions if region != selected_preference
        )

    def _bucket_for_logical_name(self, logical_bucket: str, target_env: str, region: str) -> str:
        if logical_bucket == "profile_images_private":
            return self.get_profile_private_bucket_for_env(target_env, region=region)
        if logical_bucket == "chatfiles":
            return self.get_bucket_for_env(target_env, region=region)
        raise RuntimeError(f"[S3Upload] Unsupported replicated bucket: {logical_bucket}")

    async def _delete_written_object(
        self,
        *,
        logical_bucket: str,
        object_key: str,
        target_env: str,
        region: str,
        client: object,
    ) -> None:
        bucket = self._bucket_for_logical_name(logical_bucket, target_env, region)
        await asyncio.to_thread(
            client.delete_object,
            Bucket=bucket,
            Key=object_key,
        )

    async def _persist_replication_outbox(
        self,
        *,
        logical_bucket: str,
        object_key: str,
        content: bytes,
        target_env: str,
        cleanup_on_failure: bool,
        active_region: str | None = None,
        active_client: object | None = None,
    ) -> None:
        if target_env == "dev":
            core_api_url = os.environ.get("DEV_CORE_API_URL", "")
            internal_token = os.environ.get("DEV_INTERNAL_API_SHARED_TOKEN", "")
        else:
            core_api_url = os.environ.get("PROD_CORE_API_URL", "http://api:8000")
            internal_token = os.environ.get("PROD_INTERNAL_API_SHARED_TOKEN", "")
        selected_region = active_region or self.region_name
        selected_client = active_client or self.client
        if not core_api_url or not internal_token or not selected_region:
            raise RuntimeError("[S3Upload] Durable replication outbox is unavailable")

        outbox_url = f"{core_api_url.rstrip('/')}/internal/storage/replication-jobs"
        outbox_headers = {"X-Internal-Service-Token": internal_token}
        outbox_payload = {
            "logical_bucket": logical_bucket,
            "object_key": object_key,
            "generation": 1,
            "checksum": hashlib.sha256(content).hexdigest(),
            "active_region": selected_region,
        }

        async def _post_outbox_once() -> None:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.post(
                    outbox_url,
                    headers=outbox_headers,
                    json=outbox_payload,
                )
                response.raise_for_status()

        async def _cleanup_after_outbox_failure() -> None:
            if not cleanup_on_failure or selected_client is None:
                return
            try:
                await self._delete_written_object(
                    logical_bucket=logical_bucket,
                    object_key=object_key,
                    target_env=target_env,
                    region=selected_region,
                    client=selected_client,
                )
            except Exception as cleanup_error:
                logger.error(
                    "[S3Upload] Failed to remove object after outbox failure: logical_bucket=%s region=%s error=%s",
                    logical_bucket,
                    selected_region,
                    type(cleanup_error).__name__,
                )
                raise RuntimeError("[S3Upload] Durable replication outbox is unavailable and cleanup failed") from cleanup_error

        try:
            await _post_outbox_once()
        except httpx.TransportError as transport_error:
            try:
                await _post_outbox_once()
                return
            except httpx.HTTPStatusError as retry_status_error:
                status_code = retry_status_error.response.status_code
                logger.error(
                    "[S3Upload] Replication outbox transport status remained ambiguous after retry: status=%s",
                    status_code,
                )
                raise RuntimeError("[S3Upload] Durable replication outbox status is ambiguous") from retry_status_error
            except httpx.TransportError as retry_error:
                logger.error(
                    "[S3Upload] Replication outbox transport status remained ambiguous after retry: retry_error=%s",
                    type(retry_error).__name__,
                )
                raise RuntimeError("[S3Upload] Durable replication outbox status is ambiguous") from retry_error
            except Exception as retry_error:
                logger.error(
                    "[S3Upload] Replication outbox transport status remained ambiguous after retry: retry_error=%s",
                    type(retry_error).__name__,
                )
                raise RuntimeError("[S3Upload] Durable replication outbox status is ambiguous") from retry_error
            finally:
                transport_error.add_note("Initial outbox request failed before retry")
        except httpx.HTTPStatusError as status_error:
            status_code = status_error.response.status_code
            if 500 <= status_code < 600:
                try:
                    await _post_outbox_once()
                    return
                except Exception as retry_error:
                    logger.error(
                        "[S3Upload] Replication outbox status remained ambiguous after retry: status=%s retry_error=%s",
                        status_code,
                        type(retry_error).__name__,
                    )
                    raise RuntimeError("[S3Upload] Durable replication outbox status is ambiguous") from retry_error
            await _cleanup_after_outbox_failure()
            raise RuntimeError("[S3Upload] Durable replication outbox is unavailable") from status_error
        except Exception as exc:
            await _cleanup_after_outbox_failure()
            if isinstance(exc, RuntimeError):
                raise
            raise RuntimeError("[S3Upload] Durable replication outbox is unavailable") from exc

    async def _record_region_error(
        self,
        *,
        target_env: str,
        region: str,
        error_code: str,
        http_status: int | None = None,
    ) -> None:
        if target_env == "dev":
            core_api_url = os.environ.get("DEV_CORE_API_URL", "")
            internal_token = os.environ.get("DEV_INTERNAL_API_SHARED_TOKEN", "")
        else:
            core_api_url = os.environ.get("PROD_CORE_API_URL", "http://api:8000")
            internal_token = os.environ.get("PROD_INTERNAL_API_SHARED_TOKEN", "")
        if not core_api_url or not internal_token:
            logger.warning("[S3Upload] Cannot record storage region health without core API configuration")
            return
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.post(
                    f"{core_api_url.rstrip('/')}/internal/storage/region-errors",
                    headers={"X-Internal-Service-Token": internal_token},
                    json={
                        "region": region,
                        "error_code": error_code,
                        "http_status": http_status,
                    },
                )
                response.raise_for_status()
        except Exception as error:
            logger.warning(
                "[S3Upload] Failed to record storage region health: region=%s error=%s",
                region,
                type(error).__name__,
            )

    async def _upload_replicated_object(
        self,
        *,
        logical_bucket: str,
        s3_key: str,
        content: bytes,
        target_env: str,
        preferred_region: str | None = None,
        cache_control: str | None = None,
        allow_region_fallback: bool = True,
    ) -> StoredS3Object:
        if self.client is None:
            raise RuntimeError("[S3Upload] S3 client not initialised — call initialize() first")

        content_checksum = hashlib.sha256(content).hexdigest()
        candidate_regions = self._candidate_upload_regions(preferred_region)
        if not allow_region_fallback and preferred_region:
            candidate_regions = (preferred_region,)
        last_error: BaseException | None = None

        async def _probe_ambiguous_write(active_client: object, bucket: str) -> str:
            try:
                existing = await asyncio.to_thread(
                    active_client.head_object,
                    Bucket=bucket,
                    Key=s3_key,
                )
            except ClientError as head_error:
                head_code = str(head_error.response.get("Error", {}).get("Code") or "")
                if head_code in {"404", "NoSuchKey"}:
                    return "missing"
                raise RuntimeError("S3 upload write status is ambiguous after failed verification") from head_error
            except RETRYABLE_UPLOAD_TRANSPORT_ERRORS as head_error:
                raise RuntimeError("S3 upload write status is ambiguous after failed verification") from head_error
            if (existing.get("Metadata") or {}).get("openmates-sha256") == content_checksum:
                return "matching"
            raise RuntimeError("Immutable storage key already exists with different content")

        for index, active_region in enumerate(candidate_regions):
            active_client = self.region_clients.get(active_region)
            if active_client is None:
                continue
            bucket = self._bucket_for_logical_name(logical_bucket, target_env, active_region)
            cleanup_on_failure = True
            put_parameters = {
                "Bucket": bucket,
                "Key": s3_key,
                "Body": content,
                "ContentType": "application/octet-stream",
                "ACL": "private",
                "Metadata": {"openmates-sha256": content_checksum},
                "IfNoneMatch": "*",
            }
            if cache_control:
                put_parameters["CacheControl"] = cache_control

            try:
                await asyncio.to_thread(active_client.put_object, **put_parameters)
            except ClientError as error:
                error_code = str(error.response.get("Error", {}).get("Code") or "")
                http_status = (error.response.get("ResponseMetadata") or {}).get("HTTPStatusCode")
                if error_code in {"PreconditionFailed", "412"}:
                    if await _probe_ambiguous_write(active_client, bucket) != "matching":
                        raise RuntimeError("Immutable storage key already exists with different content") from error
                    cleanup_on_failure = False
                elif is_retryable_storage_error(error_code, http_status):
                    try:
                        probe_result = await _probe_ambiguous_write(active_client, bucket)
                    except RuntimeError:
                        await self._record_region_error(
                            target_env=target_env,
                            region=active_region,
                            error_code=error_code,
                            http_status=http_status,
                        )
                        raise
                    if probe_result == "matching":
                        cleanup_on_failure = False
                    else:
                        last_error = error
                        await self._record_region_error(
                            target_env=target_env,
                            region=active_region,
                            error_code=error_code,
                            http_status=http_status,
                        )
                    if probe_result != "matching" and index + 1 < len(candidate_regions):
                        logger.warning(
                            "[S3Upload] Retryable regional upload failure; trying fallback region=%s error=%s",
                            active_region,
                            error_code,
                        )
                        continue
                    if probe_result != "matching":
                        raise RuntimeError(f"S3 upload failed: {error}") from error
                else:
                    raise RuntimeError(f"S3 upload failed: {error}") from error
            except RETRYABLE_UPLOAD_TRANSPORT_ERRORS as error:
                try:
                    probe_result = await _probe_ambiguous_write(active_client, bucket)
                except RuntimeError:
                    await self._record_region_error(
                        target_env=target_env,
                        region=active_region,
                        error_code=type(error).__name__,
                    )
                    raise
                if probe_result == "matching":
                    logger.info("[S3Upload] Transport failure followed by matching immutable object head")
                    cleanup_on_failure = False
                    last_error = None
                else:
                    last_error = error
                    await self._record_region_error(
                        target_env=target_env,
                        region=active_region,
                        error_code=type(error).__name__,
                    )
                if probe_result != "matching" and index + 1 < len(candidate_regions):
                    logger.warning(
                        "[S3Upload] Retryable regional upload transport failure; trying fallback region=%s error=%s",
                        active_region,
                        type(error).__name__,
                    )
                    continue
                if probe_result != "matching":
                    raise RuntimeError(f"S3 upload failed: {type(error).__name__}") from error

            await self._persist_replication_outbox(
                logical_bucket=logical_bucket,
                object_key=s3_key,
                content=content,
                target_env=target_env,
                cleanup_on_failure=cleanup_on_failure,
                active_region=active_region,
                active_client=active_client,
            )
            logger.info("[S3Upload] Uploaded encrypted object: size=%s region=%s", len(content), active_region)
            return StoredS3Object(key=s3_key, region=active_region)
        raise RuntimeError("S3 upload failed in every configured region") from last_error

    async def upload_file_with_region(
        self,
        s3_key: str,
        content: bytes,
        content_type: str = "application/octet-stream",
        target_env: str = "prod",
        preferred_region: str | None = None,
        allow_region_fallback: bool = True,
    ) -> StoredS3Object:
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
        return await self._upload_replicated_object(
            logical_bucket="chatfiles",
            s3_key=s3_key,
            content=content,
            target_env=target_env,
            preferred_region=preferred_region,
            allow_region_fallback=allow_region_fallback,
        )

    async def upload_file(
        self,
        s3_key: str,
        content: bytes,
        content_type: str = "application/octet-stream",
        target_env: str = "prod",
    ) -> str:
        result = await self.upload_file_with_region(
            s3_key=s3_key,
            content=content,
            content_type=content_type,
            target_env=target_env,
        )
        return result.key

    async def check_file_exists(
        self,
        s3_key: str,
        target_env: str = "prod",
        *,
        region: str | None = None,
    ) -> bool:
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
        if self.client is None and not self.region_clients:
            return False

        selected_region = region or self.region_name
        if selected_region is None:
            return False
        selected_client = self.region_clients.get(selected_region)
        if selected_client is None:
            return False
        bucket = self.get_bucket_for_env(target_env, region=selected_region)
        import asyncio

        def _head() -> bool:
            try:
                selected_client.head_object(Bucket=bucket, Key=s3_key)
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

    def generate_presigned_url(
        self,
        s3_key: str,
        target_env: str = "prod",
        expiration: int = 900,
    ) -> str:
        """
        Generate a presigned URL for downloading a private S3 object.

        Used by the REST API to provide time-limited download URLs for chatfiles
        (encrypted images, PDFs, audio). The client fetches the ciphertext via this
        URL and decrypts client-side with AES-256-GCM.

        Args:
            s3_key: Full S3 object key (e.g. "user-uuid/hash/original.bin").
            target_env: "dev" or "prod" — selects the correct S3 bucket.
            expiration: URL validity in seconds (default: 15 minutes).

        Returns:
            A presigned HTTPS URL that grants temporary anonymous GET access.

        Raises:
            RuntimeError: If the client is not initialised.
        """
        if self.client is None:
            raise RuntimeError("[S3Upload] S3 client not initialised — call initialize() first")

        bucket = self.get_bucket_for_env(target_env)
        try:
            url = self.client.generate_presigned_url(
                "get_object",
                Params={"Bucket": bucket, "Key": s3_key},
                ExpiresIn=expiration,
            )
            return url
        except ClientError as e:
            logger.error(f"[S3Upload] Failed to generate presigned URL for {s3_key}: {e}")
            raise RuntimeError(f"Presigned URL generation failed: {e}") from e

    def get_base_url(self, target_env: str = "prod", *, region: str | None = None) -> str:
        """
        Return the base URL for constructing full file URLs (for embed content).

        Args:
            target_env: "dev" or "prod" — selects the correct S3 bucket.
        """
        selected_region = region or self.region_name
        bucket = self.get_bucket_for_env(target_env, region=selected_region)
        base_domain = urlparse(endpoint_for_region(selected_region)).netloc
        return f"https://{bucket}.{base_domain}"

    def get_profile_private_bucket_for_env(self, target_env: str = "prod", *, region: str | None = None) -> str:
        """
        Return the correct private profile-images bucket name for the given environment.

        New profile image uploads (AES-256-GCM encrypted) go here instead of the
        legacy public-read bucket.  The core API decrypts and proxies these via
        GET /v1/users/{user_id}/profile-image.

        Args:
            target_env: "dev" or "prod" (from X-Target-Env header).

        Returns:
            The private profile-images bucket name for the specified environment.
        """
        legacy_bucket = (
            self.profile_private_bucket_name_dev
            if target_env == "dev"
            else self.profile_private_bucket_name_prod
        )
        selected_region = region or self.region_name
        if not selected_region:
            raise RuntimeError("[S3Upload] Active S3 region is not configured")
        return resolve_regional_bucket_name(legacy_bucket, selected_region)

    async def upload_profile_image_private_with_region(
        self,
        s3_key: str,
        content: bytes,
        target_env: str = "prod",
        preferred_region: str | None = None,
        allow_region_fallback: bool = True,
    ) -> StoredS3Object:
        """
        Upload AES-256-GCM encrypted profile image bytes to the private bucket.

        Unlike upload_profile_image() (legacy, public-read), this method:
          - Uses the private profile-images bucket (no anonymous read access)
          - Stores the encrypted blob as application/octet-stream
          - Returns the S3 key (not a public URL) — the caller uses the key
            for Directus storage and deletion on re-upload

        Args:
            s3_key: S3 object key (e.g. "{user_id}-{timestamp}-{random}.enc").
            content: AES-256-GCM encrypted image bytes.
            target_env: "dev" or "prod" — selects the correct S3 bucket.

        Returns:
            The S3 object key (same as s3_key input).

        Raises:
            RuntimeError: If the client is not initialised or the upload fails.
        """
        return await self._upload_replicated_object(
            logical_bucket="profile_images_private",
            s3_key=s3_key,
            content=content,
            target_env=target_env,
            preferred_region=preferred_region,
            cache_control="no-cache, no-store, must-revalidate",
            allow_region_fallback=allow_region_fallback,
        )

    async def upload_profile_image_private(
        self,
        s3_key: str,
        content: bytes,
        target_env: str = "prod",
    ) -> str:
        result = await self.upload_profile_image_private_with_region(
            s3_key=s3_key,
            content=content,
            target_env=target_env,
        )
        return result.key

    async def delete_profile_image_private(
        self,
        s3_key: str,
        target_env: str = "prod",
    ) -> None:
        """
        Delete an encrypted profile image from the private bucket.

        Called by the upload route (via core API internal endpoint) when a user
        re-uploads their profile image — the old encrypted object must be removed
        to prevent orphaned blobs from accumulating in the private bucket.

        Args:
            s3_key: S3 object key of the encrypted profile image to delete.
            target_env: "dev" or "prod" — selects the correct S3 bucket.

        Raises:
            RuntimeError: If the client is not initialised or the deletion fails.
        """
        if self.client is None:
            raise RuntimeError("[S3Upload] S3 client not initialised — call initialize() first")

        bucket = self.get_profile_private_bucket_for_env(target_env)
        import asyncio

        def _delete() -> None:
            self.client.delete_object(Bucket=bucket, Key=s3_key)  # type: ignore[union-attr]

        try:
            await asyncio.to_thread(_delete)
            logger.info(
                f"[S3Upload] Deleted old private profile image "
                f"s3://{bucket}/{s3_key}"
            )
        except ClientError as e:
            logger.error(
                f"[S3Upload] Failed to delete private profile image {s3_key} "
                f"(bucket={bucket}): {e}",
                exc_info=True,
            )
            raise RuntimeError(f"S3 private profile image deletion failed: {e}") from e
