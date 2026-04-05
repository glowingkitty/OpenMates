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
        temp_root_token = None  # Track if we generated a temporary root token for cleanup
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

            # If still no root token (deleted after previous successful setup — expected on restart),
            # fall back to api.token for read-only verification steps. If api.token is also
            # invalid (e.g., Vault data was reset, token expired/revoked), generate a temporary
            # root token using the unseal key and perform a full setup to create a new api.token.
            if not root_token:
                api_token = initializer.get_api_token_from_file()
                if api_token:
                    logger.info("Using existing api.token for verification (root token not available — normal after first setup run).")
                    client.update_token(api_token)

                    # Validate the api.token is actually recognized by this Vault instance
                    # AND has enough remaining TTL to be useful. A token can become invalid if
                    # Vault data was reset, or if the token was revoked/expired. Even a valid
                    # token with < 24h remaining TTL should be replaced — Vault's default max_ttl
                    # of 768h (32 days) silently caps requested TTLs, so tokens expire sooner
                    # than the requested 8760h (1 year).
                    lookup = await client.vault_request("get", "auth/token/lookup-self", ignore_errors=True)
                    needs_recovery = False
                    if not lookup or "data" not in (lookup or {}):
                        logger.warning(
                            "api.token is invalid or unrecognized by Vault - "
                            "generating temporary root token for recovery..."
                        )
                        needs_recovery = True
                    else:
                        # Token is valid — check remaining TTL
                        remaining_ttl = lookup["data"].get("ttl", 0)
                        min_ttl_seconds = 86400  # 24 hours
                        if remaining_ttl < min_ttl_seconds:
                            remaining_hours = remaining_ttl / 3600
                            logger.warning(
                                f"api.token has only {remaining_hours:.1f}h remaining TTL "
                                f"(minimum: {min_ttl_seconds / 3600:.0f}h) — "
                                f"generating temporary root token to create fresh token..."
                            )
                            needs_recovery = True
                        else:
                            remaining_days = remaining_ttl / 86400
                            logger.info(f"api.token is valid with {remaining_days:.1f} days remaining TTL.")

                    if needs_recovery:
                        temp_root_token = await initializer.generate_temporary_root_token()
                        if temp_root_token:
                            root_token = temp_root_token
                            client.update_token(temp_root_token)
                            logger.info("Generated temporary root token — will perform full setup and create new api.token.")
                        else:
                            logger.error(
                                "Cannot recover: api.token needs replacement and temporary root token "
                                "generation failed. Check that the unseal key in vault-setup-data "
                                "matches this Vault instance."
                            )
                            sys.exit(1)
                else:
                    # No api.token on disk — try generating a temporary root token from the unseal key
                    logger.warning("No api.token found — generating temporary root token for full setup...")
                    temp_root_token = await initializer.generate_temporary_root_token()
                    if temp_root_token:
                        root_token = temp_root_token
                        client.update_token(temp_root_token)
                        logger.info("Generated temporary root token — will perform full setup.")
                    else:
                        logger.error(
                            "No root token, no api.token, and cannot generate temporary root token — "
                            "cannot proceed. Restore the root token via 'vault operator generate-root'."
                        )
                        sys.exit(1)

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
        
        if root_token:
            # Full setup: create/update policies, token, and migrate secrets.
            # Only possible with root token (which exists on first run; deleted afterwards for security).
            if not await policy_manager.create_api_policy():
                logger.error("Failed to create/ensure API service policy")
                sys.exit(1)

            if not await policy_manager.create_api_encryption_policy():
                logger.error("Failed to create/ensure API encryption policy")
                sys.exit(1)

            # Tune token auth max_ttl so our 8760h (1 year) TTL request is actually honored.
            # Vault's default max_ttl is 768h (32 days) which silently caps token TTLs,
            # causing tokens to expire far sooner than expected (the root cause of the
            # April 2026 production outage where all encryption failed after 32 days).
            logger.info("Tuning token auth method max_lease_ttl to 87600h (10 years)...")
            await client.vault_request("post", "sys/auth/token/tune", {
                "max_lease_ttl": "87600h"
            }, ignore_errors=True)
            logger.info("Token auth max_lease_ttl tuned successfully.")

            client.update_token(root_token)  # Ensure root token is active for token creation
            api_token_policies = ["api-encryption", "api-service"]
            logger.info(f"Attempting to create API service token with policies: {api_token_policies}")
            api_service_token = await token_manager.create_api_service_token(
                root_token=root_token,
                initializer=initializer,
                policies=api_token_policies
            )
            if not api_service_token:
                logger.error("Failed to create API service token.")
                sys.exit(1)
            else:
                logger.info("API service token created/saved.")
                # Write a sentinel file so wait-for-vault.sh knows this boot's token is ready.
                # The sentinel contains the current Unix timestamp so the API can verify it
                # is newer than the script's own start time — preventing it from using a
                # sentinel (and token) left over from a previous container run.
                import time as _time
                sentinel_path = os.path.join(os.path.dirname(initializer.api_token_file), "token.ready")
                with open(sentinel_path, "w") as _f:
                    _f.write(str(int(_time.time())))
                logger.info(f"Wrote token-ready sentinel to {sentinel_path}")

            # Migrate secrets to Vault and add any new ones
            await secrets_manager.migrate_secrets_to_vault()
            await secrets_manager.add_new_secrets_to_vault()
        else:
            # Root token unavailable (deleted after first successful setup — expected on every restart).
            # Engine checks above confirmed Vault is operational. Skip root-only operations
            # (policy creation, token creation) but still sync new secrets from .env.
            logger.info("Root token not available — skipping policy/token creation (already completed on first run).")
            logger.info("Existing api.token remains valid.")

            # Sync new secrets from environment: generate a temporary root token using the
            # unseal key, write any new SECRET__* env vars to Vault, then revoke the token.
            logger.info("Checking for new secrets to sync from environment...")
            temp_root = await initializer.generate_temporary_root_token()
            if temp_root:
                original_token = client.vault_token
                client.update_token(temp_root)
                try:
                    await secrets_manager.add_new_secrets_to_vault()
                finally:
                    # Restore API token and revoke the temporary root token
                    client.update_token(original_token)
                    await initializer.revoke_token(temp_root)
            else:
                logger.warning("Could not generate temporary root token — skipping secret sync. "
                               "New SECRET__* env vars will NOT be imported until next first-run setup.")
        
        # Final instructions
        logger.info("="*80)
        logger.info("Vault Setup Actions Completed")
        logger.info("="*80)
        logger.critical("REMINDER: If Vault was initialized for the first time, ensure you have securely backed up the ROOT TOKEN and UNSEAL KEY shown earlier.")
        logger.info(f"API Service will use the token saved in {initializer.api_token_file} for encryption tasks.")
        if secrets_manager.initial_migration_processed_count > 0:
             logger.info(f"API secrets ({secrets_manager.initial_migration_processed_count} processed) were imported from environment variables into Vault during this setup run.")
             logger.info("The original values in .env have been automatically replaced with 'IMPORTED_TO_VAULT'.")

        logger.info("You can manage Vault secrets and configuration via the Vault Web UI or CLI.")
        logger.info(f"Vault Address: {client.vault_addr} (Port may need exposing via Docker Compose for UI access).")
        logger.info("Use the backed-up root token for full access, or create other tokens/roles as needed.")
        logger.info("="*80)

        # SECURITY: Delete the root token file from the shared volume after setup is complete.
        # The root token was only needed for initial Vault configuration (policies, service tokens,
        # secret migration). Leaving it on disk means any compromised container mounting the volume
        # gains full Vault root access. The unseal key file is kept (needed for auto-unseal).
        if os.path.exists(initializer.token_file):
            try:
                os.remove(initializer.token_file)
                logger.info(f"SECURITY: Deleted root token file {initializer.token_file} — no longer needed after setup.")
            except Exception as e_del:
                logger.error(f"SECURITY WARNING: Failed to delete root token file {initializer.token_file}: {e_del}")
                logger.error("The root token remains on the shared volume. Manual removal recommended.")

        # SECURITY: Revoke the temporary root token if one was generated during this run.
        # The temp root was only needed to recreate policies and api.token; keeping it alive
        # is an unnecessary privilege escalation risk.
        if temp_root_token:
            await initializer.revoke_token(temp_root_token)
            logger.info("SECURITY: Revoked temporary root token used for recovery setup.")

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
