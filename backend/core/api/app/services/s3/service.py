"""
S3 upload service for handling file uploads and storage.
"""
import boto3
import logging
import os
import time
from io import BytesIO
from fastapi import HTTPException
from botocore.config import Config
from botocore.exceptions import ClientError
from urllib.parse import urlparse
from typing import Optional, Dict

from .config import BUCKETS, get_bucket_config, get_bucket_by_name, get_bucket_name
from .cors import apply_cors_settings
from .lifecycle import apply_lifecycle_policies

logger = logging.getLogger(__name__)

class S3UploadService:
    """
    Service for handling file uploads to S3-compatible storage.
    """
    
    def __init__(self):
        """
        Initialize the S3 client with a configuration optimized for S3-compatible storage.
        """
        # Get region name from environment variables with fallback to 'fsn1'
        self.region_name = os.getenv('HETZNER_S3_REGION', 'fsn1')
        
        # Build endpoint URL based on region name
        self.endpoint_url = f'https://{self.region_name}.your-objectstorage.com'
        
        # Access keys
        self.access_key = os.getenv('HETZNER_S3_ACCESS_KEY')
        self.secret_key = os.getenv('HETZNER_S3_SECRET_KEY')
        
        # Configuration for CORS and general operations (uses s3v4 for compatibility)
        s3v4_config = Config(
            signature_version='s3v4',
            s3={'addressing_style': 'path'},
            connect_timeout=10,
            read_timeout=10,
            retries={'max_attempts': 3}
        )
        
        # Initialize the main S3 client for CORS and general operations
        self.client = boto3.client(
            's3',
            region_name=self.region_name,
            endpoint_url=self.endpoint_url,
            aws_access_key_id=self.access_key,
            aws_secret_access_key=self.secret_key,
            config=s3v4_config
        )
        
        # Separate client for uploads with older signature method
        upload_config = Config(
            signature_version='s3',  # Use older signature version which is more lenient
            s3={'addressing_style': 'path'},
            connect_timeout=15,
            read_timeout=15,
            retries={'max_attempts': 3}
        )
        
        # Create a separate client for uploads
        self.upload_client = boto3.client(
            's3',
            region_name=self.region_name,
            endpoint_url=self.endpoint_url,
            aws_access_key_id=self.access_key,
            aws_secret_access_key=self.secret_key,
            config=upload_config
        )
        
        # Store the base domain for URL generation
        parsed_url = urlparse(self.endpoint_url)
        self.base_domain = parsed_url.netloc
        
        # Get current environment
        self.environment = os.getenv('SERVER_ENVIRONMENT', 'development')
        
        # Apply CORS settings to required buckets
        apply_cors_settings(self.client)
        
        # Apply lifecycle policies to buckets
        apply_lifecycle_policies(self.client, BUCKETS)

    def get_s3_url(self, bucket_name: str, file_key: str) -> str:
        """
        Generate a proper S3 URL for the uploaded file.
        
        Args:
            bucket_name: The S3 bucket name
            file_key: The file key in the bucket
            
        Returns:
            The S3 URL of the file
        """
        return f"https://{bucket_name}.{self.base_domain}/{file_key}"

    def generate_presigned_url(self, bucket_name: str, file_key: str, expiration: int = 3600) -> str:
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
            
            # Generate pre-signed URL
            url = self.client.generate_presigned_url(
                'get_object',
                Params={'Bucket': bucket_name, 'Key': file_key},
                ExpiresIn=expiration
            )
            
            logger.info(f"Generated pre-signed URL for {bucket_name}/{file_key} (expires in {expiration} seconds)")
            return url
        except Exception as e:
            logger.error(f"Failed to generate pre-signed URL: {str(e)}")
            # Return regular S3 URL as fallback (will require authentication)
            return self.get_s3_url(bucket_name, file_key)

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

    async def upload_file(self, bucket_key: str, file_key: str, content: bytes, content_type: str) -> Dict[str, str]:
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
        # Get bucket configuration
        try:
            bucket_config = self.get_bucket_config(bucket_key)
        except ValueError:
            logger.error(f"Unknown bucket: {bucket_key}")
            raise HTTPException(status_code=400, detail=f"Unknown bucket: {bucket_key}")
        
        # Get the appropriate bucket name based on environment
        bucket_name = get_bucket_name(bucket_key, self.environment)
        
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
        
        try:
            # Log basic information
            logger.info(f"Uploading file to S3: bucket={bucket_name}, key={file_key}, size={len(content)}, content_type={content_type}")
            
            # Store content in BytesIO to ensure it's treated as a file-like object
            file_obj = BytesIO(content)
            
            # Set ACL based on bucket access configuration
            acl = 'private' if bucket_config['access'] == 'private' else 'public-read'
            
            # Set cache control
            cache_control = 'no-cache, no-store, must-revalidate'
            
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
                    
                    # Upload the file using the dedicated upload client
                    self.upload_client.put_object(**put_params)
                    
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
            
            # Generate S3 URL
            s3_url = self.get_s3_url(bucket_name, file_key)
            
            # Generate pre-signed URL for private content
            result = {'url': s3_url}
            if bucket_config['access'] == 'private':
                presigned_url = self.generate_presigned_url(bucket_name, file_key)
                result['presigned_url'] = presigned_url
            
            return result
        
        except Exception as e:
            logger.error(f"Failed to upload to S3: {str(e)}")
            raise HTTPException(status_code=500, detail="Failed to upload file")

    async def delete_file(self, bucket_key: str, file_key: str):
        """
        Delete a file from S3.
        
        Args:
            bucket_key: The key of the bucket in the BUCKETS dictionary
            file_key: The file key in the bucket
            
        Raises:
            HTTPException: If the deletion fails
        """
        try:
            # Get bucket configuration
            try:
                bucket_config = self.get_bucket_config(bucket_key)
            except ValueError:
                logger.error(f"Unknown bucket: {bucket_key}")
                raise HTTPException(status_code=400, detail=f"Unknown bucket: {bucket_key}")
            
            # Get the appropriate bucket name based on environment
            bucket_name = get_bucket_name(bucket_key, self.environment)
            
            # Delete the file
            self.client.delete_object(Bucket=bucket_name, Key=file_key)
            logger.info(f"Successfully deleted file from S3: bucket={bucket_name}, key={file_key}")
        except HTTPException:
            # Re-raise HTTP exceptions
            raise
        except Exception as e:
            logger.error(f"Failed to delete from S3: {str(e)}")
            raise HTTPException(status_code=500, detail="Failed to delete file")