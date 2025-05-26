import logging
import aiohttp
import time

logger = logging.getLogger(__name__)

async def delete_user(
    self, 
    user_id: str, 
    deletion_type: str = "unknown", 
    reason: str = "unknown", 
    ip_address: str = None,
    device_fingerprint: str = None,
    details: dict = None
) -> bool:
    """
    Delete a user from Directus
    
    Parameters:
    - user_id: ID of the user to delete
    - deletion_type: Type of deletion (policy_violation, user_requested, admin_action)
    - reason: Specific reason for deletion
    - ip_address: IP address of the request that triggered the deletion (if available)
    - device_fingerprint: Device fingerprint of the request that triggered the deletion (if available)
    - details: Additional context about the deletion
    """
    try:
        # Log the deletion for compliance purposes
        from backend.core.api.app.services.compliance import ComplianceService
        compliance_service = ComplianceService()
        compliance_service.log_account_deletion(
            user_id=user_id,
            deletion_type=deletion_type,
            reason=reason,
            ip_address=ip_address,
            device_fingerprint=device_fingerprint,
            details=details or {"timestamp": int(time.time())}
        )
        
        # Ensure we have admin token - check auth_methods.py to see that admin_required is the parameter name
        await self.ensure_auth_token(admin_required=True)  # Changed from admin=True
        if not self.admin_token:
            logger.error("Failed to get admin token for user deletion")
            return False
            
        # Delete the user - use direct API call
        url = f"{self.base_url}/users/{user_id}"
        headers = {
            "Authorization": f"Bearer {self.admin_token}",
            "Content-Type": "application/json"
        }
        
        # Use aiohttp directly
        async with aiohttp.ClientSession() as session:
            async with session.delete(url, headers=headers) as response:
                success = response.status == 204
                
                if not success:
                    error_text = await response.text()
                    logger.error(f"Failed to delete user {user_id}. Status: {response.status}, Response: {error_text}")
                    return False
        
        # Log the deletion
        logger.info(f"User deleted: {user_id}")
        
        return True
        
    except Exception as e:
        logger.error(f"Error deleting user {user_id}: {str(e)}")
        return False
