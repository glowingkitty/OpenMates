import boto3
import logging
from fastapi import HTTPException
import os

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
        self.client = boto3.client(
            's3',
            region_name='fsn1',
            endpoint_url=os.getenv('HETZNER_S3_ENDPOINT', 'https://fsn1.storage.hetzner.cloud'),
            aws_access_key_id=os.getenv('HETZNER_S3_ACCESS_KEY'),
            aws_secret_access_key=os.getenv('HETZNER_S3_SECRET_KEY')
        )

    def get_bucket_config(self, bucket_key: str) -> dict:
        """Get bucket configuration by key."""
        if bucket_key not in self.BUCKETS:
            raise ValueError(f"Unknown bucket: {bucket_key}")
        return self.BUCKETS[bucket_key]

    async def upload_file(self, bucket_name: str, file_key: str, content: bytes, content_type: str) -> str:
        try:
            extra_args = {
                'ContentType': content_type,
                'CacheControl': 'public, max-age=31536000',
                'ACL': 'public-read'
            }
            
            self.client.put_object(
                Bucket=bucket_name,
                Key=file_key,
                Body=content,
                **extra_args
            )
            
            endpoint = os.getenv('HETZNER_S3_ENDPOINT', 'https://fsn1.storage.hetzner.cloud')
            endpoint = endpoint.replace('https://', '')  # Remove protocol
            return f"https://{bucket_name}.{endpoint}/{file_key}"
        
        except Exception as e:
            logger.error(f"Failed to upload to S3: {str(e)}")
            raise HTTPException(status_code=500, detail="Failed to upload file")

    async def delete_file(self, bucket_name: str, file_key: str):
        try:
            self.client.delete_object(Bucket=bucket_name, Key=file_key)
        except Exception as e:
            logger.error(f"Failed to delete from S3: {str(e)}")
