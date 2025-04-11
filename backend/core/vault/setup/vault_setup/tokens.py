"""
Functions for managing Vault tokens.
"""

import logging
from typing import Dict, Any, Optional

logger = logging.getLogger("vault-setup.tokens")

class TokenManager:
    """Manages Vault tokens for services."""
    
    def __init__(self, vault_client):
        """Initialize with vault client instance.

        Args:
            vault_client: The VaultClient instance
        """
        self.client = vault_client
        
    # Removed create_api_token method - root token is handled during initialization


    async def create_api_encryption_token(self, root_token: str, initializer) -> Optional[str]:
        """Create a token specifically for the API service's encryption needs, using the root token.

        Args:
            root_token: The root token obtained during initialization.
            initializer: The VaultInitializer instance (needed for saving the token).

        Returns:
            The created encryption token or None on failure
        """
        logger.info("Creating API encryption token")

        if not root_token:
            logger.error("Cannot create encryption token: No root token provided.")
            return None

        # Ensure the client is using the provided root token for this operation
        original_token = self.client.vault_token # Store current token
        self.client.update_token(root_token)

        try:
            # Check if a token already exists and is valid (optional, can simplify by always creating)
            # For simplicity, let's always create/replace the encryption token on setup run

            # Create a token with the api-encryption policy
            result = await self.client.vault_request("post", "auth/token/create", {
                "policies": ["api-encryption"],
                "display_name": "api-encryption-token",
                "ttl": "768h",  # 32 days, adjust as needed
                "renewable": True
            })

            if not result or "auth" not in result or "client_token" not in result["auth"]:
                 logger.error("Failed to create API encryption token: Invalid response from Vault.")
                 return None

            encryption_token = result["auth"]["client_token"]
            masked_token = f"{encryption_token[:4]}...{encryption_token[-4:]}" if len(encryption_token) >= 8 else "****"
            logger.info(f"API encryption token created successfully: {masked_token}")

            # Save *this specific token* to the api.token file for the EncryptionService
            if not initializer.save_api_token_only(encryption_token):
                 logger.error("Failed to save API encryption token to file!")
                 # Continue, but the API might not work correctly
            else:
                 logger.info(f"API encryption token saved to {initializer.api_token_file}")

            return encryption_token # Return the new token

        except Exception as e:
            logger.error(f"Failed to create API encryption token: {str(e)}")
            return None
        finally:
            # Restore the client's original token if it was different from the root token used
            if original_token and original_token != root_token:
                 self.client.update_token(original_token)
            # Otherwise, leave the client token as it is (likely the API token from initialization if Vault was already set up)