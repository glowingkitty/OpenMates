"""
Functions for managing Vault tokens.
"""

import logging
import os
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
        
    async def validate_existing_token(self, token: str) -> bool:
        """Validate if a token is still valid and has the required permissions.
        
        Args:
            token: The token to validate
            
        Returns:
            True if token is valid, False otherwise
        """
        original_token = self.client.vault_token
        try:
            # Temporarily use the token to check
            self.client.update_token(token)
            
            # First and most reliable way: check the token's own information
            lookup_result = await self.client.vault_request("get", "auth/token/lookup-self", {}, ignore_errors=True)
            
            # If the token has the right policy, it's valid
            if lookup_result and "data" in lookup_result and "policies" in lookup_result["data"]:
                if "api-encryption" in lookup_result["data"]["policies"]:
                    logger.info("Existing API token has the required policies")
                    return True
            
            # If we get here, the token lookup didn't work or didn't have the right policy
            # As a fallback, we could try a simple operation, but that might fail due to missing resources
            # rather than invalid token. For example, on first run there won't be api-encryption transit key yet.
            
            # Check if token is not expired
            if lookup_result and "data" in lookup_result and "ttl" in lookup_result["data"]:
                if lookup_result["data"]["ttl"] > 0:
                    logger.info("Existing token is valid but may not have all required permissions")
                    # Even if it doesn't have right permissions now, we'll update policies later
                    return True
                    
            logger.warning("Existing API token failed validation")
            return False
            
        except Exception as e:
            logger.warning(f"Error validating existing token: {str(e)}")
            return False
        finally:
            # Restore original token
            self.client.update_token(original_token)

    async def create_api_service_token(self, root_token: str, initializer) -> Optional[str]:
        """Create a token for the API service, using the root token.
        If a valid token already exists, will use that instead of creating a new one.

        Args:
            root_token: The root token obtained during initialization.
            initializer: The VaultInitializer instance (needed for saving the token).

        Returns:
            The created or existing service token or None on failure
        """
        # First check if a valid token already exists
        if os.path.exists(initializer.api_token_file):
            try:
                with open(initializer.api_token_file, 'r') as f:
                    existing_token = f.read().strip()
                if existing_token:
                    logger.info("Found existing API token, validating...")
                    # We still validate against the 'api-encryption' policy here
                    # because the 'api-service' policy *includes* all 'api-encryption' permissions.
                    # If the existing token has 'api-service', it will pass this check.
                    # If it only has 'api-encryption', we'll create a new one with 'api-service'.
                    if await self.validate_existing_token(existing_token):
                        # Check if the valid existing token *already* has the broader 'api-service' policy
                        lookup_result = await self.client.vault_request("get", "auth/token/lookup-self", {"token": existing_token}, ignore_errors=True)
                        if lookup_result and "data" in lookup_result and "policies" in lookup_result["data"] and "api-service" in lookup_result["data"]["policies"]:
                             logger.info("Using existing API service token (already has correct policy)")
                             return existing_token
                        else:
                             logger.info("Existing API token is valid but lacks 'api-service' policy, creating a new one")
                    else:
                        logger.info("Existing API token is invalid, creating a new one")
            except Exception as e:
                logger.warning(f"Could not read or validate existing token: {str(e)}")
                logger.info("Will create a new API service token")
        else:
            logger.info("No existing API service token found, creating a new one")

        # If we get here, we need to create a new token
        logger.info("Creating new API service token")

        if not root_token:
            logger.error("Cannot create service token: No root token provided.")
            return None

        # Ensure the client is using the provided root token for this operation
        original_token = self.client.vault_token # Store current token
        self.client.update_token(root_token)

        try:
            # Create a token with the api-service policy
            result = await self.client.vault_request("post", "auth/token/create", {
                "policies": ["api-service"], # Use the broader policy
                "display_name": "api-service-token",
                "ttl": "768h",  # 32 days, adjust as needed
                "renewable": True
            })

            if not result or "auth" not in result or "client_token" not in result["auth"]:
                 logger.error("Failed to create API service token: Invalid response from Vault.")
                 return None

            service_token = result["auth"]["client_token"]
            masked_token = f"{service_token[:4]}...{service_token[-4:]}" if len(service_token) >= 8 else "****"
            logger.info(f"API service token created successfully: {masked_token}")

            # Save *this specific token* to the api.token file for the API service
            if not initializer.save_api_token_only(service_token):
                 logger.error("Failed to save API service token to file!")
                 # Continue, but the API might not work correctly
            else:
                 logger.info(f"API service token saved to {initializer.api_token_file}")

            return service_token # Return the new token

        except Exception as e:
            logger.error(f"Failed to create API service token: {str(e)}")
            return None
        finally:
            # Restore the client's original token if it was different from the root token used
            if original_token and original_token != root_token:
                 self.client.update_token(original_token)
            # Otherwise, leave the client token as it is