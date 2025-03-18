import logging
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
    
    # Create a file handler for compliance logs
    log_dir = os.path.join(os.getenv('LOG_DIR', '/app/logs'))
    os.makedirs(log_dir, exist_ok=True)
    compliance_file = os.path.join(log_dir, 'compliance.log')
    
    file_handler = logging.FileHandler(compliance_file)
    
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
