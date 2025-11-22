import logging
import json
from datetime import datetime
from typing import Optional, Dict, Any, Union
import ipaddress
from datetime import datetime # Ensure datetime is imported

# Configure a special logger for compliance events
compliance_logger = logging.getLogger("compliance")
# Get the standard logger for API events
api_logger = logging.getLogger(__name__)
# Get the specialized event logger for important business events
event_logger = logging.getLogger("app.events")

class ComplianceService:
    """
    Service for tracking compliance-related events that need to be stored
    according to regulatory requirements.
    """
    
    @staticmethod
    def log_auth_event(
        event_type: str, 
        user_id: Optional[str],
        ip_address: str,
        status: str = "success",
        details: Optional[Dict[str, Any]] = None
    ):
        """
        Log an authentication-related compliance event
        
        Args:
            event_type: Type of event (login, logout, password_reset, etc)
            user_id: User ID (if known)
            ip_address: Client IP address
            status: Outcome of the event (success, failed)
            details: Additional details to log (will be sanitized)
        """
        # Validate IP address to avoid injection
        try:
            # This will raise ValueError if invalid
            ipaddress.ip_address(ip_address)
        except ValueError:
            ip_address = "0.0.0.0"  # Use a placeholder for invalid IPs
            
        # Create log entry
        log_data = {
            "timestamp": datetime.utcnow().isoformat(),
            "event_type": event_type,
            "user_id": user_id or "anonymous",  # Never redact user_id in compliance logs
            "ip_address": ip_address,
            "status": status
        }
        
        # Add details if provided (sanitize as needed)
        if details:
            # Filter out any sensitive fields
            sanitized_details = {k: v for k, v in details.items() 
                              if k not in ['password', 'token', 'secret']}
            log_data["details"] = sanitized_details
            
        # Log the raw dictionary - let the JSON handler format it
        compliance_logger.info(log_data)
    
    @staticmethod
    def log_user_creation(
        user_id: str,
        # device_fingerprint and location removed as per requirements
        status: str = "success",
        details: Optional[Dict[str, Any]] = None
    ):
        """
        Log a user creation event and subsequent consents for compliance.
        For privacy reasons, user creation and consent logs do NOT store
        IP address, device fingerprint, or location information.
        
        Args:
            user_id: Newly created user ID
            status: Outcome of the creation (success, failed)
            details: Additional details to log (will be sanitized)
        """
        # Create log entry for user creation (without IP, device, location)
        log_data = {
            "timestamp": datetime.utcnow().isoformat(),
            "event_type": "user_creation",
            "user_id": user_id,
            "status": status
        }
        
        if details:
            sanitized_details = {k: v for k, v in details.items() 
                              if k not in ['password', 'token', 'secret']}
            log_data["details"] = sanitized_details
            
        # Log the raw dictionary - let the JSON handler format it
        compliance_logger.info(log_data)

        # Log consent events immediately after user creation log
        # These logs intentionally omit IP, device fingerprint, and location
        consent_timestamp = datetime.utcnow().isoformat()

        # Log Privacy Policy consent
        privacy_consent_log = {
            "timestamp": consent_timestamp,
            "event_type": "consent",
            "user_id": user_id,
            "consent_type": "privacy_policy",
            "action": "granted",
            "version": consent_timestamp, # Use timestamp as version identifier
            "status": status
        }
        # Add sanitized details if they exist from the original call
        if 'details' in log_data:
             privacy_consent_log["details"] = log_data['details']
        compliance_logger.info(privacy_consent_log)

        # Log Terms of Service consent
        terms_consent_log = {
            "timestamp": consent_timestamp, # Use same timestamp
            "event_type": "consent",
            "user_id": user_id,
            "consent_type": "terms_of_service",
            "action": "granted",
            "version": consent_timestamp,
            "status": status
        }
        # Add sanitized details if they exist from the original call
        if 'details' in log_data:
             terms_consent_log["details"] = log_data['details']
        compliance_logger.info(terms_consent_log)

    @staticmethod
    def log_api_event(
        event_type: str,
        user_id: Optional[str] = None,
        status: str = "success",
        details: Optional[Dict[str, Any]] = None
    ):
        """
        Log an event to the API logs (not to compliance logs)
        No IP addresses are included in these logs
        
        Args:
            event_type: Type of event (invite_code_check, etc)
            user_id: User ID (if known)
            status: Outcome of the event (success, failed)
            details: Additional details to log (will be sanitized)
        """
        # Create log entry
        log_data = {
            "event_type": event_type,
            "user_id": user_id or "anonymous",
            "status": status
        }
        
        # Add details if provided (sanitize as needed)
        if details:
            # Filter out any sensitive fields
            sanitized_details = {k: v for k, v in details.items() 
                              if k not in ['password', 'token', 'secret']}
            log_data["details"] = sanitized_details
            
        # Use the specialized event logger - will always be stored
        event_logger.info(f"{event_type} - {status}", extra=log_data)
    
    @staticmethod
    def log_data_access(
        user_id: str,
        ip_address: str,
        action_type: str,  # export, delete, etc.
        data_type: str,  # user_data, chat_history, etc.
        status: str = "success",
        details: Optional[Dict[str, Any]] = None
    ):
        """Log data access events for GDPR compliance"""
        # Validate IP address
        try:
            ipaddress.ip_address(ip_address)
        except ValueError:
            ip_address = "0.0.0.0"
            
        # Create log entry
        log_data = {
            "timestamp": datetime.utcnow().isoformat(),
            "event_type": f"data_{action_type}",
            "user_id": user_id,
            "ip_address": ip_address,
            "data_type": data_type,
            "status": status
        }
        
        if details:
            sanitized_details = {k: v for k, v in details.items() 
                              if k not in ['password', 'token', 'secret']}
            log_data["details"] = sanitized_details
            
        # Log the event - pass log_data directly to preserve structured data
        compliance_logger.info(log_data)
    
    @staticmethod
    def log_consent(
        user_id: str,
        ip_address: str,
        consent_type: str,  # privacy_policy, terms, marketing, etc.
        action: str,  # granted, withdrawn, updated
        version: str,  # version of the policy/terms
        details: Optional[Dict[str, Any]] = None
    ):
        """Log consent-related events for GDPR compliance"""
        # Validate IP address
        try:
            ipaddress.ip_address(ip_address)
        except ValueError:
            ip_address = "0.0.0.0"
            
        # Create log entry
        log_data = {
            "timestamp": datetime.utcnow().isoformat(),
            "event_type": "consent",
            "user_id": user_id,
            "ip_address": ip_address,
            "consent_type": consent_type,
            "action": action,
            "version": version
        }
        
        if details:
            sanitized_details = {k: v for k, v in details.items()}
            log_data["details"] = sanitized_details
            
        # Log the event - pass log_data directly to preserve structured data
        compliance_logger.info(log_data)

    @staticmethod
    def log_auth_event_safe(
        event_type: str, 
        user_id: Optional[str],
        device_fingerprint: str,
        location: str,
        status: str = "success",
        details: Optional[Dict[str, Any]] = None
    ):
        """
        Log an authentication-related compliance event, but without storing IP address
        Used for routine successful logins from known devices
        
        Args:
            event_type: Type of event (login, etc)
            user_id: User ID
            device_fingerprint: Hashed device fingerprint
            location: Location derived from IP
            status: Outcome of the event (success, failed)
            details: Additional details to log (will be sanitized)
        """
        # Create log entry without IP address
        log_data = {
            "timestamp": datetime.utcnow().isoformat(),
            "event_type": event_type,
            "user_id": user_id or "anonymous",  # Never redact user_id in compliance logs
            "device_fingerprint": device_fingerprint,
            "location": location,
            "status": status
        }
        
        # Add details if provided (sanitize as needed)
        if details:
            # Filter out any sensitive fields
            sanitized_details = {k: v for k, v in details.items() 
                               if k not in ['password', 'token', 'secret']}
            log_data["details"] = sanitized_details
            
        # Log the raw dictionary - let the JSON handler format it
        compliance_logger.info(log_data)

    @staticmethod
    def log_account_deletion(
        user_id: str,
        deletion_type: str,  # policy_violation, user_requested, admin_action
        reason: str,
        ip_address: Optional[str] = None,
        device_fingerprint: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None
    ):
        """
        Log account deletion events for compliance and audit purposes
        
        Args:
            user_id: ID of the deleted user account
            deletion_type: Type of deletion (policy_violation, user_requested, admin_action)
            reason: Specific reason for deletion (repeated_inappropriate_images, harmful_content, etc.)
            ip_address: IP address of the request that triggered the deletion (if available)
            device_fingerprint: Device fingerprint of the request that triggered the deletion (if available)
            details: Additional context about the deletion
        """
        # Validate IP address if provided
        if ip_address:
            try:
                ipaddress.ip_address(ip_address)
            except ValueError:
                ip_address = "0.0.0.0"
            
        # Create log entry
        log_data = {
            "timestamp": datetime.utcnow().isoformat(),
            "event_type": "account_deletion",
            "user_id": user_id,
            "deletion_type": deletion_type,
            "reason": reason
        }
        
        # Add optional fields if provided
        if ip_address:
            log_data["ip_address"] = ip_address
            
        if device_fingerprint:
            log_data["device_fingerprint"] = device_fingerprint
        
        if details:
            log_data["details"] = details
            
        # Log to compliance logger with warning level for high visibility
        # Pass log_data directly to preserve structured data for monitoring tools
        compliance_logger.warning(log_data)
        
        # Also log to regular API logger
        api_logger.warning(
            f"ACCOUNT DELETION: User {user_id} deleted. Type: {deletion_type}, Reason: {reason}"
        )

    @staticmethod
    def log_chat_deletion(
        user_id: str,
        chat_id: str,
        device_fingerprint_hash: str,
        details: Optional[Dict[str, Any]] = None
    ):
        """
        Log a chat deletion event for compliance and audit purposes.
        
        Args:
            user_id: ID of the user who initiated the deletion.
            chat_id: ID of the chat that was deleted.
            device_fingerprint_hash: Hashed device fingerprint of the client that requested deletion.
            details: Additional context about the deletion.
        """

        log_data = {
            "timestamp": datetime.utcnow().isoformat(),
            "event_type": "chat_deletion",
            "user_id": user_id,
            "chat_id": chat_id,
            "device_fingerprint_hash": device_fingerprint_hash,
        }
        
        if details:
            # Sanitize details if necessary, similar to other logging methods
            sanitized_details = {k: v for k, v in details.items()
                               if k not in ['password', 'token', 'secret']}
            if sanitized_details: # Only add if there's anything left after sanitizing
                log_data["details"] = sanitized_details
            
        # Log to compliance logger
        # Pass log_data directly to preserve structured data for monitoring tools
        compliance_logger.info(log_data)
        
        # Optionally, also log to regular API logger for operational visibility if needed
        api_logger.info(
            f"CHAT DELETION: User {user_id} deleted chat {chat_id} via device {device_fingerprint_hash}."
        )

    @staticmethod
    def log_financial_transaction(
        user_id: str,
        transaction_type: str,  # credit_purchase, gift_card_redemption, subscription_renewal, etc.
        amount: Optional[Union[int, float]] = None,  # Credits or monetary amount
        currency: Optional[str] = None,  # Currency code if monetary
        status: str = "success",
        details: Optional[Dict[str, Any]] = None
    ):
        """
        Log financial transactions for compliance and audit purposes.
        This includes credit purchases, gift card redemptions, and subscription renewals.
        
        Args:
            user_id: ID of the user involved in the transaction
            transaction_type: Type of transaction (credit_purchase, gift_card_redemption, etc.)
            amount: Amount involved (credits or monetary value)
            currency: Currency code if this is a monetary transaction
            status: Outcome of the transaction (success, failed)
            details: Additional context about the transaction (order_id, gift_card_code, etc.)
        """
        # Create log entry
        log_data = {
            "timestamp": datetime.utcnow().isoformat(),
            "event_type": "financial_transaction",
            "transaction_type": transaction_type,
            "user_id": user_id,
            "status": status
        }
        
        # Add optional fields if provided
        if amount is not None:
            log_data["amount"] = amount
            
        if currency:
            log_data["currency"] = currency
        
        if details:
            # Sanitize details to remove sensitive information
            sanitized_details = {k: v for k, v in details.items() 
                              if k not in ['password', 'token', 'secret', 'payment_method_id', 'card_number']}
            log_data["details"] = sanitized_details
            
        # Log to compliance logger - pass log_data directly to preserve structured data
        compliance_logger.info(log_data)
        
        # Also log to regular API logger for operational visibility
        amount_str = f" {amount}" if amount is not None else ""
        currency_str = f" {currency}" if currency else ""
        api_logger.info(
            f"FINANCIAL TRANSACTION: User {user_id} - {transaction_type}{amount_str}{currency_str} - {status}"
        )

# TODO: Implement S3 archive functionality for compliance logs
# This will:
# 1. Periodically (daily) collect logs older than 48 hours
# 2. Encrypt them using Vault keys
# 3. Upload to S3 Hetzner
# 4. Verify upload and then delete from local storage
