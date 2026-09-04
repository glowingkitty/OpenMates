"""
S3 upload service for handling file uploads and storage.
"""
import asyncio
import boto3
import hashlib
import logging
import os
from collections.abc import AsyncIterable, AsyncIterator
from datetime import datetime, timezone
from io import BytesIO
from tempfile import SpooledTemporaryFile
from fastapi import HTTPException
from backend.core.api.app.utils.secrets_manager import SecretsManager # Import SecretsManager (though not used directly here, good for context)
from botocore.config import Config
# Import ClientError and timeout exceptions for exception handling
from botocore.exceptions import (
    ClientError,
    ConnectionClosedError,
    ConnectTimeoutError,
    EndpointConnectionError,
    HTTPClientError,
    ReadTimeoutError,
)
from urllib.parse import urlparse
from typing import Any, Optional, Dict

from backend.shared.python_utils.object_storage_regions import (
    endpoint_for_region,
    is_retryable_storage_error,
    parse_storage_regions,
    resolve_regional_bucket_name,
    RETRYABLE_STORAGE_ERROR_CODES,
    select_temporary_upload_region,
    should_replicate_bucket,
)
from backend.shared.python_utils.storage_availability import (
    STORAGE_AVAILABLE,
    storage_unavailable_error,
)
from backend.core.api.app.services.s3.replication import (
    build_replication_job,
    persist_replication_job,
    record_persisted_region_error,
)
from backend.core.api.app.services.s3.reconciliation import (
    build_deletion_tombstone,
    find_deletion_tombstone,
    persist_deletion_tombstone,
)

# Import necessary config functions and the single-bucket lifecycle function
from .config import BUCKETS, CORS_ENABLED_BUCKETS, get_bucket_config, get_bucket_by_name, get_bucket_name
from .cors import apply_cors_settings
from .lifecycle import apply_lifecycle_policies

logger = logging.getLogger(__name__)

HETZNER_OBJECT_STORAGE_PROVIDER = "Hetzner Object Storage"
EXTERNAL_PROVIDER_DEGRADED = "external_provider_degraded"
INTERNAL_STORAGE_CONFIGURATION = "internal_storage_configuration"
def _stream_sha256(body: Any) -> str:
    digest = hashlib.sha256()
    try:
        while chunk := body.read(1024 * 1024):
            digest.update(chunk)
    finally:
        body.close()
    return digest.hexdigest()
_AUTHORIZATION_ERROR_CODES = {
    "AccessDenied",
    "AuthorizationHeaderMalformed",
    "InvalidAccessKeyId",
    "InvalidSecurity",
    "SignatureDoesNotMatch",
}
_BUCKET_CONFIGURATION_ERROR_CODES = {
    "InvalidBucketName",
    "NoSuchBucket",
    "PermanentRedirect",
}
_TRANSIENT_NETWORK_ERRORS = (
    ConnectionClosedError,
    ConnectTimeoutError,
    EndpointConnectionError,
    HTTPClientError,
    ReadTimeoutError,
)


async def _storage_object_is_tombstoned(
    service: "S3UploadService",
    bucket_name: str,
    object_key: str,
) -> bool:
    if service.directus_service is None:
        return False
    base_bucket = bucket_name
    for region in ("fsn1", "hel1"):
        suffix = f"-{region}"
        if base_bucket.endswith(suffix):
            base_bucket = base_bucket.removesuffix(suffix)
            break
    try:
        logical_bucket, _config = get_bucket_by_name(base_bucket)
    except ValueError:
        return False
    tombstone = await find_deletion_tombstone(
        directus_service=service.directus_service,
        logical_bucket=logical_bucket,
        object_key=object_key,
    )
    return tombstone is not None


class HetznerObjectStorageError(HTTPException):
    """Sanitized terminal upload failure with retry semantics for billing workers."""

    def __init__(self, *, classification: str, retryable: bool, reason: str):
        self.provider = HETZNER_OBJECT_STORAGE_PROVIDER
        self.classification = classification
        self.retryable = retryable
        self.reason = reason
        super().__init__(
            status_code=503 if retryable else 500,
            detail=f"{self.provider}: {reason}",
        )


def classify_hetzner_upload_error(error: BaseException) -> HetznerObjectStorageError:
    """Map observed upload failures without exposing provider response details."""
    if isinstance(error, _TRANSIENT_NETWORK_ERRORS):
        return HetznerObjectStorageError(
            classification=EXTERNAL_PROVIDER_DEGRADED,
            retryable=True,
            reason="connection or timeout failure",
        )

    if isinstance(error, ClientError):
        response = error.response if isinstance(error.response, dict) else {}
        error_details = response.get("Error") or {}
        response_metadata = response.get("ResponseMetadata") or {}
        error_code = str(error_details.get("Code") or "Unknown")
        status_code = response_metadata.get("HTTPStatusCode")

        if is_retryable_storage_error(error_code, status_code):
            is_throttled = (
                status_code == 429
                or "Throttl" in error_code
                or error_code == "SlowDown"
            )
            reason = "request throttled" if is_throttled else "service returned a server error"
            return HetznerObjectStorageError(
                classification=EXTERNAL_PROVIDER_DEGRADED,
                retryable=True,
                reason=reason,
            )

        if error_code in _AUTHORIZATION_ERROR_CODES or status_code in {401, 403}:
            reason = "authentication or permission failure"
        elif error_code in _BUCKET_CONFIGURATION_ERROR_CODES or status_code == 404:
            reason = "bucket configuration failure"
        else:
            reason = "malformed or unsupported storage request"
        return HetznerObjectStorageError(
            classification=INTERNAL_STORAGE_CONFIGURATION,
            retryable=False,
            reason=reason,
        )

    raise TypeError(f"Unsupported Hetzner upload error type: {type(error).__name__}")


