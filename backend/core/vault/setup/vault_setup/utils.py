"""
Utility functions for the Vault setup process.
"""

import logging
import os

logger = logging.getLogger("vault-setup.utils")

def setup_logging() -> None:
    """Configure logging for the Vault setup process."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler()]
    )

def check_env_file_exists(env_file_path: str) -> bool:
    """Check if the .env file exists.
    
    Args:
        env_file_path: Path to the .env file
        
    Returns:
        True if file exists, False otherwise
    """
    if not os.path.exists(env_file_path):
        logger.error(f".env file not found at {env_file_path}")
        return False
    return True

def validate_environment() -> bool:
    """Validate that required environment variables are set.
    
    Returns:
        True if validation passes, False otherwise
    """
    required_vars = [
        "VAULT_ADDR",
    ]
    
    missing_vars = []
    for var in required_vars:
        if not os.environ.get(var):
            missing_vars.append(var)
    
    if missing_vars:
        logger.error(f"Missing required environment variables: {', '.join(missing_vars)}")
        return False
        
    return True