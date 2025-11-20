import logging
import logging.handlers
import os
from pythonjsonlogger import jsonlogger
import json

def setup_compliance_logging():
    """
    Configure the compliance logger to properly format logs as JSON.
    
    This ensures:
    1. User IDs are not redacted in compliance logs
    2. The logs are properly formatted as JSON without double-encoding
    3. All necessary compliance fields are included
    """
    # Get the compliance logger
    compliance_logger = logging.getLogger("compliance")
    
    # Remove existing handlers
    for handler in compliance_logger.handlers:
        compliance_logger.removeHandler(handler)
    
    # Create a time-based rotating file handler for compliance logs
    # CRITICAL: Compliance logs must be retained per legal requirements (e.g., 10 years for tax/commercial law)
    # These logs use time-based rotation (not size-based) and are NEVER automatically deleted
    # Default: Daily rotation, keep ALL backups (backupCount=0 means unlimited retention)
    log_dir = os.path.join(os.getenv('LOG_DIR', '/app/logs'))
    os.makedirs(log_dir, exist_ok=True)
    compliance_file = os.path.join(log_dir, 'compliance.log')
    
    # Compliance log rotation configuration: time-based rotation with long retention
    # Can be overridden via environment variables:
    #   COMPLIANCE_LOG_WHEN: 'D' (daily), 'W' (weekly), 'M' (monthly) - default: 'D'
    #   COMPLIANCE_LOG_BACKUP_COUNT: Number of backup files to keep (0 = keep all, default: 0)
    #   COMPLIANCE_LOG_INTERVAL: Rotation interval (default: 1, meaning 1 day/week/month)
    compliance_log_when = os.getenv("COMPLIANCE_LOG_WHEN", "D")  # Daily rotation
    compliance_log_interval = int(os.getenv("COMPLIANCE_LOG_INTERVAL", "1"))  # Every 1 day
    # backupCount=0 means keep ALL rotated files (no automatic deletion)
    # Set to a number if you want to limit (e.g., 3650 for ~10 years of daily logs)
    compliance_log_backup_count = int(os.getenv("COMPLIANCE_LOG_BACKUP_COUNT", "0"))  # 0 = keep all
    
    file_handler = logging.handlers.TimedRotatingFileHandler(
        compliance_file,
        when=compliance_log_when,
        interval=compliance_log_interval,
        encoding='utf-8',
        backupCount=compliance_log_backup_count
        # CRITICAL: backupCount=0 means compliance logs are NEVER automatically deleted
        # Manual deletion/archiving must be done based on legal retention requirements
    )
    
    # Create a custom formatter for compliance logs
    class ComplianceJsonFormatter(jsonlogger.JsonFormatter):
        """Custom formatter that ensures user_ids are not redacted and proper JSON formatting"""
        
        def add_fields(self, log_record, record, message_dict):
            super().add_fields(log_record, record, message_dict)
            
            # If the message is a dict, extract its fields
            if isinstance(record.msg, dict):
                # Add all fields from the dict to the output
                for key, value in record.msg.items():
                    log_record[key] = value
            
            # Add standard fields if not present
            if 'timestamp' not in log_record:
                log_record['timestamp'] = self.formatTime(record, self.datefmt)
                
            # Ensure log level is included
            log_record['level'] = record.levelname
    
    # Configure the formatter
    formatter = ComplianceJsonFormatter(
        '%(asctime)s %(name)s %(levelname)s %(message)s',
        rename_fields={
            'asctime': 'timestamp',
            'levelname': 'level',
            'name': 'logger'
        }
    )
    file_handler.setFormatter(formatter)
    
    # Set the level and add the handler
    compliance_logger.setLevel(logging.INFO)
    compliance_logger.addHandler(file_handler)
    
    # Make the compliance logger propagate=False to avoid double logging
    compliance_logger.propagate = False
    
    # Add a console handler if in development mode
    if os.getenv('ENVIRONMENT', 'development') == 'development':
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        compliance_logger.addHandler(console_handler)
    
    return compliance_logger
