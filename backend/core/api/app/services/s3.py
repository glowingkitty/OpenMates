import boto3
import logging
import os
import time
from io import BytesIO
from fastapi import HTTPException
from botocore.config import Config
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

class S3UploadService:
    # S3 bucket configurations as class variable
    BUCKETS = {
        'profile_images': {
            'name': 'openmates-profile-images',
            'allowed_types': ['image/jpeg', 'image/png', 'image/webp'],
            'max_size': 5 * 1024 * 1024  # 5MB
        }
    }

    def __init__(self):
        """
        Initialize the S3 client with a configuration that disables SHA256 content hash calculation.
        
        The XAmzContentSHA256Mismatch error occurs when the SHA256 hash of the content calculated 
        by AWS doesn't match the hash provided in the request headers. This can happen when:
        1. The content is modified during transmission
        2. The AWS SDK calculates the hash differently than the S3 service expects
        3. The S3-compatible service has a different implementation of SHA256 hash calculation
        
        By disabling the SHA256 content hash calculation, we can bypass this issue.
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
        
        # Initialize the S3 client with the config
        self.client = boto3.client(
            's3',
            region_name='fsn1',
            endpoint_url='https://fsn1.your-objectstorage.com',
            aws_access_key_id=os.getenv('HETZNER_S3_ACCESS_KEY'),
            aws_secret_access_key=os.getenv('HETZNER_S3_SECRET_KEY'),
            config=s3_config
        )

    def get_bucket_config(self, bucket_key: str) -> dict:
        """Get bucket configuration by key."""
        if bucket_key not in self.BUCKETS:
            raise ValueError(f"Unknown bucket: {bucket_key}")
        return self.BUCKETS[bucket_key]

    async def upload_file(self, bucket_name: str, file_key: str, content: bytes, content_type: str) -> str:
        """
        Upload a file to S3 using a simple approach with retries.
        
        This method uses a simpler approach that's more compatible with S3-compatible storage services:
        1. Using an older signature version (s3 instead of s3v4)
        2. Using path-style addressing instead of virtual-hosted style
        3. Using a simple put_object call without checksums or streaming
        4. Implementing manual retries with exponential backoff
        """
        max_retries = 5
        retry_delay = 1  # Start with 1 second delay
        
        try:
            # Log basic information
            logger.info(f"Uploading file to S3: bucket={bucket_name}, key={file_key}, size={len(content)}, content_type={content_type}")
            
            # Store content in BytesIO to ensure it's treated as a file-like object
            file_obj = BytesIO(content)
            
            # Try uploading with retries and exponential backoff
            for attempt in range(max_retries):
                try:
                    # Simple put_object call without extra parameters
                    self.client.put_object(
                        Bucket=bucket_name,
                        Key=file_key,
                        Body=file_obj,
                        ContentType=content_type,
                        CacheControl='public, max-age=31536000',
                        ACL='public-read'
                    )
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
            
            # Extract the endpoint URL from the client configuration
            endpoint_url = self.client._endpoint.host
            return f"https://{bucket_name}.{endpoint_url}/{file_key}"
        
        except Exception as e:
            logger.error(f"Failed to upload to S3: {str(e)}")
            raise HTTPException(status_code=500, detail="Failed to upload file")

    async def delete_file(self, bucket_name: str, file_key: str):
        try:
            self.client.delete_object(Bucket=bucket_name, Key=file_key)
        except Exception as e:
            logger.error(f"Failed to delete from S3: {str(e)}")
