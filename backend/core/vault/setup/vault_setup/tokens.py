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

    async def create_api_service_token(self, root_token: str, initializer, policies: list[str]) -> Optional[str]:
        """Create a token for the API service, using the root token.
        If a valid token already exists and has all the required policies, it will be used.
        Otherwise, a new token is created with the specified policies.

        Args:
            root_token: The root token obtained during initialization.
            initializer: The VaultInitializer instance (needed for saving the token).
            policies: A list of policy names to assign to the token.

        Returns:
            The created or existing service token or None on failure
        """
        if not policies:
            logger.error("Cannot create service token: No policies specified.")
            return None

        # First check if a valid token already exists with all required policies
        if os.path.exists(initializer.api_token_file):
            try:
                with open(initializer.api_token_file, 'r') as f:
                    existing_token_value = f.read().strip()
                if existing_token_value:
                    logger.info(f"Found existing API token in {initializer.api_token_file}, validating its policies: {policies}...")
                    
                    # Temporarily use the client's root token to look up the existing token's details
                    # This avoids issues if the existing_token_value itself doesn't have lookup-self permissions
                    # or if self.client is currently using a non-root token.
                    current_client_token = self.client.vault_token
                    self.client.update_token(root_token) # Use root for reliable lookup
                    
                    try:
                        # We need to pass the token we want to lookup in the payload for this endpoint
                        # when not using it for X-Vault-Token header.
                        # However, auth/token/lookup (with token in payload) is often restricted.
                        # A more reliable way if the existing_token_value *might* be valid is to
                        # temporarily set it as the client token and do a lookup-self.
                        
                        temp_client_for_lookup = self.client.__class__() # Create a temporary client instance
                        await temp_client_for_lookup.init_client() # Initialize its httpx client
                        temp_client_for_lookup.update_token(existing_token_value) # Set the token for this temp client
                        
                        lookup_result = await temp_client_for_lookup.vault_request("get", "auth/token/lookup-self", {}, ignore_errors=True)
                        await temp_client_for_lookup.close()

                    finally:
                        self.client.update_token(current_client_token) # Restore original client token

                    if lookup_result and lookup_result.get("data"):
                        token_data = lookup_result["data"]
                        if token_data.get("ttl", 0) > 0: # Check if token is not expired
                            existing_policies = set(token_data.get("policies", []))
                            required_policies_set = set(policies)
                            
                            # Remove 'default' policy from consideration if present, as it's often implicitly there
                            existing_policies.discard("default")
                            
                            if required_policies_set.issubset(existing_policies):
                                logger.info(f"Existing API token has all required policies ({policies}). Using existing token.")
                                return existing_token_value
                            else:
                                logger.info(f"Existing API token is valid but lacks some required policies. Has: {list(existing_policies)}, Requires: {policies}. Creating a new one.")
                        else:
                            logger.info("Existing API token is expired. Creating a new one.")
                    else:
                        logger.warning(f"Failed to lookup details for existing token or token is invalid. Response: {lookup_result}. Creating a new one.")
                else:
                    logger.info(f"Token file {initializer.api_token_file} is empty. Creating a new token.")
            except Exception as e:
                logger.warning(f"Could not read or validate existing token from {initializer.api_token_file}: {str(e)}. Creating a new API service token.")
        else:
            logger.info(f"No existing API service token file found at {initializer.api_token_file}. Creating a new one.")

        # If we get here, we need to create a new token
        logger.info(f"Creating new API service token with policies: {policies}")

        if not root_token:
            logger.error("Cannot create service token: No root token provided.")
            return None

        # Ensure the client is using the provided root token for this operation
        original_client_token_before_create = self.client.vault_token
        self.client.update_token(root_token)

        try:
            # Create a token with the specified policies
            token_payload = {
                "policies": policies,
                "display_name": f"api-token-{'-'.join(policies)}", # More descriptive display name
                "ttl": "768h",  # 32 days, adjust as needed
                "renewable": True
            }
            logger.debug(f"Creating token with payload: {token_payload}")
            result = await self.client.vault_request("post", "auth/token/create", token_payload)

            if not result or "auth" not in result or "client_token" not in result["auth"]:
                 logger.error(f"Failed to create API service token: Invalid response from Vault. Response: {result}")
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
            # Restore the client's original token
            self.client.update_token(original_client_token_before_create)