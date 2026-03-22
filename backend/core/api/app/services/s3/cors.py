"""
CORS settings management for S3 buckets.

Applied at API startup via S3UploadService.initialize(). CORS rules allow the
frontend (app.dev.openmates.org / app.openmates.org) to fetch encrypted .bin
blobs directly from public-read chatfiles buckets — required for client-side
AES-256-GCM decryption of uploaded images.

If CORS is not applied correctly, the frontend receives a CORS policy error
when trying to fetch encrypted image blobs for fullscreen viewing.
"""
import logging
import os
from botocore.exceptions import ClientError
from typing import List, Optional

from .config import CORS_ENABLED_BUCKETS, get_allowed_origins

logger = logging.getLogger(__name__)

def apply_cors_settings(s3_client, bucket_names: Optional[List[str]] = None):
    """
    Apply CORS settings to S3 buckets.

    Called at API startup to ensure all public-read chat file buckets have the
    correct CORS rules so the frontend can fetch encrypted blobs cross-origin.

    Raises RuntimeError if CORS could not be applied to any eligible bucket,
    so the caller is aware the bucket state is incorrect rather than silently
    operating with stale/missing CORS rules.

    Args:
        s3_client: The boto3 S3 client
        bucket_names: List of bucket names to apply CORS settings to.
                     If None, uses CORS_ENABLED_BUCKETS from config.
    """
    # Get the current environment
    server_env = os.getenv('SERVER_ENVIRONMENT', 'development')

    # Use default bucket list if none provided
    if bucket_names is None:
        bucket_names = CORS_ENABLED_BUCKETS

    # Get allowed origins based on environment
    allowed_origins = get_allowed_origins(server_env)

    logger.info(f"Applying CORS settings for {server_env} environment with origins: {allowed_origins}")

    # CORS configuration — allows GET/HEAD of encrypted .bin blobs from the frontend
    cors_config = {
        'CORSRules': [
            {
                'AllowedOrigins': allowed_origins,
                'AllowedMethods': ['GET', 'HEAD'],
                'AllowedHeaders': ['*'],
                'ExposeHeaders': ['ETag', 'Content-Length'],
                'MaxAgeSeconds': 3600
            }
        ]
    }

    failed_buckets = []

    # Apply CORS settings to each bucket
    for bucket_name in bucket_names:
        # Skip buckets that don't match the current environment
        if server_env == 'development' and not bucket_name.startswith('dev-'):
            logger.info(f"Skipping production bucket {bucket_name} in development environment")
            continue

        if server_env == 'production' and bucket_name.startswith('dev-'):
            logger.info(f"Skipping development bucket {bucket_name} in production environment")
            continue

        try:
            logger.info(f"Applying CORS settings to bucket: {bucket_name}")
            s3_client.put_bucket_cors(
                Bucket=bucket_name,
                CORSConfiguration=cors_config
            )
            logger.info(f"Successfully applied CORS settings to bucket: {bucket_name}")
        except ClientError as e:
            error_code = e.response['Error']['Code']
            logger.error(
                f"Failed to apply CORS settings to bucket {bucket_name}: {error_code} — "
                f"frontend image fetches will be blocked by CORS policy"
            )
            failed_buckets.append(bucket_name)

    if failed_buckets:
        raise RuntimeError(
            f"Failed to apply CORS settings to buckets: {failed_buckets}. "
            f"Cross-origin image fetches from the frontend will fail. "
            f"Check S3 credentials and bucket permissions."
        )
