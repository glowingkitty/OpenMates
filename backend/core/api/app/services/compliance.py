import logging
import json
from datetime import datetime
from typing import Optional, Dict, Any, Union
import ipaddress

# Configure a special logger for compliance events
compliance_logger = logging.getLogger("compliance")

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
            "user_id": user_id or "anonymous",
            "ip_address": ip_address,
            "status": status
        }
        
        # Add details if provided (sanitize as needed)
        if details:
            # Filter out any sensitive fields
            sanitized_details = {k: v for k, v in details.items() 
                              if k not in ['password', 'token', 'secret']}
            log_data["details"] = sanitized_details
            
        # Log the event
        compliance_logger.info(json.dumps(log_data))
    
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
            
        # Log the event
        compliance_logger.info(json.dumps(log_data))
    
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
            
        # Log the event
        compliance_logger.info(json.dumps(log_data))

# TODO: Implement S3 archive functionality for compliance logs
# This will:
# 1. Periodically (daily) collect logs older than 48 hours
# 2. Encrypt them using Vault keys
# 3. Upload to S3 Hetzner
# 4. Verify upload and then delete from local storage
