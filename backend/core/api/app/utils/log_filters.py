import re
import logging
import os
from typing import Dict, Pattern, Optional

class SensitiveDataFilter(logging.Filter):
    """
    A logging filter that redacts sensitive information from log messages.
    """
    
    def __init__(self, name: str = ""):
        super().__init__(name)
        
        # Enable debug mode through environment variable
        self.debug = os.environ.get("LOG_FILTER_DEBUG", "").lower() in ("1", "true", "yes")
        
        # Common patterns for sensitive data
        self.patterns: Dict[str, Pattern] = {
            # Email pattern: username@domain.com
            "email": re.compile(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+'),
            
            # IP Address pattern: IPv4 and simple IPv6
            "ip": re.compile(r'\b(?:\d{1,3}\.){3}\d{1,3}\b|'  # IPv4
                             r'(?:[0-9a-fA-F]{1,4}:){7,7}[0-9a-fA-F]{1,4}|'  # IPv6
                             r'(?:[0-9a-fA-F]{1,4}:){1,7}:|'
                             r'(?:[0-9a-fA-F]{1,4}:){1,6}:[0-9a-fA-F]{1,4}'),
            
            # User ID pattern: uuid format - NOT used for compliance logs
            "uuid": re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', re.IGNORECASE),
            
            # Password value pattern
            "password": re.compile(r'"?password"?\s*[:=]\s*"?[^",\s]+"?', re.IGNORECASE),
            
            # Token pattern
            "token": re.compile(r'"?(?:api_?key|token|secret|jwt)"?\s*[:=]\s*"?[^",\s]+"?', re.IGNORECASE),
            
            # Bearer auth header pattern
            "bearer": re.compile(r'[Bb]earer\s+[A-Za-z0-9-_=]+\.[A-Za-z0-9-_=]+\.?[A-Za-z0-9-_.+/=]*')
        }
        
        # Replacement templates
        self.replacements = {
            "email": "***@***.***",
            "ip": "[REDACTED_IP]",
            "uuid": "[REDACTED_ID]",
            "password": '"password": "[REDACTED]"',
            "token": '"token": "[REDACTED]"',
            "bearer": "Bearer [REDACTED]"
        }
    
    def filter(self, record: logging.LogRecord) -> bool:
        """
        Filter log records by redacting sensitive information from messages.
        Returns True to keep the record, with modified content.
        """
        try:
            # Special handling for compliance logger - don't redact user_id
            is_compliance_log = getattr(record, 'name', '').startswith('compliance')
            
            # If this is a record with extra data (dict)
            if hasattr(record, 'msg') and isinstance(record.msg, dict):
                # For compliance logs, preserve user_id
                if is_compliance_log and 'user_id' in record.msg:
                    # Don't modify user_id
                    pass
                else:
                    # Apply normal redaction to dict fields
                    self._redact_dict_fields(record.msg)
            # If this is a string message
            elif record.msg and isinstance(record.msg, str):
                # Save original message for debugging
                original_msg = record.msg
                
                # Apply redactions to the message string, but for compliance logs skip uuid redaction
                if is_compliance_log:
                    # For compliance logs, apply all patterns except UUID
                    for pattern_name, pattern in self.patterns.items():
                        if pattern_name != "uuid":  # Skip UUID redaction for compliance logs
                            record.msg = pattern.sub(self.replacements[pattern_name], record.msg)
                else:
                    # Normal redaction for all other logs
                    record.msg = self._redact_sensitive_data(record.msg)
                
                # Debug output to help diagnose filter behavior
                if self.debug and original_msg != record.msg:
                    print(f"FILTER DEBUG: Original: {original_msg!r} -> Filtered: {record.msg!r}")
                
            # Also check for args that might contain sensitive data
            if record.args:
                record.args = self._sanitize_args(record.args, is_compliance_log)
                
        except Exception as e:
            # If anything goes wrong in filtering, just log it but allow the message through
            if self.debug:
                print(f"FILTER ERROR: {str(e)}")
        
        # Always allow the message through - filtering just redacts sensitive data
        return True
    
    def _redact_sensitive_data(self, message: str) -> str:
        """Replace sensitive data patterns in the message with redacted values."""
        for pattern_name, pattern in self.patterns.items():
            message = pattern.sub(self.replacements[pattern_name], message)
        return message
    
    def _redact_dict_fields(self, data: dict) -> None:
        """Redact sensitive fields in a dictionary in-place, preserving user_id."""
        for key, value in data.items():
            # Never redact user_id field in compliance logs
            if key == 'user_id':
                continue
                
            # Recursively process nested dictionaries
            if isinstance(value, dict):
                self._redact_dict_fields(value)
                continue
                
            # Redact string values using patterns
            if isinstance(value, str):
                # Skip UUID redaction for user_id field
                if key == 'user_id':
                    for pattern_name, pattern in self.patterns.items():
                        if pattern_name != "uuid":
                            value = pattern.sub(self.replacements[pattern_name], value)
                else:
                    value = self._redact_sensitive_data(value)
                data[key] = value
    
    def _sanitize_args(self, args, is_compliance_log=False):
        """Sanitize log record args, whether tuple, dict or single value."""
        if isinstance(args, dict):
            # For dictionaries, create a copy then modify
            result = args.copy()
            for k, v in result.items():
                # Skip user_id for compliance logs
                if is_compliance_log and k == 'user_id':
                    continue
                result[k] = self._sanitize_value(k, v, is_compliance_log)
            return result
        elif isinstance(args, (list, tuple)):
            return tuple(self._sanitize_value('', arg, is_compliance_log) for arg in args)
        else:
            return self._sanitize_value('', args, is_compliance_log)
    
    def _sanitize_value(self, key: str, value, is_compliance_log=False) -> str:
        """
        Sanitize a single value that might be used in a log message.
        Redacts values for sensitive keys, and checks string values for sensitive patterns.
        """
        # Don't redact user_id for compliance logs
        if is_compliance_log and key == 'user_id':
            return value
            
        # Check if the key suggests this is a sensitive field
        sensitive_keys = ['password', 'token', 'secret', 'key', 'email', 'ip']
        sensitive_keys_for_compliance = ['password', 'token', 'secret', 'key', 'email']
        
        check_keys = sensitive_keys_for_compliance if is_compliance_log else sensitive_keys
        
        if any(s_key in key.lower() for s_key in check_keys):
            return "[REDACTED]"
        
        # For string values, check if they match sensitive patterns
        if isinstance(value, str):
            if is_compliance_log:
                # For compliance logs, redact everything except user_id
                for pattern_name, pattern in self.patterns.items():
                    if pattern_name != "uuid":
                        value = pattern.sub(self.replacements[pattern_name], value)
            else:
                value = self._redact_sensitive_data(value)
        
        return value
