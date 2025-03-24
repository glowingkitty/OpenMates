"""
Lifecycle policy management for S3 buckets.
"""
import logging
from botocore.exceptions import ClientError
from typing import Dict, List

logger = logging.getLogger(__name__)

def apply_lifecycle_policies(s3_client, bucket_configs: Dict[str, Dict]):
    """
    Apply lifecycle policies to S3 buckets.
    
    Args:
        s3_client: The boto3 S3 client
        bucket_configs: Dictionary of bucket configurations
    """
    try:
        for bucket_key, bucket_config in bucket_configs.items():
            bucket_name = bucket_config['name']
            lifecycle_days = bucket_config.get('lifecycle_policy')
            
            # Skip if no lifecycle policy is defined
            if not lifecycle_days:
                continue
            
            try:
                logger.info(f"Applying lifecycle policy to bucket: {bucket_name} (expire after {lifecycle_days} days)")
                
                # Create lifecycle configuration
                lifecycle_config = {
                    'Rules': [
                        {
                            'ID': f'ExpireAfter{lifecycle_days}Days',
                            'Status': 'Enabled',
                            'Prefix': '',  # Apply to all objects
                            'Expiration': {
                                'Days': lifecycle_days
                            }
                        }
                    ]
                }
                
                # Apply lifecycle configuration
                s3_client.put_bucket_lifecycle_configuration(
                    Bucket=bucket_name,
                    LifecycleConfiguration=lifecycle_config
                )
                
                logger.info(f"Successfully applied lifecycle policy to bucket: {bucket_name}")
            except ClientError as e:
                error_code = e.response['Error']['Code']
                logger.warning(f"Failed to apply lifecycle policy to bucket {bucket_name}: {error_code}")
                # Don't raise exception here, as this is not critical for the service to function
            except Exception as e:
                logger.error(f"Error applying lifecycle policy to bucket {bucket_name}: {str(e)}")
    except Exception as e:
        logger.error(f"Error applying lifecycle policies: {str(e)}")

def apply_lifecycle_policy_to_bucket(s3_client, bucket_name: str, days: int):
    """
    Apply a lifecycle policy to a specific bucket.
    
    Args:
        s3_client: The boto3 S3 client
        bucket_name: The name of the bucket
        days: The number of days after which objects should expire
    """
    try:
        logger.info(f"Applying lifecycle policy to bucket: {bucket_name} (expire after {days} days)")
        
        # Create lifecycle configuration
        lifecycle_config = {
            'Rules': [
                {
                    'ID': f'ExpireAfter{days}Days',
                    'Status': 'Enabled',
                    'Prefix': '',  # Apply to all objects
                    'Expiration': {
                        'Days': days
                    }
                }
            ]
        }
        
        # Apply lifecycle configuration
        s3_client.put_bucket_lifecycle_configuration(
            Bucket=bucket_name,
            LifecycleConfiguration=lifecycle_config
        )
        
        logger.info(f"Successfully applied lifecycle policy to bucket: {bucket_name}")
        return True
    except Exception as e:
        logger.error(f"Error applying lifecycle policy to bucket {bucket_name}: {str(e)}")
        return False