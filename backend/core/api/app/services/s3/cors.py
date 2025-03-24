"""
CORS settings management for S3 buckets.
"""
import logging
import os
from botocore.exceptions import ClientError
from typing import List

from .config import CORS_ENABLED_BUCKETS, get_allowed_origins

logger = logging.getLogger(__name__)

def apply_cors_settings(s3_client, bucket_names: List[str] = None):
    """
    Apply CORS settings to S3 buckets.
    
    Args:
        s3_client: The boto3 S3 client
        bucket_names: List of bucket names to apply CORS settings to.
                     If None, uses CORS_ENABLED_BUCKETS from config.
    """
    try:
        # Get the current environment
        server_env = os.getenv('SERVER_ENVIRONMENT', 'development')
        
        # Use default bucket list if none provided
        if bucket_names is None:
            bucket_names = CORS_ENABLED_BUCKETS
        
        # Get allowed origins based on environment
        allowed_origins = get_allowed_origins(server_env)
        
        logger.info(f"Applying CORS settings for {server_env} environment with origins: {allowed_origins}")
        
        # CORS configuration
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
                logger.warning(f"Failed to apply CORS settings to bucket {bucket_name}: {error_code}")
                # Don't raise exception here, as this is not critical for the service to function
    except Exception as e:
        logger.error(f"Error applying CORS settings: {str(e)}")