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
        token_manager = TokenManager(client) # Initializer no longer needed in constructor
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
                 # This shouldn't happen if init_success is True, but safety check
                 logger.error("Initialization reported success but did not return root token.")
                 sys.exit(1)
            # Client token is set to root_token inside initialize_vault
            logger.info("Vault initialized, proceeding with setup using root token.")
        elif health_data.get("sealed", True):
            # Vault is initialized but sealed - try auto unsealing
            logger.info("Vault is sealed, attempting auto-unseal")
            if not initializer.auto_unseal:
                logger.info("Auto-unsealing disabled, skipping")
            elif not await initializer.unseal_vault():
                # Only exit if auto-unsealing is enabled but failed
                logger.error("Auto-unsealing failed")
                sys.exit(1)
        else:
            # Vault is unsealed, check for saved token
            # Vault already initialized. initialize_vault tried to load api.token.
            # Check if the client has a token now.
            if not client.vault_token:
                 logger.error("Vault already initialized, but failed to load a usable token (e.g., from api.token).")
                 logger.error("Manual intervention required using the backed-up root token.")
                 sys.exit(1)
            logger.info("Vault already initialized, proceeding with setup using loaded token.")
            # root_token remains None in this case, operations will use the loaded token.
        
        # Check and enable transit engine if needed
        if not await engines.check_transit_engine():
            if not await engines.enable_transit_engine():
                logger.error("Failed to enable transit engine")
        else:
            logger.info("Transit secrets engine is already enabled")
        
        # Enable KV v2 engine for storing API keys
        if not await engines.enable_kv_engine():
            logger.error("Failed to enable KV engine")
        
        # Create API service policy
        # Ensure the client is using the root token if we have it for policy creation
        if root_token:
             client.update_token(root_token)

        # Create/Ensure general API service policy exists
        if not await policy_manager.create_api_policy():
            logger.error("Failed to create/ensure API service policy")
            # Decide if this is fatal? Maybe not if it already exists.

        # Create/Ensure specific API encryption policy exists
        if not await policy_manager.create_api_encryption_policy():
             logger.error("Failed to create/ensure API encryption policy")
             # Decide if this is fatal? Maybe not if it already exists.

        # Restore token if we switched to root (might be API token if Vault was already init)
        # The token_manager will switch to root temporarily if needed anyway.
        # Let's ensure the client has *some* valid token before proceeding.
        if not client.vault_token:
             logger.error("Lost Vault client token before creating encryption token.")
             sys.exit(1)
        
        # Create the specific token for the API encryption service
        # Pass the root_token (if available) and the initializer instance
        if root_token:
             api_enc_token = await token_manager.create_api_encryption_token(root_token=root_token, initializer=initializer)
             if not api_enc_token:
                 logger.error("Failed to create API encryption token using root token.")
                 # This might be critical, decide whether to exit
                 # sys.exit(1)
             else:
                 logger.info("API encryption token created/saved.")
        else:
             # If Vault was already initialized, we don't have the root token.
             # We cannot create the specific API encryption token automatically in this case.
             # The user would need to create it manually or re-run setup after deleting Vault data.
             logger.warning("Vault was already initialized; cannot automatically create API encryption token without root token.")
             logger.warning("Ensure an API encryption token exists and is saved in /app/data/api.token for the API service.")

        # Restore client token state if needed (though create_api_encryption_token should handle its temporary use of root)
        # If Vault was already initialized, client.token should be the API token.
        # If Vault was just initialized, client.token should be the root token.
        # Let's set it to the newly created API token if we have it, otherwise leave as root/loaded API token.
        # This is tricky. Let's rely on the api.token file being read by the EncryptionService itself.
        # The setup script doesn't need to guarantee the client token state after this point.
        
        # First migration: If this is the first setup, migrate all secrets from .env
        await secrets_manager.migrate_secrets_to_vault()
        
        # Second step: Check for new API_SECRET__ variables and add them to vault
        await secrets_manager.add_new_secrets_to_vault()
        
        # Final instructions
        logger.info("="*80)
        logger.info("Vault Setup Actions Completed")
        logger.info("="*80)
        logger.critical("REMINDER: If Vault was initialized for the first time, ensure you have securely backed up the ROOT TOKEN and UNSEAL KEY shown earlier.")
        logger.info(f"API Service will use the token saved in {initializer.api_token_file} for encryption tasks.")
        if secrets_manager.secrets_imported:
             logger.warning("API secrets were imported from environment variables (likely sourced from your .env file).")
             logger.warning("For security, please MANUALLY REMOVE or comment out the original API_SECRET__* lines from your .env file.")
             logger.warning("Consider adding a comment like '# API secrets are managed in Vault' to your .env file.")

        logger.info("You can manage Vault secrets and configuration via the Vault Web UI or CLI.")
        logger.info(f"Vault Address: {client.vault_addr} (Port may need exposing via Docker Compose for UI access).")
        logger.info(f"Use the backed-up root token for full access, or create other tokens/roles as needed.")
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
