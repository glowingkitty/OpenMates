#!/usr/bin/env python3
"""
Vault Setup Script for OpenMates

This script sets up HashiCorp Vault for the OpenMates application:
1. Initializes Vault if needed
2. Unseals Vault if sealed
3. Enables necessary secret engines (transit, kv)
4. Creates policies for the API service
5. Creates a token for the API service
6. Migrates secrets from environment variables to Vault
"""

import os
import asyncio
import sys
import logging

from vault_setup import (
    VaultClient,
    VaultInitializer,
    SecretEngines,
    PolicyManager,
    TokenManager,
    SecretsManager,
    setup_logging
)

# Configure logging
setup_logging()
logger = logging.getLogger("vault-setup")

async def setup_vault():
    """Main setup routine for Vault."""
    try:
        # Initialize the Vault client
        client = VaultClient()
        await client.init_client()
        
        # Wait for Vault to become available
        try:
            status_code, health_data = await client.wait_for_vault()
        except Exception as e:
            logger.error(f"Could not connect to Vault: {str(e)}")
            sys.exit(1)
        
        # Initialize the component managers
        initializer = VaultInitializer(client)
        engines = SecretEngines(client)
        policy_manager = PolicyManager(client)
        token_manager = TokenManager(client)
        secrets_manager = SecretsManager(client)
        
        # If Vault is not initialized, initialize it
        root_token = None # Initialize root_token variable
        if not health_data.get("initialized", False):
            logger.info("Vault needs to be initialized")
            # Initialize and capture the root token
            init_success, root_token = await initializer.initialize_vault()
            if not init_success:
                logger.error("Failed to initialize Vault")
                sys.exit(1)
            if not root_token:
                 logger.error("Initialization reported success but did not return root token.")
                 sys.exit(1)
            logger.info("Vault initialized, proceeding with setup using root token.")
        else:
            # Vault is already initialized
            # First try to load the saved root token
            root_token = initializer.load_root_token()
            
            if root_token:
                logger.info("Loaded saved root token for administrative tasks")
                client.update_token(root_token)
            else:
                logger.warning("No saved root token found. Will attempt to use VAULT_TOKEN environment variable.")
            
            # If Vault is sealed, try to unseal it
            if health_data.get("sealed", True):
                logger.info("Vault is sealed, attempting auto-unseal")
                if not initializer.auto_unseal:
                    logger.info("Auto-unsealing disabled, skipping")
                elif not await initializer.unseal_vault():
                    logger.error("Auto-unsealing failed")
                    sys.exit(1)
                
                # After unsealing, check our token situation again if needed
                if not root_token:
                    root_token = initializer.load_root_token()
                    if root_token:
                        logger.info("Loaded saved root token after unsealing")
                        client.update_token(root_token)
            
            logger.info("Vault already initialized, proceeding with setup.")
        
        # Check and enable transit engine if needed
        if not await engines.check_transit_engine():
            if not await engines.enable_transit_engine():
                logger.error("Failed to enable transit engine")
                sys.exit(1)
        else:
            logger.info("Transit secrets engine is already enabled")
        
        # Enable KV v2 engine for storing API keys
        if not await engines.enable_kv_engine():
            logger.error("Failed to enable KV engine")
            sys.exit(1)
        
        # Create API service policy
        if not await policy_manager.create_api_policy():
            logger.error("Failed to create/ensure API service policy")
            sys.exit(1)

        # Create API encryption policy
        if not await policy_manager.create_api_encryption_policy():
             logger.error("Failed to create/ensure API encryption policy")
             sys.exit(1)
        
        # Create the API service token - always try to use the root token if available
        if root_token:
             client.update_token(root_token)  # Ensure we're using root token for this operation
             
             # Define the policies for the API service token
             # 'api-encryption' for all transit-related operations (encryption, decryption, key management, hmac)
             # 'api-service' for other operations like KV store access and token self-lookup
             api_token_policies = ["api-encryption", "api-service"]
             logger.info(f"Attempting to create API service token with policies: {api_token_policies}")

             api_service_token = await token_manager.create_api_service_token(
                 root_token=root_token,
                 initializer=initializer,
                 policies=api_token_policies  # Assuming TokenManager accepts a 'policies' argument
             )
             if not api_service_token:
                 logger.error("Failed to create API service token.")
                 sys.exit(1)
             else:
                 logger.info("API service token created/saved.")
        else:
             # If we got this far without a root token, we might be using an API token
             # that doesn't have permissions to create new tokens
             logger.warning("No root token available; cannot automatically create API service token.")
             logger.warning("Ensure an API service token exists and is saved in /app/data/api.token (or the configured path) for the API service.")
        
        # Migrate secrets to Vault and add any new ones
        await secrets_manager.migrate_secrets_to_vault()
        await secrets_manager.add_new_secrets_to_vault()
        
        # Final instructions
        logger.info("="*80)
        logger.info("Vault Setup Actions Completed")
        logger.info("="*80)
        logger.critical("REMINDER: If Vault was initialized for the first time, ensure you have securely backed up the ROOT TOKEN and UNSEAL KEY shown earlier.")
        logger.info(f"API Service will use the token saved in {initializer.api_token_file} for encryption tasks.")
        if secrets_manager.initial_migration_processed_count > 0:
             logger.warning(f"API secrets ({secrets_manager.initial_migration_processed_count} processed) were imported from environment variables (likely sourced from your .env file) during this setup run.")
             logger.warning("For security, please MANUALLY REMOVE or comment out the original SECRET__* lines from your .env file after verifying they are in Vault.")
             logger.warning("Consider adding a comment like '# API secrets are managed in Vault' to your .env file.")

        logger.info("You can manage Vault secrets and configuration via the Vault Web UI or CLI.")
        logger.info(f"Vault Address: {client.vault_addr} (Port may need exposing via Docker Compose for UI access).")
        logger.info("Use the backed-up root token for full access, or create other tokens/roles as needed.")
        logger.info("="*80)

        logger.info("Vault setup script finished.")
        
    except Exception as e:
        logger.error(f"Vault setup failed: {str(e)}")
        sys.exit(1)
    finally:
        # Clean up
        if 'client' in locals():
            await client.close()

if __name__ == "__main__":
    asyncio.run(setup_vault())
