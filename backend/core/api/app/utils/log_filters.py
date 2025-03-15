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
            
            # User ID pattern: uuid format
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
            if record.msg and isinstance(record.msg, str):
                # Save original message for debugging
                original_msg = record.msg
                
                # Apply redactions to the message string
                record.msg = self._redact_sensitive_data(record.msg)
                
                # Debug output to help diagnose filter behavior
                if self.debug and original_msg != record.msg:
                    print(f"FILTER DEBUG: Original: {original_msg!r} -> Filtered: {record.msg!r}")
                
            # Also check for args that might contain sensitive data
            if record.args:
                record.args = self._sanitize_args(record.args)
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
    
    def _sanitize_args(self, args):
        """Sanitize log record args, whether tuple, dict or single value."""
        if isinstance(args, dict):
            return {k: self._sanitize_value(k, v) for k, v in args.items()}
        elif isinstance(args, (list, tuple)):
            return tuple(self._sanitize_value('', arg) for arg in args)
        else:
            return self._sanitize_value('', args)
    
    def _sanitize_value(self, key: str, value) -> str:
        """
        Sanitize a single value that might be used in a log message.
        Redacts values for sensitive keys, and checks string values for sensitive patterns.
        """
        # Check if the key suggests this is a sensitive field
        sensitive_keys = ['password', 'token', 'secret', 'key', 'email', 'user', 'ip']
        
        if any(s_key in key.lower() for s_key in sensitive_keys):
            return "[REDACTED]"
        
        # For string values, check if they match sensitive patterns
        if isinstance(value, str):
            return self._redact_sensitive_data(value)
        
        return value