class S3UploadService:
    """
    Service for handling file uploads to S3-compatible storage.
    """
    
    def __init__(self, secrets_manager: SecretsManager, directus_service: Any | None = None):
        """
        Initialize the S3 service with SecretsManager. Clients are initialized asynchronously.
        """
        self.secrets_manager = secrets_manager
        self.directus_service = directus_service
        self.client = None
        self.upload_client = None
        self.availability_client = None
        self.region_clients = {}
        self.upload_region_clients = {}
        self.base_domain = None
        self.region_name = None
        self.endpoint_url = None
        self.configured = False
        self.last_availability_status = "not_configured"
        
        # Get current environment - needed before initialization
        self.environment = os.getenv('SERVER_ENVIRONMENT', 'development')

    async def _persist_replication_outbox(
        self,
        *,
        logical_bucket: str,
        object_key: str,
        checksum: str,
        active_region: str,
    ) -> None:
        """Require durable replica intent before acknowledging a replicated write."""
        configured_regions = tuple(self.region_clients)
        if not should_replicate_bucket(logical_bucket):
            return
        if self.directus_service is None:
            raise RuntimeError("Durable replication outbox is unavailable")
        tombstone = await find_deletion_tombstone(
            directus_service=self.directus_service,
            logical_bucket=logical_bucket,
            object_key=object_key,
        )
        if tombstone:
            legacy_bucket = get_bucket_name(logical_bucket, self.environment)
            bucket_name = resolve_regional_bucket_name(legacy_bucket, active_region)
            await asyncio.to_thread(
                self.region_clients[active_region].delete_object,
                Bucket=bucket_name,
                Key=object_key,
            )
            raise RuntimeError("Storage object is authoritatively deleted")
        now = datetime.now(timezone.utc)
        job = build_replication_job(
            logical_bucket=logical_bucket,
            object_key=object_key,
            generation=1,
            checksum=checksum,
            active_region=active_region,
            configured_regions=configured_regions,
            now=now,
        )
        await persist_replication_job(
            directus_service=self.directus_service,
            job=job,
        )

    async def persist_external_upload_replication(
        self,
        *,
        logical_bucket: str,
        object_key: str,
    ) -> None:
        """Persist replica intent for ciphertext written by the upload service."""
        active_region = str(self.region_name)
        legacy_bucket = get_bucket_name(logical_bucket, self.environment)
        bucket_name = resolve_regional_bucket_name(legacy_bucket, active_region)
        head = await asyncio.to_thread(
            self.region_clients[active_region].head_object,
            Bucket=bucket_name,
            Key=object_key,
        )
        checksum = str((head.get("Metadata") or {}).get("openmates-sha256") or "").lower()
        if len(checksum) != 64 or any(character not in "0123456789abcdef" for character in checksum):
            response = await asyncio.to_thread(
                self.region_clients[active_region].get_object,
                Bucket=bucket_name,
                Key=object_key,
            )
            checksum = await asyncio.to_thread(_stream_sha256, response["Body"])
            logger.info("Computed ciphertext checksum for legacy external upload metadata")
        await self._persist_replication_outbox(
            logical_bucket=logical_bucket,
            object_key=object_key,
            checksum=checksum,
            active_region=active_region,
        )

    async def initialize(self, *, configure_buckets: bool = True):
        """
        Asynchronously fetch secrets and initialize S3 clients.

        Bucket, lifecycle, and CORS reconciliation is startup work. Request-time
        callers can skip it after the runtime has already initialized storage.
        """
        logger.info("Initializing S3 service asynchronously...")
        
        # Fetch secrets
        access_key = await self.secrets_manager.get_secret(secret_path="kv/data/providers/hetzner", secret_key="s3_access_key")
        secret_key = await self.secrets_manager.get_secret(secret_path="kv/data/providers/hetzner", secret_key="s3_secret_key")

        if not access_key or not secret_key:
            logger.critical("S3 credentials not found in Secrets Manager. S3 service will be unavailable.")
            # Keep clients as None
            return # Stop initialization

        self.configured = True

        # The legacy region secret remains the active write region during rollout.
        region_secret = await self.secrets_manager.get_secret(secret_path="kv/data/providers/hetzner", secret_key="s3_region_name")
        self.region_name = region_secret if region_secret else 'nbg1'
        configured_regions = parse_storage_regions(os.getenv("S3_REGIONS"))
        if self.region_name not in configured_regions:
            raise ValueError("Active S3 region must be present in S3_REGIONS")
        logger.info("Using active S3 region %s from configured regions %s", self.region_name, configured_regions)
        
        # Build endpoint URL based on region name
        self.endpoint_url = endpoint_for_region(self.region_name)
        
        # Store the base domain for URL generation
        parsed_url = urlparse(self.endpoint_url)
        self.base_domain = parsed_url.netloc

        # Configuration for CORS and general operations (uses s3v4 for compatibility)
        s3v4_config = Config(
            signature_version='s3v4',
            s3={'addressing_style': 'path'},
            connect_timeout=10,
            read_timeout=10,
            retries={'max_attempts': 3}
        )
        self.region_clients = {
            region: boto3.client(
                's3',
                region_name=region,
                endpoint_url=endpoint_for_region(region),
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                config=s3v4_config,
            )
            for region in configured_regions
        }
        self.client = self.region_clients[self.region_name]
        
        # Separate client for uploads with older signature method
        upload_config = Config(
            signature_version='s3',  # Use older signature version which is more lenient
            s3={'addressing_style': 'path'},
            connect_timeout=15,
            read_timeout=15,
            retries={'max_attempts': 3}
        )
        self.upload_region_clients = {
            region: boto3.client(
                's3',
                region_name=region,
                endpoint_url=endpoint_for_region(region),
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                config=upload_config,
            )
            for region in configured_regions
        }
        self.upload_client = self.upload_region_clients[self.region_name]

        availability_config = Config(
            signature_version='s3v4',
            s3={'addressing_style': 'path'},
            connect_timeout=2,
            read_timeout=2,
            retries={'max_attempts': 0},
        )
        self.availability_client = boto3.client(
            's3',
            region_name=self.region_name,
            endpoint_url=self.endpoint_url,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            config=availability_config,
        )
        
        # Store credentials so we can create retry clients with longer timeouts
        self._upload_access_key = access_key
        self._upload_secret_key = secret_key
        
        logger.info("S3 clients created.")

        if configure_buckets:
            await self.reconcile_configuration()
        
        logger.info("S3 service initialization complete.")

    async def reconcile_configuration(self) -> None:
        """Reconcile remote bucket policy without making service startup depend on it."""
        if not self.configured or self.client is None:
            return
        await self._initialize_buckets()
        await self._reconcile_regional_bucket_policies()

    async def check_availability(self) -> str:
        """Run one bounded, non-mutating provider probe and return a sanitized state."""
        if not self.configured or self.availability_client is None:
            self.last_availability_status = "not_configured"
            return self.last_availability_status

        bucket_name = get_bucket_name("chatfiles", self.environment)
        try:
            await asyncio.to_thread(
                self.availability_client.head_bucket,
                Bucket=bucket_name,
            )
        except Exception as exc:
            self.last_availability_status = "unavailable"
            logger.warning("Object storage availability probe failed: %s", type(exc).__name__)
            return self.last_availability_status

        self.last_availability_status = STORAGE_AVAILABLE
        return self.last_availability_status

    async def _initialize_buckets(self): # Make this method async
        """
        Check if configured buckets exist, create them if they don't,
        and apply lifecycle policies. Requires self.client to be initialized.
        """
        if not self.client:
             logger.error("S3 client not initialized. Cannot initialize buckets.")
             return
        logger.info("Initializing S3 buckets...")
        reconciliation_failed = False
        for bucket_key, bucket_config in BUCKETS.items():
            if not bucket_config.get('managed', True):
                continue
            bucket_name = get_bucket_name(bucket_key, self.environment)
            access_type = bucket_config.get('access', 'private') # Default to private

            try:
                # Check if bucket exists
                await asyncio.to_thread(self.client.head_bucket, Bucket=bucket_name)
                logger.info("Active-region bucket exists: logical_bucket=%s", bucket_key)
                bucket_exists = True
            except ClientError as e:
                error_code = e.response.get('Error', {}).get('Code')
                # Common error codes for non-existent buckets
                if error_code == '404' or error_code == 'NoSuchBucket':
                    logger.info("Active-region bucket is missing; creating logical_bucket=%s", bucket_key)
                    try:
                        # Attempt to create the bucket (Hetzner implies region from endpoint)
                        await asyncio.to_thread(self.client.create_bucket, Bucket=bucket_name)
                        logger.info("Created active-region bucket: logical_bucket=%s", bucket_key)
                        # Hetzner Object Storage can be briefly eventually consistent after bucket creation.
                        # Wait before applying ACL/lifecycle so first-start initialization does not fail noisily.
                        await asyncio.sleep(2)
                        bucket_exists = True
                    except ClientError as create_e:
                        logger.error("Failed to create active-region bucket: logical_bucket=%s error=%s", bucket_key, type(create_e).__name__)
                        reconciliation_failed = True
                        bucket_exists = False  # Creation failed
                        continue  # Skip lifecycle for this bucket
                else:
                    # Handle other errors during head_bucket (e.g., permissions)
                    logger.error("Cannot inspect active-region bucket: logical_bucket=%s error=%s", bucket_key, type(e).__name__)
                    reconciliation_failed = True
                    bucket_exists = False  # Unsure about state, assume no for safety
                    continue  # Skip lifecycle for this bucket

            # Reconcile bucket ACL with the current config on every startup.
            # Previously this only ran at creation time, which meant that flipping
            # a bucket's `access` in config.py (e.g. public-read → private after
            # GDPR audit C6) had no effect on buckets that already existed.
            # Running it unconditionally keeps the live state aligned with code.
            if bucket_exists:
                desired_acl = 'public-read' if access_type == 'public-read' else 'private'
                try:
                    await asyncio.to_thread(
                        self.client.put_bucket_acl,
                        Bucket=bucket_name,
                        ACL=desired_acl,
                    )
                    logger.info("Reconciled active-region bucket ACL: logical_bucket=%s acl=%s", bucket_key, desired_acl)
                except ClientError as acl_e:
                    logger.warning(
                        "Failed to reconcile active-region bucket ACL: logical_bucket=%s acl=%s error=%s",
                        bucket_key,
                        desired_acl,
                        type(acl_e).__name__,
                    )
                    reconciliation_failed = True
                    # Continue even if ACL reconciliation fails — object-level ACLs
                    # applied during put_object are the enforced boundary.

        if reconciliation_failed:
            raise RuntimeError("object_storage_reconciliation_failed")

    async def _reconcile_regional_bucket_policies(self) -> None:
        """Apply private ACL, lifecycle, and CORS to existing regional buckets."""
        environment_name = 'dev_name' if self.environment == 'development' else 'name'
        cors_bases = {
            bucket_name
            for bucket_name in CORS_ENABLED_BUCKETS
            if (self.environment == 'development') == bucket_name.startswith('dev-')
        }

        reconciliation_failed = False
        for region, client in self.region_clients.items():
            regional_configs = {}
            cors_buckets = []
            for bucket_key, bucket_config in BUCKETS.items():
                if not bucket_config.get('managed', True):
                    continue
                legacy_name = bucket_config[environment_name]
                bucket_name = resolve_regional_bucket_name(legacy_name, region)
                try:
                    await asyncio.to_thread(client.head_bucket, Bucket=bucket_name)
                except ClientError as exc:
                    error_code = str(exc.response.get('Error', {}).get('Code', ''))
                    if error_code in {'404', 'NoSuchBucket'}:
                        logger.warning("Regional bucket is not provisioned: region=%s logical_bucket=%s", region, bucket_key)
                        continue
                    logger.error(
                        "Cannot inspect regional bucket policy: region=%s logical_bucket=%s error=%s",
                        region,
                        bucket_key,
                        error_code,
                    )
                    reconciliation_failed = True
                    continue
                except _TRANSIENT_NETWORK_ERRORS as exc:
                    logger.warning(
                        "Regional bucket inspection is degraded: region=%s logical_bucket=%s error=%s",
                        region,
                        bucket_key,
                        type(exc).__name__,
                    )
                    reconciliation_failed = True
                    continue

                desired_acl = 'public-read' if bucket_config.get('access') == 'public-read' else 'private'
                try:
                    await asyncio.to_thread(client.put_bucket_acl, Bucket=bucket_name, ACL=desired_acl)
                except ClientError as exc:
                    logger.error(
                        "Cannot reconcile regional bucket ACL: region=%s logical_bucket=%s error=%s",
                        region,
                        bucket_key,
                        str(exc.response.get('Error', {}).get('Code', 'unknown')),
                    )
                    reconciliation_failed = True
                    continue
                regional_config = dict(bucket_config)
                regional_config['name'] = bucket_name
                regional_config['dev_name'] = bucket_name
                regional_configs[bucket_key] = regional_config
                if legacy_name in cors_bases:
                    cors_buckets.append(bucket_name)

            if regional_configs:
                try:
                    await asyncio.to_thread(
                        apply_lifecycle_policies,
                        client,
                        regional_configs,
                        self.environment,
                    )
                except Exception as exc:
                    logger.error("Cannot reconcile lifecycle policy for region=%s: %s", region, type(exc).__name__)
                    reconciliation_failed = True
            if cors_buckets:
                try:
                    await asyncio.to_thread(apply_cors_settings, client, cors_buckets)
                except Exception as exc:
                    logger.error("Cannot reconcile CORS policy for region=%s: %s", region, type(exc).__name__)
                    reconciliation_failed = True

        if reconciliation_failed:
            raise RuntimeError("object_storage_reconciliation_failed")


    def get_s3_url(self, bucket_name: str, file_key: str, region: str | None = None) -> str:
        """
        Generate a proper S3 URL for the uploaded file.
        
        Args:
            bucket_name: The S3 bucket name
            file_key: The file key in the bucket
            
        Returns:
            The S3 URL of the file
        """
        selected_region = region or self.region_name
        regional_bucket = resolve_regional_bucket_name(bucket_name, selected_region)
        base_domain = urlparse(endpoint_for_region(selected_region)).netloc
        return f"https://{regional_bucket}.{base_domain}/{file_key}"

    def generate_presigned_url(self, bucket_name: str, file_key: str, expiration: int = 3600, region: str | None = None) -> str:
        """
        Generate a pre-signed URL for accessing a private file.
        
        Args:
            bucket_name: The S3 bucket name
            file_key: The file key in the bucket
            expiration: The expiration time in seconds (default: 1 hour)
            
        Returns:
            The pre-signed URL
        """
        try:
            # Get bucket configuration to check access type
            bucket_key, bucket_config = self.get_bucket_by_name(bucket_name)
            
            # Only generate pre-signed URLs for private buckets
            if bucket_config['access'] != 'private':
                return self.get_s3_url(bucket_name, file_key)
            
            selected_region = region or self.region_name
            selected_client = self.region_clients[selected_region]
            regional_bucket = resolve_regional_bucket_name(bucket_name, selected_region)
            url = selected_client.generate_presigned_url(
                'get_object',
                Params={'Bucket': regional_bucket, 'Key': file_key},
                ExpiresIn=expiration
            )
            
            logger.info("Generated private object URL: region=%s expires_in=%s", selected_region, expiration)
            return url
        except Exception as e:
            logger.error(f"Failed to generate pre-signed URL: {str(e)}")
            # Return regular S3 URL as fallback (will require authentication)
            return self.get_s3_url(bucket_name, file_key, region=region)

    def get_bucket_config(self, bucket_key: str) -> dict:
        """
        Get bucket configuration by key.
        
        Args:
            bucket_key: The key of the bucket in the BUCKETS dictionary
            
        Returns:
            The bucket configuration
            
        Raises:
            ValueError: If the bucket key is not found
        """
        return get_bucket_config(bucket_key)

    def get_bucket_by_name(self, bucket_name: str) -> tuple:
        """
        Get bucket key and config by bucket name.
        
        Args:
            bucket_name: The name of the bucket
            
        Returns:
            A tuple of (bucket_key, bucket_config)
            
        Raises:
            ValueError: If the bucket name is not found
        """
        return get_bucket_by_name(bucket_name)

    async def upload_file(
        self,
        bucket_key: str,
        file_key: str,
        content: bytes,
        content_type: str,
        metadata: Optional[Dict[str, str]] = None,
        region: str | None = None,
        _failed_regions: frozenset[str] | None = None,
    ) -> Dict[str, str]:
        """
        Upload a file to S3 using a simple approach with retries.
        
        Args:
            bucket_key: The key of the bucket in the BUCKETS dictionary
            file_key: The file key in the bucket
            content: The file content as bytes
            content_type: The MIME type of the file
            
        Returns:
            A dictionary containing the S3 URL and pre-signed URL (if applicable)
            
        Raises:
            HTTPException: If the upload fails
        """
        # Ensure client is initialized before proceeding
        selected_region = region or self.region_name
        if not selected_region or selected_region not in self.upload_region_clients:
            logger.error("S3 service not initialized. Cannot upload file.")
            raise storage_unavailable_error()

        # Get bucket configuration
        try:
            bucket_config = self.get_bucket_config(bucket_key)
        except ValueError:
            logger.error(f"Unknown bucket: {bucket_key}")
            raise HTTPException(status_code=400, detail=f"Unknown bucket: {bucket_key}")
        
        # Get the appropriate bucket name based on environment
        legacy_bucket_name = get_bucket_name(bucket_key, self.environment)
        bucket_name = resolve_regional_bucket_name(legacy_bucket_name, selected_region)
        
        # Check file size
        if len(content) > bucket_config['max_size']:
            logger.error(f"File size exceeds maximum allowed for bucket {bucket_key}: {len(content)} > {bucket_config['max_size']}")
            raise HTTPException(status_code=400, detail=f"File size exceeds maximum allowed ({bucket_config['max_size'] // 1024} KB)")
        
        # Check content type if restrictions exist
        if bucket_config['allowed_types'] != ['*/*'] and content_type not in bucket_config['allowed_types']:
            logger.error(f"Content type {content_type} not allowed for bucket {bucket_key}")
            raise HTTPException(status_code=400, detail=f"Content type {content_type} not allowed for this bucket")
        
        max_retries = 5
        retry_delay = 1  # Start with 1 second delay
        # Progressive timeout: start at 15s, double on each timeout retry (15, 30, 60, 120, 120)
        base_read_timeout = 15
        max_read_timeout = 120
        
        try:
            # Log basic information
            logger.info(
                "Uploading storage object: logical_bucket=%s region=%s size=%s content_type=%s",
                bucket_key,
                selected_region,
                len(content),
                content_type,
            )
            
            # Store content in BytesIO to ensure it's treated as a file-like object
            file_obj = BytesIO(content)
            content_checksum = hashlib.sha256(content).hexdigest()

            async def _probe_ambiguous_write() -> str:
                try:
                    existing = await asyncio.to_thread(
                        self.region_clients[selected_region].head_object,
                        Bucket=bucket_name,
                        Key=file_key,
                    )
                except ClientError as head_error:
                    head_code = str(head_error.response.get('Error', {}).get('Code') or '')
                    if head_code in {'404', 'NoSuchKey'}:
                        return 'missing'
                    raise RuntimeError("S3 upload write status is ambiguous after failed verification") from head_error
                except _TRANSIENT_NETWORK_ERRORS as head_error:
                    raise RuntimeError("S3 upload write status is ambiguous after failed verification") from head_error
                existing_checksum = (existing.get('Metadata') or {}).get('openmates-sha256')
                if existing_checksum == content_checksum:
                    return 'matching'
                raise RuntimeError("Immutable storage key already exists with different content")
            
            # Set ACL based on bucket access configuration
            acl = 'private' if bucket_config['access'] == 'private' else 'public-read'
            
            # Set cache control based on bucket configuration.
            # Immutable buckets (e.g., chatfiles) contain content-addressed encrypted blobs
            # that never change — aggressive caching lets browsers skip redundant fetches.
            # Mutable buckets (e.g., profile_images) need no-cache to ensure fresh content.
            if bucket_config.get('cache_control'):
                cache_control = bucket_config['cache_control']
            else:
                cache_control = 'no-cache, no-store, must-revalidate'
            
            # Track the current upload client — starts with the default (15s timeout).
            # On timeout errors, we create a new client with a longer timeout.
            current_upload_client = self.upload_region_clients[selected_region]
            current_read_timeout = base_read_timeout
            
            # Try uploading with retries and exponential backoff.
            # Catches both S3 ClientError (e.g., 5xx) and transient network errors
            # (timeouts, connection drops) that previously bypassed the retry loop.
            for attempt in range(max_retries):
                try:
                    # Configure put_object parameters based on bucket configuration
                    put_params = {
                        'Bucket': bucket_name,
                        'Key': file_key,
                        'Body': file_obj,
                        'ContentType': content_type,
                        'CacheControl': cache_control,
                        'ACL': acl
                    }
                    
                    # Add metadata (merge lifecycle marker + caller-provided metadata)
                    combined_metadata = {}
                    if bucket_config['lifecycle_policy']:
                        combined_metadata['lifecycle-policy'] = f"expire-after-{bucket_config['lifecycle_policy']}-days"
                    if metadata:
                        # Caller metadata wins on conflicts (except we still keep lifecycle marker if distinct)
                        combined_metadata.update(metadata)
                    combined_metadata['openmates-sha256'] = content_checksum
                    if combined_metadata:
                        put_params['Metadata'] = combined_metadata
                    if should_replicate_bucket(bucket_key):
                        put_params['IfNoneMatch'] = '*'
                    
                    # Upload the file using the current upload client.
                    # put_object is synchronous; run on the default executor so
                    # the event loop stays responsive under S3 backpressure.
                    # (Same rationale as delete_file / get_file — see commit d64b91773.)
                    await asyncio.to_thread(current_upload_client.put_object, **put_params)

                    # If successful, break out of the retry loop
                    logger.info(f"Upload successful on attempt {attempt + 1}")
                    break
                except ClientError as e:
                    error_code = e.response['Error']['Code']
                    http_status = (e.response.get('ResponseMetadata') or {}).get('HTTPStatusCode')
                    if error_code in {'PreconditionFailed', '412'}:
                        existing = await asyncio.to_thread(
                            self.region_clients[selected_region].head_object,
                            Bucket=bucket_name,
                            Key=file_key,
                        )
                        existing_checksum = (existing.get('Metadata') or {}).get('openmates-sha256')
                        if existing_checksum == content_checksum:
                            logger.info("Immutable storage object already exists with matching checksum")
                            break
                        raise RuntimeError("Immutable storage key already exists with different content") from e
                    logger.warning(f"Upload attempt {attempt + 1} failed with ClientError: {error_code}")
                    
                    # If we've reached the maximum number of retries, re-raise the exception
                    if attempt == max_retries - 1:
                        if should_replicate_bucket(bucket_key) and is_retryable_storage_error(error_code, http_status):
                            if await _probe_ambiguous_write() == 'matching':
                                logger.info("Retryable S3 failure followed by matching immutable object head")
                                break
                        raise
                    
                    # Otherwise, wait and retry with exponential backoff
                    wait_time = retry_delay * (2 ** attempt)
                    logger.info(f"Retrying in {wait_time} seconds...")
                    await asyncio.sleep(wait_time)
                    
                    # Reset the file position to the beginning for the next attempt
                    file_obj.seek(0)
                except _TRANSIENT_NETWORK_ERRORS as e:
                    # Transient network errors (timeouts, connection drops) are retryable.
                    # Previously these were NOT caught here and fell through to the outer
                    # except block, causing immediate failure without any retries.
                    logger.warning(
                        f"Upload attempt {attempt + 1} failed with network error "
                        f"(timeout={current_read_timeout}s): {type(e).__name__}: {e}"
                    )
                    
                    if attempt == max_retries - 1:
                        if should_replicate_bucket(bucket_key):
                            if await _probe_ambiguous_write() == 'matching':
                                logger.info("Network failure followed by matching immutable object head")
                                break
                        raise
                    
                    # Create a new client with a longer read timeout for the next attempt.
                    # This avoids penalizing normal uploads with a large default timeout
                    # while still allowing retries to succeed for larger files.
                    current_read_timeout = min(current_read_timeout * 2, max_read_timeout)
                    logger.info(f"Creating retry client with read_timeout={current_read_timeout}s")
                    retry_config = Config(
                        signature_version='s3',
                        s3={'addressing_style': 'path'},
                        connect_timeout=15,
                        read_timeout=current_read_timeout,
                        retries={'max_attempts': 0}  # We handle retries ourselves
                    )
                    current_upload_client = boto3.client(
                        's3',
                        region_name=selected_region,
                        endpoint_url=endpoint_for_region(selected_region),
                        aws_access_key_id=self._upload_access_key,
                        aws_secret_access_key=self._upload_secret_key,
                        config=retry_config
                    )
                    
                    wait_time = retry_delay * (2 ** attempt)
                    logger.info(f"Retrying in {wait_time} seconds...")
                    await asyncio.sleep(wait_time)
                    
                    # Reset the file position to the beginning for the next attempt
                    file_obj.seek(0)
            
            logger.info("Upload successful")

            await self._persist_replication_outbox(
                logical_bucket=bucket_key,
                object_key=file_key,
                checksum=content_checksum,
                active_region=selected_region,
            )
            
            # Generate S3 URL
            s3_url = self.get_s3_url(legacy_bucket_name, file_key, region=selected_region)
            
            # Generate pre-signed URL for private content
            result = {'url': s3_url}
            if bucket_config['access'] == 'private':
                presigned_url = self.generate_presigned_url(legacy_bucket_name, file_key, region=selected_region)
                result['presigned_url'] = presigned_url
            result['region'] = selected_region
            
            return result
        
        except HetznerObjectStorageError:
            raise
        except (ClientError, *_TRANSIENT_NETWORK_ERRORS) as exc:
            error_code = (
                str(exc.response.get("Error", {}).get("Code") or type(exc).__name__)
                if isinstance(exc, ClientError)
                else type(exc).__name__
            )
            http_status = (
                (exc.response.get("ResponseMetadata") or {}).get("HTTPStatusCode")
                if isinstance(exc, ClientError)
                else None
            )
            retryable_failure = is_retryable_storage_error(error_code, http_status)
            if self.directus_service is not None and retryable_failure:
                health_error_code = (
                    error_code
                    if error_code in RETRYABLE_STORAGE_ERROR_CODES or http_status is None
                    else str(http_status)
                )
                await record_persisted_region_error(
                    directus_service=self.directus_service,
                    region=selected_region,
                    error_code=health_error_code,
                    now=datetime.now(timezone.utc),
                )
            failed_regions = set(_failed_regions or ())
            failed_regions.add(selected_region)
            allow_failover = should_replicate_bucket(bucket_key) and (
                region is None or _failed_regions is not None
            )
            next_region = next(
                (
                    candidate
                    for candidate in self.upload_region_clients
                    if candidate not in failed_regions
                ),
                None,
            )
            if allow_failover and retryable_failure and next_region:
                logger.warning(
                    "Retryable active-region upload failure; trying configured fallback: failed_region=%s fallback_region=%s error=%s",
                    selected_region,
                    next_region,
                    error_code,
                )
                return await self.upload_file(
                    bucket_key=bucket_key,
                    file_key=file_key,
                    content=content,
                    content_type=content_type,
                    metadata=metadata,
                    region=next_region,
                    _failed_regions=frozenset(failed_regions),
                )
            logger.error("Failed to upload to S3: %s", type(exc).__name__)
            raise classify_hetzner_upload_error(exc) from exc
        except HTTPException:
            raise
        except Exception as exc:
            logger.error("Failed to upload to S3: %s", type(exc).__name__)
            raise storage_unavailable_error() from exc

    async def upload_temporary_file(
        self,
        *,
        bucket_key: str,
        file_key: str,
        content: bytes,
        content_type: str,
        healthy_regions: set[str],
        metadata: Optional[Dict[str, str]] = None,
    ) -> Dict[str, str]:
        """Upload non-replicated temporary media to a healthy configured region."""
        if should_replicate_bucket(bucket_key):
            raise ValueError(f"Temporary non-replicated upload is not allowed for {bucket_key}")
        configured_regions = tuple(self.region_clients)
        selected_region = select_temporary_upload_region(
            configured_regions=configured_regions,
            healthy_regions=healthy_regions,
            preferred_region=self.region_name or configured_regions[0],
        )
        return await self.upload_file(
            bucket_key=bucket_key,
            file_key=file_key,
            content=content,
            content_type=content_type,
            metadata=metadata,
            region=selected_region,
        )

    async def upload_file_stream(
        self,
        *,
        bucket_key: str,
        file_key: str,
        source: AsyncIterable[bytes],
        content_type: str,
        part_size: int = 5 * 1024 * 1024,
        metadata: Optional[Dict[str, str]] = None,
    ) -> Dict[str, str]:
        """Upload an async byte stream using bounded S3 multipart buffers."""
        minimum_part_size = 5 * 1024 * 1024
        if not self.client or not self.upload_client:
            raise storage_unavailable_error()
        if part_size < minimum_part_size:
            raise ValueError(f"part_size must be at least {minimum_part_size} bytes")

        bucket_config = self.get_bucket_config(bucket_key)
        if bucket_config["allowed_types"] != ["*/*"] and content_type not in bucket_config["allowed_types"]:
            raise HTTPException(status_code=400, detail="Content type not allowed for this bucket")
        legacy_bucket_name = get_bucket_name(bucket_key, self.environment)
        selected_region = self.region_name
        if not selected_region:
            raise storage_unavailable_error()
        bucket_name = resolve_regional_bucket_name(legacy_bucket_name, selected_region)
        cache_control = bucket_config.get("cache_control") or "no-cache, no-store, must-revalidate"
        upload_parameters: Dict[str, Any] = {
            "Bucket": bucket_name,
            "Key": file_key,
            "ContentType": content_type,
            "CacheControl": cache_control,
            "ACL": "private" if bucket_config["access"] == "private" else "public-read",
        }
        combined_metadata: Dict[str, str] = {}
        if bucket_config.get("lifecycle_policy"):
            combined_metadata["lifecycle-policy"] = f"expire-after-{bucket_config['lifecycle_policy']}-days"
        if metadata:
            combined_metadata.update(metadata)
        if combined_metadata:
            upload_parameters["Metadata"] = combined_metadata

        staged = SpooledTemporaryFile(max_size=8 * 1024 * 1024)
        upload_id: Optional[str] = None
        try:
            total_size = 0
            checksum = hashlib.sha256()
            async for incoming in source:
                if not incoming:
                    continue
                total_size += len(incoming)
                if total_size > bucket_config["max_size"]:
                    raise HTTPException(status_code=400, detail="File size exceeds bucket limit")
                checksum.update(incoming)
                await asyncio.to_thread(staged.write, incoming)
            if total_size == 0:
                raise ValueError("Cannot upload an empty stream")

            content_checksum = checksum.hexdigest()
            combined_metadata["openmates-sha256"] = content_checksum
            upload_parameters["Metadata"] = combined_metadata

            if should_replicate_bucket(bucket_key):
                try:
                    existing = await asyncio.to_thread(
                        self.region_clients[selected_region].head_object,
                        Bucket=bucket_name,
                        Key=file_key,
                    )
                except ClientError as error:
                    error_code = error.response.get("Error", {}).get("Code")
                    if error_code not in {"404", "NoSuchKey"}:
                        raise
                else:
                    existing_checksum = (existing.get("Metadata") or {}).get("openmates-sha256")
                    if existing_checksum != content_checksum:
                        raise RuntimeError("Immutable storage key already exists with different content")
                    await self._persist_replication_outbox(
                        logical_bucket=bucket_key,
                        object_key=file_key,
                        checksum=content_checksum,
                        active_region=selected_region,
                    )
                    result = {"url": self.get_s3_url(legacy_bucket_name, file_key, region=selected_region)}
                    if bucket_config["access"] == "private":
                        result["presigned_url"] = self.generate_presigned_url(
                            legacy_bucket_name,
                            file_key,
                            region=selected_region,
                        )
                    return result

            created = await asyncio.to_thread(self.upload_client.create_multipart_upload, **upload_parameters)
            upload_id = str(created["UploadId"])
            uploaded_parts: list[Dict[str, Any]] = []
            part_number = 1

            staged.seek(0)
            while content := await asyncio.to_thread(staged.read, part_size):
                response = await asyncio.to_thread(
                    self.upload_client.upload_part,
                    Bucket=bucket_name,
                    Key=file_key,
                    UploadId=upload_id,
                    PartNumber=part_number,
                    Body=content,
                )
                uploaded_parts.append({"PartNumber": part_number, "ETag": response["ETag"]})
                part_number += 1
            completion_parameters: Dict[str, Any] = {
                "Bucket": bucket_name,
                "Key": file_key,
                "UploadId": upload_id,
                "MultipartUpload": {"Parts": uploaded_parts},
            }
            if should_replicate_bucket(bucket_key):
                completion_parameters["IfNoneMatch"] = "*"

            async def _record_completion_region_error(error_code: str, http_status: int | None = None) -> None:
                if self.directus_service is None or not is_retryable_storage_error(error_code, http_status):
                    return
                health_error_code = (
                    error_code
                    if error_code in RETRYABLE_STORAGE_ERROR_CODES or http_status is None
                    else str(http_status)
                )
                await record_persisted_region_error(
                    directus_service=self.directus_service,
                    region=selected_region,
                    error_code=health_error_code,
                    now=datetime.now(timezone.utc),
                )

            async def _verify_ambiguous_multipart_completion() -> str:
                try:
                    existing = await asyncio.to_thread(
                        self.region_clients[selected_region].head_object,
                        Bucket=bucket_name,
                        Key=file_key,
                    )
                except ClientError as head_error:
                    head_code = str(head_error.response.get("Error", {}).get("Code") or "")
                    if head_code in {"404", "NoSuchKey"}:
                        return "missing"
                    raise RuntimeError(
                        "S3 multipart completion status is ambiguous after failed verification"
                    ) from head_error
                except _TRANSIENT_NETWORK_ERRORS as head_error:
                    raise RuntimeError(
                        "S3 multipart completion status is ambiguous after failed verification"
                    ) from head_error
                existing_checksum = (existing.get("Metadata") or {}).get("openmates-sha256")
                if existing_checksum == content_checksum:
                    return "matching"
                raise RuntimeError("Immutable storage key already exists with different content")

            try:
                await asyncio.to_thread(
                    self.upload_client.complete_multipart_upload,
                    **completion_parameters,
                )
            except ClientError as error:
                error_code = error.response.get("Error", {}).get("Code")
                if error_code not in {"PreconditionFailed", "412"}:
                    http_status = (error.response.get("ResponseMetadata") or {}).get("HTTPStatusCode")
                    if should_replicate_bucket(bucket_key) and is_retryable_storage_error(error_code, http_status):
                        try:
                            probe_result = await _verify_ambiguous_multipart_completion()
                        except RuntimeError:
                            await _record_completion_region_error(str(error_code), http_status)
                            raise
                        if probe_result == "matching":
                            logger.info("Retryable multipart completion failure followed by matching object head")
                            upload_id = None
                        else:
                            await _record_completion_region_error(str(error_code), http_status)
                            raise
                    else:
                        raise
                else:
                    await asyncio.to_thread(
                        self.upload_client.abort_multipart_upload,
                        Bucket=bucket_name,
                        Key=file_key,
                        UploadId=upload_id,
                    )
                    upload_id = None
                    existing = await asyncio.to_thread(
                        self.region_clients[selected_region].head_object,
                        Bucket=bucket_name,
                        Key=file_key,
                    )
                    existing_checksum = (existing.get("Metadata") or {}).get("openmates-sha256")
                    if existing_checksum != content_checksum:
                        raise RuntimeError("Immutable storage key already exists with different content") from error
            except _TRANSIENT_NETWORK_ERRORS as error:
                if should_replicate_bucket(bucket_key):
                    try:
                        probe_result = await _verify_ambiguous_multipart_completion()
                    except RuntimeError:
                        await _record_completion_region_error(type(error).__name__)
                        raise
                    if probe_result == "matching":
                        logger.info("Network multipart completion failure followed by matching object head")
                        upload_id = None
                    else:
                        await _record_completion_region_error(type(error).__name__)
                        raise
                else:
                    raise
        except asyncio.CancelledError:
            if upload_id:
                await asyncio.to_thread(
                    self.upload_client.abort_multipart_upload,
                    Bucket=bucket_name,
                    Key=file_key,
                    UploadId=upload_id,
                )
            raise
        except Exception:
            if upload_id:
                try:
                    await asyncio.to_thread(
                        self.upload_client.abort_multipart_upload,
                        Bucket=bucket_name,
                        Key=file_key,
                        UploadId=upload_id,
                    )
                except Exception as abort_exc:
                    logger.error("Failed to abort S3 multipart upload: %s", type(abort_exc).__name__)
            raise
        finally:
            staged.close()

        await self._persist_replication_outbox(
            logical_bucket=bucket_key,
            object_key=file_key,
            checksum=content_checksum,
            active_region=selected_region,
        )
        result = {"url": self.get_s3_url(legacy_bucket_name, file_key, region=selected_region)}
        if bucket_config["access"] == "private":
            result["presigned_url"] = self.generate_presigned_url(
                legacy_bucket_name,
                file_key,
                region=selected_region,
            )
        return result

    async def delete_file(self, bucket_key: str, file_key: str):
        """
        Delete a file from S3.
        
        Args:
            bucket_key: The key of the bucket in the BUCKETS dictionary
            file_key: The file key in the bucket
            
        Raises:
            HTTPException: If the deletion fails
        """
        # Ensure client is initialized before proceeding
        if not self.client:
            logger.error("S3 service not initialized. Cannot delete file.")
            raise storage_unavailable_error()
            
        try:
            if should_replicate_bucket(bucket_key) and self.directus_service is not None:
                now = datetime.now(timezone.utc)
                regions = tuple(self.region_clients)
                tombstone = build_deletion_tombstone(
                    logical_bucket=bucket_key,
                    object_key=file_key,
                    generations=(1,),
                    generation_keys={1: file_key},
                    regions=regions,
                    surviving_reference_count=0,
                    now=now,
                )
                await persist_deletion_tombstone(
                    directus_service=self.directus_service,
                    tombstone=tombstone,
                )
                logger.info(
                    "Persisted regional storage deletion: logical_bucket=%s",
                    bucket_key,
                )
                return

            legacy_bucket = get_bucket_name(bucket_key, self.environment)
            regions = tuple(self.region_clients) or (self.region_name,)
            for region in regions:
                if not region:
                    continue
                bucket_name = resolve_regional_bucket_name(legacy_bucket, region)
                client = self.region_clients.get(region, self.client)
                await asyncio.to_thread(
                    client.delete_object,
                    Bucket=bucket_name,
                    Key=file_key,
                )
            logger.info("Deleted storage object in configured regions: logical_bucket=%s", bucket_key)
        except HTTPException:
            # Re-raise HTTP exceptions
            raise
        except Exception as e:
            logger.error("Failed to delete from object storage: %s", type(e).__name__)
            raise storage_unavailable_error() from e

    async def verify_regional_object(
        self,
        *,
        bucket_key: str,
        object_key: str,
        region: str,
        checksum: str,
    ) -> bool:
        """Verify one immutable regional object using its persisted SHA-256 metadata."""
        client = self.region_clients.get(region)
        if client is None:
            return False
        bucket_name = resolve_regional_bucket_name(get_bucket_name(bucket_key, self.environment), region)
        try:
            response = await asyncio.to_thread(client.head_object, Bucket=bucket_name, Key=object_key)
        except ClientError as exc:
            error_code = exc.response.get('Error', {}).get('Code')
            if error_code in {'NoSuchKey', '404'}:
                return False
            raise storage_unavailable_error() from exc
        return (response.get('Metadata') or {}).get('openmates-sha256') == checksum

    async def get_file(self, bucket_name: str, object_key: str) -> Optional[bytes]:
        """
        Download a file from S3 and return its content as bytes.
        
        Args:
            bucket_name: The name of the S3 bucket
            object_key: The key (path) of the object in the bucket
            
        Returns:
            The file content as bytes, or None if the file doesn't exist or download fails
            
        Raises:
            HTTPException: If the download fails due to service unavailability
        """
        # Ensure client is initialized before proceeding
        if not self.client:
            logger.error("S3 service not initialized. Cannot download file.")
            raise storage_unavailable_error()
        
        try:
            logger.info("Downloading object from storage")
            if await _storage_object_is_tombstoned(self, bucket_name, object_key):
                return None

            bucket_candidates: list[tuple[str, Any]] = [(bucket_name, self.client)]
            try:
                bucket_key, _bucket_config = get_bucket_by_name(bucket_name)
            except ValueError:
                bucket_key = None
            if bucket_key and should_replicate_bucket(bucket_key):
                legacy_bucket = get_bucket_name(bucket_key, self.environment)
                preferred_regions = (
                    (self.region_name,) + tuple(region for region in self.region_clients if region != self.region_name)
                    if self.region_name
                    else tuple(self.region_clients)
                )
                bucket_candidates = [
                    (resolve_regional_bucket_name(legacy_bucket, region), self.region_clients[region])
                    for region in preferred_regions
                    if region in self.region_clients
                ]

            file_content = None
            for candidate_bucket, candidate_client in bucket_candidates:
                try:
                    # boto3 get_object + Body.read() are synchronous network calls.
                    def _download() -> bytes:
                        response = candidate_client.get_object(Bucket=candidate_bucket, Key=object_key)
                        return response['Body'].read()

                    file_content = await asyncio.to_thread(_download)
                    break
                except ClientError as exc:
                    error_code = exc.response.get('Error', {}).get('Code')
                    http_status = (exc.response.get('ResponseMetadata') or {}).get('HTTPStatusCode')
                    if (
                        error_code in {'NoSuchKey', '404'}
                        or is_retryable_storage_error(str(error_code), http_status)
                    ) and candidate_bucket != bucket_candidates[-1][0]:
                        continue
                    raise
                except _TRANSIENT_NETWORK_ERRORS:
                    if candidate_bucket != bucket_candidates[-1][0]:
                        continue
                    raise
            if file_content is None:
                return None

            logger.info("Successfully downloaded object from storage: size=%s bytes", len(file_content))
            return file_content
            
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code')
            if error_code == 'NoSuchKey' or error_code == '404':
                logger.warning("Object not found in storage")
                return None
            else:
                logger.error("Failed to download from object storage: %s", error_code)
                raise storage_unavailable_error() from e
        except Exception as e:
            logger.error("Unexpected object-storage download failure: %s", type(e).__name__)
            raise storage_unavailable_error() from e

    async def get_file_stream(
        self,
        bucket_name: str,
        object_key: str,
        *,
        chunk_size: int = 1024 * 1024,
    ) -> AsyncIterator[bytes]:
        """Read an S3 object incrementally without materializing it in memory."""
        if not self.client:
            raise storage_unavailable_error()
        if chunk_size <= 0:
            raise ValueError("chunk_size must be positive")

        body = None
        try:
            if await _storage_object_is_tombstoned(self, bucket_name, object_key):
                raise HTTPException(status_code=404, detail="Generated asset file missing")
            response = await asyncio.to_thread(
                self.client.get_object,
                Bucket=bucket_name,
                Key=object_key,
            )
            body = response["Body"]
            while chunk := await asyncio.to_thread(body.read, chunk_size):
                if await _storage_object_is_tombstoned(self, bucket_name, object_key):
                    raise HTTPException(status_code=404, detail="Generated asset file missing")
                yield chunk
        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code")
            if error_code in {"NoSuchKey", "404"}:
                raise HTTPException(status_code=404, detail="Generated asset file missing") from exc
            raise storage_unavailable_error() from exc
        except HTTPException:
            raise
        except Exception as exc:
            logger.error(
                "Failed to stream storage object: error=%s",
                type(exc).__name__,
                exc_info=True,
            )
            raise storage_unavailable_error() from exc
        finally:
            if body is not None:
                await asyncio.to_thread(body.close)

    async def get_replicated_file_stream(
        self,
        *,
        bucket_key: str,
        object_key: str,
        regions: tuple[str, ...],
        chunk_size: int = 1024 * 1024,
    ) -> AsyncIterator[bytes]:
        """Stream one replica, failing over across explicitly verified regions."""
        if chunk_size <= 0:
            raise ValueError("chunk_size must be positive")
        if not regions:
            raise storage_unavailable_error()

        legacy_bucket = get_bucket_name(bucket_key, self.environment)
        last_error: Exception | None = None
        for region in regions:
            client = self.region_clients.get(region)
            if client is None:
                continue
            bucket_name = resolve_regional_bucket_name(legacy_bucket, region)
            body = None
            yielded = False
            try:
                response = await asyncio.to_thread(
                    client.get_object,
                    Bucket=bucket_name,
                    Key=object_key,
                )
                body = response["Body"]
                while chunk := await asyncio.to_thread(body.read, chunk_size):
                    yielded = True
                    yield chunk
                return
            except ClientError as exc:
                last_error = exc
                response = exc.response if isinstance(exc.response, dict) else {}
                error_details = response.get("Error") or {}
                response_metadata = response.get("ResponseMetadata") or {}
                error_code = str(error_details.get("Code") or "Unknown")
                status_code = response_metadata.get("HTTPStatusCode")
                if yielded:
                    raise storage_unavailable_error() from exc
                if error_code in {"NoSuchKey", "404"} or status_code == 404:
                    raise HTTPException(status_code=404, detail="Generated asset file missing") from exc
                retryable = is_retryable_storage_error(error_code, status_code)
                if not retryable:
                    raise storage_unavailable_error() from exc
                logger.warning(
                    "Regional object read failed over: region=%s logical_bucket=%s error=%s",
                    region,
                    bucket_key,
                    type(exc).__name__,
                )
            except _TRANSIENT_NETWORK_ERRORS as exc:
                last_error = exc
                if yielded:
                    raise storage_unavailable_error() from exc
                logger.warning(
                    "Regional object read failed over: region=%s logical_bucket=%s error=%s",
                    region,
                    bucket_key,
                    type(exc).__name__,
                )
            finally:
                if body is not None:
                    await asyncio.to_thread(body.close)

        raise storage_unavailable_error() from last_error
