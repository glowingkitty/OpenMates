import logging

logger = logging.getLogger(__name__)

async def get_user_credits(self, user_id: str) -> int:
    """
    Get a user's credit balance
    - Decrypts the encrypted_credit_balance field
    - Returns the credit balance as an integer
    """
    try:
        # Get the user data
        url = f"{self.base_url}/users/{user_id}"
        response = await self._make_api_request("GET", url)
        
        if response.status_code != 200:
            logger.warning(f"Failed to retrieve user: {response.status_code}")
            return 0
            
        user_data = response.json().get("data", {})
        vault_key_id = user_data.get("vault_key_id")
        encrypted_credit_balance = user_data.get("encrypted_credit_balance")
        
        # If no vault key or encrypted balance, return 0
        if not vault_key_id or not encrypted_credit_balance:
            return 0
        
        # Decrypt the credit balance
        try:
            decrypted_credits = await self.encryption_service.decrypt_with_user_key(
                encrypted_credit_balance, vault_key_id
            )
            
            # Convert to integer
            try:
                return int(decrypted_credits)
            except ValueError:
                # If it can't be converted to int, try float and then convert to int
                try:
                    return int(float(decrypted_credits))
                except ValueError:
                    logger.error(f"Invalid credit balance format: {decrypted_credits}")
                    return 0
                
        except Exception as e:
            logger.error(f"Error decrypting credit balance: {str(e)}")
            return 0
            
    except Exception as e:
        logger.error(f"Error getting user credits: {str(e)}", exc_info=True)
        return 0
