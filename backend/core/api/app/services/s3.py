import boto3
import logging
import os
import time
import re
from io import BytesIO
from fastapi import HTTPException
from botocore.config import Config
from botocore.exceptions import ClientError
from urllib.parse import urlparse
from typing import Union, Dict

logger = logging.getLogger(__name__)

class S3UploadService:
    # S3 bucket configurations as class variable
    BUCKETS = {
        'profile_images': {
            'name': 'openmates-profile-images',
            'allowed_types': ['image/jpeg', 'image/png', 'image/webp'],
            'max_size': 300 * 1024,  # 300KB
            'access': 'private',
            'lifecycle_policy': None,  # No auto-delete
            'cache': True,  # Use KeyCDN caching
            'permissions': 'read_write'  # Read & write permissions
        },
        'invoices': {
            'name': 'openmates-invoices',
            'allowed_types': ['application/pdf'],
            'max_size': 1 * 1024 * 1024,  # 1MB
            'access': 'private',
            'lifecycle_policy': 3650,  # 10 years auto-delete (in days)
            'cache': False,  # No caching
            'permissions': 'write_once_read',  # Read-only after write
            'environment': 'production'  # Only used in production
        },
        'testing_invoices': {
            'name': 'openmates-testing-invoices',
            'allowed_types': ['application/pdf'],
            'max_size': 1 * 1024 * 1024,  # 1MB
            'access': 'private',
            'lifecycle_policy': 3650,  # 10 years auto-delete (in days)
            'cache': False,  # No caching
            'permissions': 'read_write',  # Read & write permissions
            'environment': 'testing'  # Only used in testing
        },
        'chatfiles': {
            'name': 'openmates-chatfiles',
            'allowed_types': ['*/*'],  # Allow all file types
            'max_size': 500 * 1024 * 1024,  # 500MB
            'access': 'private',
            'lifecycle_policy': None,  # No auto-delete
            'cache': True,  # Use KeyCDN caching
            'permissions': 'read_write'  # Read & write permissions
        },
        'userdata_backups': {
            'name': 'openmates-userdata-backups',
            'allowed_types': ['*/*'],  # Allow all file types
            'max_size': 1024 * 1024 * 1024,  # 1GB (reasonable for backups)
            'access': 'private',
            'lifecycle_policy': 60,  # 2 months auto-delete (in days)
            'cache': False,  # No caching
            'permissions': 'read_write'  # Read & write permissions
        },
        'compliance_logs': {
            'name': 'openmates-compliance-logs-backups',
            'allowed_types': ['*/*'],  # Allow all file types
            'max_size': 500 * 1024 * 1024,  # 500MB
            'access': 'private',
            'lifecycle_policy': 365,  # 1 year auto-delete (in days)
            'cache': False,  # No caching
            'permissions': 'write_once_read'  # Read-only after upload
        }
    }

    # Removed KeyCDN configuration as it's not needed yet

    def __init__(self):
        """
        Initialize the S3 client with a configuration optimized for S3-compatible storage.
        """
        # Use a simpler configuration for S3-compatible storage
        s3_config = Config(
            # Use older signature version for better compatibility
            signature_version='s3',
            # Use path-style addressing instead of virtual-hosted style
            s3={'addressing_style': 'path'},
            # Increase timeouts and retries
            connect_timeout=10,
            read_timeout=10,
            retries={'max_attempts': 3}
        )
        
        # Get region name from environment variables with fallback to 'fsn1'
        region_name = os.getenv('HETZNER_S3_REGION', 'fsn1')
        
        # Build endpoint URL based on region name
        endpoint_url = f'https://{region_name}.your-objectstorage.com'
        
        # Initialize the S3 client with the config
        self.client = boto3.client(
            's3',
            region_name=region_name,
            endpoint_url=endpoint_url,
            aws_access_key_id=os.getenv('HETZNER_S3_ACCESS_KEY'),
            aws_secret_access_key=os.getenv('HETZNER_S3_SECRET_KEY'),
            config=s3_config
        )
        
        # Store the base domain for URL generation
        parsed_url = urlparse(endpoint_url)
        self.base_domain = parsed_url.netloc

    def get_bucket_config(self, bucket_key: str) -> dict:
        """Get bucket configuration by key."""
        if bucket_key not in self.BUCKETS:
            raise ValueError(f"Unknown bucket: {bucket_key}")
        return self.BUCKETS[bucket_key]

    def get_bucket_by_name(self, bucket_name: str) -> tuple:
        """Get bucket key and config by bucket name."""
        for key, config in self.BUCKETS.items():
            if config['name'] == bucket_name:
                return key, config
        raise ValueError(f"Unknown bucket name: {bucket_name}")

    def get_s3_url(self, bucket_name: str, file_key: str) -> str:
        """Generate a proper S3 URL for the uploaded file."""
        return f"https://{bucket_name}.{self.base_domain}/{file_key}"

    # Removed get_cdn_url and get_urls methods as they're not needed yet

    async def upload_file(self, bucket_name: str, file_key: str, content: bytes, content_type: str) -> str:
        """
        Upload a file to S3 using a simple approach with retries.
        
        This method uses a simpler approach that's more compatible with S3-compatible storage services:
        1. Using an older signature version (s3 instead of s3v4)
        2. Using path-style addressing instead of virtual-hosted style
        3. Using a simple put_object call without checksums or streaming
        4. Implementing manual retries with exponential backoff
        
        Args:
            bucket_name: The S3 bucket name
            file_key: The file key in the bucket
            content: The file content as bytes
            content_type: The MIME type of the file
            
        Returns:
            The S3 URL of the uploaded file
        """
        # Get bucket configuration
        try:
            bucket_key, bucket_config = self.get_bucket_by_name(bucket_name)
        except ValueError:
            logger.error(f"Unknown bucket: {bucket_name}")
            raise HTTPException(status_code=400, detail=f"Unknown bucket: {bucket_name}")
        
        # Check environment restrictions
        server_env = os.getenv('SERVER_ENVIRONMENT', 'development')
        if 'environment' in bucket_config and bucket_config['environment'] != server_env:
            logger.error(f"Bucket {bucket_name} is restricted to {bucket_config['environment']} environment")
            raise HTTPException(status_code=400, detail=f"Bucket {bucket_name} is not available in {server_env} environment")
        
        # Check file size
        if len(content) > bucket_config['max_size']:
            logger.error(f"File size exceeds maximum allowed for bucket {bucket_name}: {len(content)} > {bucket_config['max_size']}")
            raise HTTPException(status_code=400, detail=f"File size exceeds maximum allowed ({bucket_config['max_size'] // 1024} KB)")
        
        # Check content type if restrictions exist
        if bucket_config['allowed_types'] != ['*/*'] and content_type not in bucket_config['allowed_types']:
            logger.error(f"Content type {content_type} not allowed for bucket {bucket_name}")
            raise HTTPException(status_code=400, detail=f"Content type {content_type} not allowed for this bucket")
        
        max_retries = 5
        retry_delay = 1  # Start with 1 second delay
        
        try:
            # Log basic information
            logger.info(f"Uploading file to S3: bucket={bucket_name}, key={file_key}, size={len(content)}, content_type={content_type}")
            
            # Store content in BytesIO to ensure it's treated as a file-like object
            file_obj = BytesIO(content)
            
            # Set ACL based on bucket access configuration
            acl = 'private' if bucket_config['access'] == 'private' else 'public-read'
            
            # Set cache control based on bucket cache configuration
            cache_control = 'public, max-age=31536000' if bucket_config['cache'] else 'no-cache, no-store, must-revalidate'
            
            # Try uploading with retries and exponential backoff
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
                    
                    # Add lifecycle configuration if specified
                    if bucket_config['lifecycle_policy']:
                        # Note: This is just metadata, actual lifecycle policies should be configured at the bucket level
                        put_params['Metadata'] = {
                            'lifecycle-policy': f"expire-after-{bucket_config['lifecycle_policy']}-days"
                        }
                    
                    # Upload the file
                    self.client.put_object(**put_params)
                    
                    # If successful, break out of the retry loop
                    logger.info(f"Upload successful on attempt {attempt + 1}")
                    break
                except ClientError as e:
                    error_code = e.response['Error']['Code']
                    logger.warning(f"Upload attempt {attempt + 1} failed with error: {error_code}")
                    
                    # If we've reached the maximum number of retries, re-raise the exception
                    if attempt == max_retries - 1:
                        raise
                    
                    # Otherwise, wait and retry with exponential backoff
                    wait_time = retry_delay * (2 ** attempt)
                    logger.info(f"Retrying in {wait_time} seconds...")
                    time.sleep(wait_time)
                    
                    # Reset the file position to the beginning for the next attempt
                    file_obj.seek(0)
            
            logger.info(f"Upload successful")
            
            # Generate and return the S3 URL
            s3_url = self.get_s3_url(bucket_name, file_key)
            return s3_url
        
        except Exception as e:
            logger.error(f"Failed to upload to S3: {str(e)}")
            raise HTTPException(status_code=500, detail="Failed to upload file")

    async def delete_file(self, bucket_name: str, file_key: str):
        """
        Delete a file from S3.
        
        Args:
            bucket_name: The S3 bucket name
            file_key: The file key in the bucket
        """
        try:
            # Get bucket configuration
            try:
                bucket_key, bucket_config = self.get_bucket_by_name(bucket_name)
            except ValueError:
                logger.error(f"Unknown bucket: {bucket_name}")
                raise HTTPException(status_code=400, detail=f"Unknown bucket: {bucket_name}")
            
            # Check if deletion is allowed based on permissions
            if bucket_config['permissions'] == 'write_once_read':
                logger.error(f"Deletion not allowed for bucket {bucket_name} with write_once_read permissions")
                raise HTTPException(status_code=403, detail="Deletion not allowed for this bucket")
            
            # Delete the file
            self.client.delete_object(Bucket=bucket_name, Key=file_key)
            logger.info(f"Successfully deleted file from S3: bucket={bucket_name}, key={file_key}")
        except HTTPException:
            # Re-raise HTTP exceptions
            raise
        except Exception as e:
            logger.error(f"Failed to delete from S3: {str(e)}")
            raise HTTPException(status_code=500, detail="Failed to delete file")
