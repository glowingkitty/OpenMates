"""
S3 bucket configurations and settings.
"""
import logging
import os
import yaml
from pathlib import Path
from typing import Dict, List

logger = logging.getLogger(__name__)

# Load URLs from shared config
def load_urls_config():
    """Load URLs configuration from shared config file."""
    try:
        config_path = Path(__file__).parent.parent.parent.parent.parent.parent.parent / "shared" / "config" / "urls.yml"
        with open(config_path, 'r') as file:
            config = yaml.safe_load(file)
            return config['urls']
    except Exception as e:
        logger.error(f"Failed to load URLs config: {str(e)}")
        # Fallback to default values
        return {
            'base': {
                'webapp': {
                    'development': 'http://localhost:5174',
                    'production': 'https://app.openmates.org'
                }
            }
        }

# URLs configuration
URLS_CONFIG = load_urls_config()

# Buckets that need CORS settings
CORS_ENABLED_BUCKETS = [
    'openmates-profile-images', 
    'dev-openmates-profile-images',
    'openmates-chatfiles',
    'dev-openmates-chatfiles',
    'openmates-invoices',
    'dev-openmates-invoices'
]

# S3 bucket configurations
BUCKETS = {
    'profile_images': {
        'name': 'openmates-profile-images',
        'dev_name': 'dev-openmates-profile-images',
        'allowed_types': ['image/jpeg', 'image/png', 'image/webp'],
        'max_size': 300 * 1024,  # 300KB
        'access': 'public-read',
        'lifecycle_policy': None,  # No auto-delete
    },
    'invoices': {
        'name': 'openmates-invoices',
        'dev_name': 'dev-openmates-invoices',
        'allowed_types': ['application/pdf'],
        'max_size': 1 * 1024 * 1024,  # 1MB
        'access': 'private',
        'lifecycle_policy': 3650,  # 10 years auto-delete (in days)
    },
    'chatfiles': {
        'name': 'openmates-chatfiles',
        'dev_name': 'dev-openmates-chatfiles',
        'allowed_types': ['*/*'],  # Allow all file types
        'max_size': 500 * 1024 * 1024,  # 500MB
        'access': 'public-read',
        'lifecycle_policy': None,  # No auto-delete
    },
    'userdata_backups': {
        'name': 'openmates-userdata-backups',
        'dev_name': 'dev-openmates-userdata-backups',
        'allowed_types': ['*/*'],  # Allow all file types
        'max_size': 1024 * 1024 * 1024,  # 1GB (reasonable for backups)
        'access': 'private',
        'lifecycle_policy': 60,  # 2 months auto-delete (in days)
    },
    'compliance_logs': {
        'name': 'openmates-compliance-logs-backups',
        'dev_name': 'dev-openmates-compliance-logs-backups',
        'allowed_types': ['*/*'],  # Allow all file types
        'max_size': 500 * 1024 * 1024,  # 500MB
        'access': 'private',
        'lifecycle_policy': 365,  # 1 year auto-delete (in days)
    }
}

def get_bucket_name(bucket_key: str, environment: str = None) -> str:
    """
    Get the appropriate bucket name based on the environment.
    
    Args:
        bucket_key: The key of the bucket in the BUCKETS dictionary
        environment: The environment ('development' or 'production')
                    If None, uses the SERVER_ENVIRONMENT env var
                    
    Returns:
        The bucket name for the specified environment
    """
    if bucket_key not in BUCKETS:
        raise ValueError(f"Unknown bucket: {bucket_key}")
    
    if environment is None:
        environment = os.getenv('SERVER_ENVIRONMENT', 'development')
    
    if environment == 'development':
        return BUCKETS[bucket_key]['dev_name']
    else:
        return BUCKETS[bucket_key]['name']

def get_bucket_config(bucket_key: str) -> dict:
    """Get bucket configuration by key."""
    if bucket_key not in BUCKETS:
        raise ValueError(f"Unknown bucket: {bucket_key}")
    return BUCKETS[bucket_key]

def get_bucket_by_name(bucket_name: str) -> tuple:
    """
    Get bucket key and config by bucket name.
    
    Args:
        bucket_name: The name of the bucket
        
    Returns:
        A tuple of (bucket_key, bucket_config)
        
    Raises:
        ValueError: If the bucket name is not found
    """
    # Check production bucket names
    for key, config in BUCKETS.items():
        if config['name'] == bucket_name:
            return key, config
    
    # Check development bucket names
    for key, config in BUCKETS.items():
        if config['dev_name'] == bucket_name:
            return key, config
    
    raise ValueError(f"Unknown bucket name: {bucket_name}")

def get_allowed_origins(environment: str) -> List[str]:
    """
    Get allowed origins based on environment.
    
    Args:
        environment: The environment ('development' or 'production')
        
    Returns:
        A list of allowed origins for CORS
    """
    origins = []
    
    # Add webapp URLs
    webapp_url = URLS_CONFIG.get('base', {}).get('webapp', {}).get(environment)
    if webapp_url:
        origins.append(webapp_url)
    
    # If no origins were found, add defaults
    if not origins:
        if environment == 'development':
            origins = ['http://localhost:5174']
        else:
            origins = ['https://app.openmates.org']
    
    return origins