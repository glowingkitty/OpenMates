"""
Functions for initializing and unsealing Vault.
"""

import os
import logging
import stat
from typing import Optional, Tuple

logger = logging.getLogger("vault-setup.initialization")

class VaultInitializer:
    """Handles initialization and unsealing of the Vault server."""
    
    def __init__(self, vault_client):
        """Initialize with a vault client instance.
        
        Args:
            vault_client: The VaultClient instance
        """
        self.client = vault_client
        self.unseal_key_file = "/app/data/unseal.key"
        self.token_file = "/app/data/root.token"
        self.api_token_file = "/app/data/api.token"
        self.auto_unseal = os.environ.get("VAULT_AUTO_UNSEAL", "true").lower() == "true"

    def save_unseal_key(self, unseal_key: str) -> bool:
        """Save unseal key to a restricted access file.
        
        Args:
            unseal_key: The key to save
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Check if the file already exists, don't overwrite
            if os.path.exists(self.unseal_key_file):
                logger.info("Unseal key file already exists, not overwriting")
                return True
                
            # Create directory if it doesn't exist
            os.makedirs(os.path.dirname(self.unseal_key_file), exist_ok=True)
            
            # Write key to file
            with open(self.unseal_key_file, 'w') as f:
                f.write(unseal_key)
            
            # Set restrictive permissions (600 - owner read/write only)
            os.chmod(self.unseal_key_file, stat.S_IRUSR | stat.S_IWUSR)
            
            logger.info(f"Saved unseal key to {self.unseal_key_file}")
            return True
        except Exception as e:
            logger.error(f"Failed to save unseal key: {str(e)}")
            return False
    
    def save_root_token(self, root_token: str) -> bool:
        """Save root token to a restricted access file.
        
        This is used ONLY by the setup script to maintain its ability to configure
        Vault across container restarts. The root token is still displayed for manual
        backup during initialization.
        
        Args:
            root_token: The token to save
            
        Returns:
            True if successful, False otherwise
        """
        try:
            os.makedirs(os.path.dirname(self.token_file), exist_ok=True)
            with open(self.token_file, 'w') as f:
                f.write(root_token)
            # Use very restrictive permissions (600 - owner read/write only)
            os.chmod(self.token_file, stat.S_IRUSR | stat.S_IWUSR)
            logger.info(f"Saved root token to {self.token_file} for setup script use")
            return True
        except Exception as e:
            logger.error(f"Failed to save root token: {str(e)}")
            return False

    def save_api_token_only(self, api_token: str) -> bool:
        """Save API token specifically to the API token file."""
        try:
            os.makedirs(os.path.dirname(self.api_token_file), exist_ok=True)
            with open(self.api_token_file, 'w') as f:
                f.write(api_token)
            # SECURITY: Use 640 permissions (owner rw, group r, no world access).
            # The API service containers run in the same group context on the shared volume.
            # Previous 644 (world-readable) exposed the token to any process in any container.
            os.chmod(self.api_token_file, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP)  # 640
            logger.debug(f"Saved API token specifically to {self.api_token_file}") # Keep as debug
            return True
        except Exception as e:
            logger.error(f"Failed to save API token to {self.api_token_file}: {str(e)}")
            return False
    
    def get_saved_unseal_key(self) -> Optional[str]:
        """Get saved unseal key if available.
        
        Returns:
            The unseal key or None if not available
        """
        try:
            if os.path.exists(self.unseal_key_file):
                with open(self.unseal_key_file, 'r') as f:
                    unseal_key = f.read().strip()
                logger.info("Retrieved saved unseal key")
                return unseal_key
            return None
        except Exception as e:
            logger.error(f"Failed to read unseal key: {str(e)}")
            return None
    
    def load_root_token(self) -> Optional[str]:
        """Get saved root token if available.
        
        Returns:
            The root token or None if not available
        """
        try:
            if os.path.exists(self.token_file):
                with open(self.token_file, 'r') as f:
                    root_token = f.read().strip()
                logger.info("Retrieved saved root token")
                return root_token
            logger.warning("No saved root token file found")
            return None
        except Exception as e:
            logger.error(f"Failed to read root token: {str(e)}")
            return None
    
    async def initialize_vault(self) -> Tuple[bool, Optional[str]]:
        """Initialize Vault if not already initialized.

        Returns:
            Tuple of (success_status, root_token or None)
        """
        try:
            # Check if Vault is already initialized
            response = await self.client._client.get(f"{self.client.vault_addr}/v1/sys/init")
            response.raise_for_status()
            
            init_status = response.json()
            if init_status.get("initialized", False):
                logger.info("Vault is already initialized")
                # Vault already initialized, we don't have the original root token.
                # Setup should proceed assuming policies/tokens might exist or need checking.
                # We cannot return the original root token here.
                logger.warning("Vault already initialized. Cannot retrieve original root token.")
                logger.warning("Setup will proceed, checking existing configuration.")
                # Try to get *a* token from the API file if it exists, maybe it's usable?
                api_token = self.get_api_token_from_file()
                if api_token:
                     self.client.update_token(api_token)
                     logger.info("Using token found in api.token file for subsequent operations.")
                     # We return None for root_token as it's not the *original* root.
                     return True, None
                else:
                     # Cannot proceed without any token if already initialized and no API token saved
                     logger.error("Vault already initialized but no usable token found in api.token file.")
                     return False, None

                
            # Initialize Vault
            logger.info("Initializing Vault...")
            init_response = await self.client._client.post(
                f"{self.client.vault_addr}/v1/sys/init",
                json={
                    "secret_shares": 1,     # For development, just a single share
                    "secret_threshold": 1   
                }
            )
            init_response.raise_for_status()
            
            credentials = init_response.json()
            
            # Store the keys for future use
            root_token = credentials['root_token']
            unseal_key = credentials['keys'][0]
            
            # Save keys only if they don't already exist
            self.save_unseal_key(unseal_key)
            # Save root token for setup script use (not for API)
            self.save_root_token(root_token)
            
            # Display the keys clearly ONCE for manual backup
            print("\n" + "="*80, flush=True)
            print("VAULT INITIALIZED - CRITICAL INFORMATION BELOW", flush=True)
            print("="*80, flush=True)
            print(f"ROOT TOKEN: {root_token}", flush=True)
            print(f"UNSEAL KEY: {unseal_key}", flush=True)
            print("\n" + "="*80, flush=True)
            print("IMPORTANT: Copy the ROOT TOKEN and UNSEAL KEY above and save them securely OFFLINE now!", flush=True)
            print("           You will NOT see them again. They are required for recovery.", flush=True)
            print(f"           (The unseal key has also been saved to {self.unseal_key_file} for auto-unsealing)", flush=True)
            print("="*80 + "\n", flush=True)
            
            # Update the root token in the client
            self.client.update_token(root_token)
            
            # Unseal Vault
            await self.unseal_vault(unseal_key)
            # Return success and the root token for the setup script to use
            return True, root_token
            
        except Exception as e:
            logger.error(f"Failed to initialize Vault: {str(e)}")
            return False, None
    
    async def unseal_vault(self, unseal_key: Optional[str] = None) -> bool:
        """Unseal Vault if it's sealed.
        
        Args:
            unseal_key: Unseal key to use (optional, will look for saved key if not provided)
            
        Returns:
            True if Vault is unsealed (either already or after unsealing), False otherwise
        """
        try:
            # Check seal status
            status = await self.client.check_vault_status()
            
            if status and not status.get("sealed", True):
                logger.info("Vault is already unsealed")
                return True
            
            if not self.auto_unseal:
                logger.info("Auto-unsealing is disabled, skipping")
                return False
            
            if not unseal_key:
                # Try to get from saved file first
                unseal_key = self.get_saved_unseal_key()
                
            if not unseal_key:
                # If still no key, report the error
                logger.error("No unseal key provided or found - cannot unseal Vault")
                print("\n" + "="*80)
                print("VAULT IS SEALED - MANUAL UNSEALING REQUIRED")
                print("="*80)
                print("No unseal key found. You need to manually unseal Vault:")
                print("1. Get your unseal key")
                print("2. Run: docker exec -it vault vault operator unseal <key>")
                print("3. Or set VAULT_AUTO_UNSEAL=false if you prefer manual unsealing")
                print("="*80 + "\n")
                return False
                
            # Unseal vault
            logger.info("Unsealing Vault...")
            unseal_response = await self.client._client.post(
                f"{self.client.vault_addr}/v1/sys/unseal",
                json={"key": unseal_key}
            )
            unseal_response.raise_for_status()
            
            # Verify it's unsealed
            result = unseal_response.json()
            if not result.get("sealed", True):
                logger.info("Vault unsealed successfully")
                
                # After unsealing, we need to make sure we're using the root token for setup tasks
                # Check if we already have a saved root token (from previous initialization)
                root_token = self.load_root_token()
                
                if root_token:
                    logger.info("Using saved root token after unsealing for administrative tasks")
                    self.client.update_token(root_token)
                    return True
                else:
                    # If no root token is available, try the API token as a fallback
                    # This is not ideal but better than having no token at all
                    api_token = self.get_api_token_from_file()
                    if api_token:
                        logger.warning("No root token found, falling back to API token after unsealing (limited functionality)")
                        self.client.update_token(api_token)
                        return True
                    else:
                        # This is problematic - initialized, unsealed, but no token found.
                        logger.error("Vault unsealed, but no token found in api.token or root.token files.")
                        logger.error("Manual intervention required using the backed-up root token.")
                        return False
                
                return True
            else:
                logger.warning("Vault is still sealed after unseal attempt")
                return False
            
        except Exception as e:
            logger.error(f"Failed to unseal Vault: {str(e)}")
            return False

    async def generate_temporary_root_token(self) -> Optional[str]:
        """Generate a temporary root token using the unseal key.

        Uses the Vault generate-root workflow (init → provide unseal key → decode).
        This allows vault-setup to perform privileged operations (secret sync, policy
        updates) on every restart without storing the root token on disk.

        Returns:
            A temporary root token, or None if generation fails.
        """
        unseal_key = self.get_saved_unseal_key()
        if not unseal_key:
            logger.warning("No unseal key available — cannot generate temporary root token.")
            return None

        try:
            # Step 1: Cancel any in-progress generation
            await self.client._client.delete(
                f"{self.client.vault_addr}/v1/sys/generate-root/attempt",
            )

            # Step 2: Start a new generate-root attempt
            init_resp = await self.client._client.put(
                f"{self.client.vault_addr}/v1/sys/generate-root/attempt",
                json={},
            )
            init_resp.raise_for_status()
            init_data = init_resp.json()
            nonce = init_data["nonce"]
            otp = init_data["otp"]

            # Step 3: Provide the unseal key
            update_resp = await self.client._client.put(
                f"{self.client.vault_addr}/v1/sys/generate-root/update",
                json={"key": unseal_key, "nonce": nonce},
            )
            update_resp.raise_for_status()
            update_data = update_resp.json()

            if not update_data.get("complete"):
                logger.error("Root token generation did not complete (unexpected — threshold=1).")
                return None

            encoded_token = update_data["encoded_root_token"]

            # Step 4: Decode the encoded token using the OTP via XOR.
            # Vault 1.x returns base64url(xor(token, otp)) — decode client-side.
            root_token = self._xor_decode_root_token(encoded_token, otp)

            if root_token:
                logger.info("Generated temporary root token for secret sync.")
                return root_token

            logger.error("Failed to decode temporary root token.")
            return None

        except Exception as e:
            logger.error(f"Failed to generate temporary root token: {e}", exc_info=True)
            # Cancel any in-progress attempt on failure
            try:
                await self.client._client.delete(
                    f"{self.client.vault_addr}/v1/sys/generate-root/attempt",
                )
            except Exception:
                pass
            return None

    @staticmethod
    def _xor_decode_root_token(encoded_token: str, otp: str) -> Optional[str]:
        """Decode a Vault encoded root token using XOR with the OTP.

        Vault (1.x+) encodes: base64url(xor(token_bytes, otp_bytes)).
        After XOR the result is the raw token string (UTF-8).
        The OTP is a raw ASCII string (not base64-encoded).
        """
        import base64
        try:
            # encoded_token is base64url without padding
            padded = encoded_token + "=" * (-len(encoded_token) % 4)
            token_bytes = base64.urlsafe_b64decode(padded)
            # OTP is a raw string — use its bytes directly
            otp_bytes = otp.encode("utf-8")
            xored = bytes(a ^ b for a, b in zip(token_bytes, otp_bytes))
            result = xored.decode("utf-8").rstrip("\x00")
            if result:
                return result
            logger.error("XOR decode produced empty result.")
            return None
        except UnicodeDecodeError:
            # Fallback: OTP might be base64url-encoded in some Vault versions
            try:
                otp_bytes = base64.urlsafe_b64decode(otp + "=" * (-len(otp) % 4))
                xored = bytes(a ^ b for a, b in zip(token_bytes, otp_bytes))
                result = xored.decode("utf-8").rstrip("\x00")
                return result if result else None
            except Exception as e2:
                logger.error(f"XOR decode failed (both raw and b64 OTP): {e2}")
                return None
        except Exception as e:
            logger.error(f"XOR decode failed: {e}")
            return None

    async def revoke_token(self, token: str) -> None:
        """Revoke a Vault token."""
        try:
            await self.client._client.put(
                f"{self.client.vault_addr}/v1/auth/token/revoke-self",
                headers={"X-Vault-Token": token},
                json={},
            )
            logger.info("Temporary root token revoked.")
        except Exception as e:
            logger.warning(f"Failed to revoke temporary root token: {e}")

    def get_api_token_from_file(self) -> Optional[str]:
        """Reads the token from the api.token file."""
        try:
            if os.path.exists(self.api_token_file):
                with open(self.api_token_file, 'r') as f:
                    token = f.read().strip()
                if token:
                    # logger.debug("Retrieved token from api.token file.") # Keep debug
                    return token
                else:
                    logger.warning(f"API token file found but empty: {self.api_token_file}")
            # else: logger.debug(f"API token file not found at {self.api_token_file}") # Keep debug
            return None
        except Exception as e:
            logger.error(f"Failed to read API token file {self.api_token_file}: {str(e)}")
            return None